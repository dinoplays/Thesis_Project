# main.py
# Red Bit-Manipulative pipeline:
#   raw cross data conversion
#   -> construct EPIs
#   -> bit-manipulative confidence + derivatives for red channel
#   -> fixed-point horizontal/vertical disparity
#   -> confidence-weighted disparity fusion
#   -> final fixed 7x7 2D low-pass on non-filled disparity
#   -> confidence-guided region filling
#   -> final fixed 7x7 2D low-pass on filled disparity
#
# All IMGB numeric outputs after cross conversion are stored as:
#   dtype_code=4 (u24), biased signed Q12.12 (see utils.py)
#
# Architecture matches the newer standard Red No-Libraries version:
#   - no pre-EPI low-pass
#   - final post-disparity 7x7 low-pass is applied to both:
#       1) the non-filled fused disparity, for direct FPGA comparison
#       2) the filled fused disparity, for future-work dense output
#
# Bit-manipulative version:
#   Uses Python_Red/Bit_Manipulation paths.
#   Uses Q12.12 integer scale values for d, ds, dt, du, dv.
#   Uses fixed-point confidence/disparity/fusion logic.

import os
import time

import cross
import EPIs
import confidence
import disparity
import region_filling
import convolve
import utils
import bin_to_png


REGION_FILL_CONFIDENCE_THRESHOLD = 1.25


if __name__ == "__main__":
    for scene in ["dino", "head", "town"]:
        print(f"\n=== Processing Red bit-manipulative scene: {scene} ===")

        scene_dir = f"Python_Red/Bit_Manipulation/{scene}"

        cross_dir_raw = os.path.join(scene_dir, "cross_raw_data")
        cross_dir = os.path.join(scene_dir, "cross_data_q12_12")
        disp_dir = os.path.join(scene_dir, "disparity")
        conf_dir = os.path.join(scene_dir, "confidence")

        stage_times_ns = {}

        def _stage_begin() -> int:
            return time.perf_counter_ns()

        def _stage_end(stage_name: str, t0_ns: int) -> None:
            dt_ns = time.perf_counter_ns() - t0_ns
            stage_times_ns[stage_name] = stage_times_ns.get(stage_name, 0) + dt_ns

        compute_t0_ns = time.perf_counter_ns()

        # --- 1) Convert raw u8 RGB IMGB into Q12.12 u24 IMGB
        print("Converting raw red-pipeline cross data to Q12.12 u24 IMGB")
        t0 = _stage_begin()
        cross.convert_cross_u8_to_q12_12(cross_dir_raw, cross_dir)
        _stage_end("1) Cross data Q12.12 conversion", t0)

        # --- 2) Construct EPIs
        print("Building horizontal/vertical EPIs (IMGB blobs)")
        t0 = _stage_begin()
        epi_h_imgb, epi_v_imgb = EPIs.load_cross_crops_and_build_epis_imgb(cross_dir)
        _stage_end("2) Build EPIs", t0)

        # --- 3) Confidence + derivatives for red channel only
        print("Computing bit-manipulative confidence maps and derivatives for red channel")
        t0 = _stage_begin()
        C_h, C_v, dL_du_h, dL_dv_v, dL_ds_h, dL_dt_v = confidence.compute_from_epis_with_diffs(
            epi_h_imgb,
            epi_v_imgb,
            channel=0,
        )
        _stage_end("3a) Confidence + angular/spatial diffs (red)", t0)

        t0 = _stage_begin()
        C_avg_raw = confidence.fuse_avg(C_h, C_v)
        _stage_end("3b) FPGA-style confidence fuse sum", t0)

        os.makedirs(conf_dir, exist_ok=True)
        utils.save_imgb(C_h, os.path.join(conf_dir, "C_h.imgb"))
        utils.save_imgb(C_v, os.path.join(conf_dir, "C_v.imgb"))
        utils.save_imgb(C_avg_raw, os.path.join(conf_dir, "C_avg_raw.imgb"))

        # --- 4) Fixed-point disparity per-axis
        Q = utils.Q_SCALE

        d = Q
        ds = Q
        dt = Q
        du = Q
        dv = Q

        print("Estimating fixed-point disparity per-axis (horizontal & vertical)")
        t0 = _stage_begin()
        Z_h = disparity.compute_horizontal_from_epis(
            epi_h_imgb,
            dL_du_h,
            dL_ds_h,
            d=d,
            ds=ds,
            du=du,
            win=5,
        )
        _stage_end("4a) Disparity horizontal", t0)

        t0 = _stage_begin()
        Z_v = disparity.compute_vertical_from_epis(
            epi_v_imgb,
            dL_dv_v,
            dL_dt_v,
            d=d,
            dt=dt,
            dv=dv,
            win=5,
        )
        _stage_end("4b) Disparity vertical", t0)

        # --- 5) Confidence-weighted fixed-point disparity fusion
        print("Fusing disparity using fixed-point confidence weights")
        t0 = _stage_begin()
        Z_conf_raw = disparity.fuse_disparity_precision(
            Z_h,
            Z_v,
            C_h,
            C_v,
            temperature=1,
            floor=0,
            cap=Q,
            eps=0,
        )
        _stage_end("5) Fuse disparity precision", t0)

        # --- 6) Final fixed 7x7 post-disparity 2D low-pass on NON-FILLED output
        #
        # This is the direct Python reference for the current FPGA pipeline,
        # because the FPGA applies the final low-pass but does not perform
        # confidence-guided region filling.
        #
        # Keep this as Z_conf.imgb so existing comparison scripts compare the
        # FPGA output against the non-filled blurred Python output.
        print("Applying final fixed 7x7 2D low-pass to non-filled disparity")
        t0 = _stage_begin()
        Z_conf = convolve.low_pass_q12_12_single_channel(Z_conf_raw)
        C_avg = convolve.low_pass_q12_12_single_channel(C_avg_raw)
        _stage_end("6) Final fixed 7x7 non-filled disparity/confidence low-pass", t0)

        # --- 7) Confidence-guided region filling
        #
        # This is retained as a future-work dense-output stage. It is not the
        # default Z_conf comparison target because the current FPGA does not
        # implement this filling stage.
        print("Applying confidence-guided region filling")
        t0 = _stage_begin()
        Z_conf_filled = region_filling.fill_regions_q12_12_single_channel(
            Z_conf_raw,
            C_avg_raw,
            confidence_threshold=REGION_FILL_CONFIDENCE_THRESHOLD,
        )
        _stage_end("7) Confidence-guided region filling", t0)

        # --- 8) Final fixed 7x7 post-disparity 2D low-pass on FILLED output
        #
        # This produces the dense/future-work visual output while keeping the
        # direct FPGA-comparison output separate.
        print("Applying final fixed 7x7 2D low-pass to filled disparity")
        t0 = _stage_begin()
        Z_conf_filled_blurred = convolve.low_pass_q12_12_single_channel(Z_conf_filled)
        _stage_end("8) Final fixed 7x7 filled disparity low-pass", t0)

        utils.save_imgb(C_avg, os.path.join(conf_dir, "C_avg.imgb"))
        utils.save_imgb(C_avg, os.path.join(conf_dir, "C_avg_nonfilled_blurred.imgb"))

        os.makedirs(disp_dir, exist_ok=True)
        utils.save_imgb(Z_h, os.path.join(disp_dir, "Z_h.imgb"))
        utils.save_imgb(Z_v, os.path.join(disp_dir, "Z_v.imgb"))

        # Raw fused output before any post-processing.
        utils.save_imgb(Z_conf_raw, os.path.join(disp_dir, "Z_conf_raw.imgb"))

        # Direct FPGA-comparison output:
        # fused output + final low-pass, but NO region filling.
        utils.save_imgb(Z_conf, os.path.join(disp_dir, "Z_conf.imgb"))
        utils.save_imgb(Z_conf, os.path.join(disp_dir, "Z_conf_nonfilled_blurred.imgb"))

        # Future-work dense outputs:
        # filled output before and after the final low-pass.
        utils.save_imgb(Z_conf_filled, os.path.join(disp_dir, "Z_conf_filled.imgb"))
        utils.save_imgb(
            Z_conf_filled_blurred,
            os.path.join(disp_dir, "Z_conf_filled_blurred.imgb"),
        )

        compute_total_ns = time.perf_counter_ns() - compute_t0_ns
        print("Computations complete.")

        ordered = [
            "1) Cross data Q12.12 conversion",
            "2) Build EPIs",
            "3a) Confidence + angular/spatial diffs (red)",
            "3b) Confidence fuse avg",
            "4a) Disparity horizontal",
            "4b) Disparity vertical",
            "5) Fuse disparity precision",
            "6) Final fixed 7x7 non-filled disparity/confidence low-pass",
            "7) Confidence-guided region filling",
            "8) Final fixed 7x7 filled disparity low-pass",
        ]

        timing_path = os.path.join(scene_dir, "compute_timings.txt")
        os.makedirs(scene_dir, exist_ok=True)

        with open(timing_path, "w") as f:
            f.write("=== Compute Timings Summary (nanoseconds, excludes saves) ===\n\n")

            for name in ordered:
                if name in stage_times_ns:
                    f.write(f"{name}: {stage_times_ns[name]} ns\n")

            f.write("\n")
            f.write(f"TOTAL compute time: {compute_total_ns} ns\n")
            f.write("===========================================================")

        bin_to_png.convert_scene_imgb_to_png(
            scene_dir=scene_dir,
            reliable_thresh=REGION_FILL_CONFIDENCE_THRESHOLD,
            # Z_conf.imgb is the non-filled blurred output, matching the
            # current FPGA pipeline more directly than the filled output.
            z_conf_rel_path="disparity/Z_conf.imgb",
            c_avg_rel_path="confidence/C_avg.imgb",
            reliable_base_name="reliable_avg_Z_conf_1p25",
        )

        print("Saves complete.")

    print("\nAll complete.")

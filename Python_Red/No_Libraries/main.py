# main.py
# Pipeline:
#   raw cross data conversion
#   -> construct EPIs
#   -> confidence
#   -> disparity
#   -> confidence fusion
#   -> final fixed 7x7 2D low-pass on non-filled disparity
#   -> confidence-guided region filling
#   -> final fixed 7x7 2D low-pass on filled disparity
#
# All IMGB numeric outputs after cross conversion are stored as:
#   dtype_code=4 (u24), biased signed Q12.12 (see utils.py)
#
# The old pre-EPI low-pass has been removed.
# The low-pass filter is applied to both:
#   - Z_conf_raw, producing Z_conf.imgb for direct FPGA comparison
#   - Z_conf_filled, producing Z_conf_filled_blurred.imgb for future dense-output work
#
# Non-bit-manipulative version:
#   Uses Python_Red/No_Libraries paths.
#   Uses floating-point scale values for d, ds, dt, du, dv.
#   Uses floating-point fusion parameters.
#
# Only necessary computations are timed.

import os
import time

import cross           # u8 RGB -> Q12.12 u24 RGB conversion only
import EPIs            # load stacks -> builds EPI IMGB blobs
import confidence      # C_h, C_v and AVG, plus angular/spatial diffs
import disparity       # stdlib-only, works on IMGB blobs
import region_filling  # confidence-guided region filling
import convolve        # final fixed 7x7 post-disparity 2D low-pass
import utils           # IMGB helpers + saves
import bin_to_png      # converts IMGB folders to PNG


EPS = 1 / 4096  # Q12.12 LSB

REGION_FILL_CONFIDENCE_THRESHOLD = 1.25


if __name__ == "__main__":
    for scene in ["dino", "head", "town"]:
        print(f"\n=== Processing scene: {scene} ===")

        # --- Paths
        scene_dir = f"Python_Red/No_Libraries/{scene}"

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
        print("Converting raw cross data to Q12.12 u24 IMGB")
        t0 = _stage_begin()
        cross.convert_cross_u8_to_q12_12(cross_dir_raw, cross_dir)
        _stage_end("1) Cross data Q12.12 conversion", t0)

        # --- 2) Construct EPIs
        print("Building horizontal/vertical EPIs (IMGB blobs)")
        t0 = _stage_begin()
        epi_h_imgb, epi_v_imgb = EPIs.load_cross_crops_and_build_epis_imgb(cross_dir)
        _stage_end("2) Build EPIs", t0)

        # --- 3) CONFIDENCE (+ angular and spatial diffs computed ONCE)
        print("Computing confidence maps (C_h, C_v and AVG)")
        t0 = _stage_begin()
        C_h, C_v, dL_du_h, dL_dv_v, dL_ds_h, dL_dt_v = confidence.compute_from_epis_with_diffs(
            epi_h_imgb,
            epi_v_imgb,
            channel=None
        )
        _stage_end("3a) Confidence + angular/spatial diffs", t0)

        t0 = _stage_begin()
        C_avg = confidence.fuse_avg(C_h, C_v)
        _stage_end("3b) Confidence fuse avg", t0)

        # Save confidence IMGB blobs
        os.makedirs(conf_dir, exist_ok=True)
        utils.save_imgb(C_h, os.path.join(conf_dir, "C_h.imgb"))
        utils.save_imgb(C_v, os.path.join(conf_dir, "C_v.imgb"))
        utils.save_imgb(C_avg, os.path.join(conf_dir, "C_avg.imgb"))

        # --- 4) DISPARITY per-axis
        d = 1.0
        ds = 1.0
        dt = 1.0
        du = 1.0
        dv = 1.0

        print("Estimating disparity per-axis (horizontal & vertical)")
        t0 = _stage_begin()
        Z_h = disparity.compute_horizontal_from_epis(
            epi_h_imgb,
            dL_du_h,
            dL_ds_h,
            d=d,
            ds=ds,
            du=du,
            win=5
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
            win=5
        )
        _stage_end("4b) Disparity vertical", t0)

        # --- 5) Confidence-weighted disparity fusion
        print("Fusing disparity using confidence")
        t0 = _stage_begin()
        Z_conf_raw = disparity.fuse_disparity_precision(
            Z_h,
            Z_v,
            C_h,
            C_v,
            temperature=4.0,
            floor=1 / 4096,
            cap=1.0,
            eps=EPS,
        )
        _stage_end("5) Fuse disparity precision", t0)

        # --- 6) Final fixed 7x7 post-disparity 2D low-pass on NON-FILLED output
        # This is the direct comparison target for the FPGA output, because the
        # current FPGA implementation does not perform confidence-guided region
        # filling. Keep this as Z_conf.imgb so existing comparison/conversion
        # scripts use the non-filled blurred result by default.
        print("Applying final fixed 7x7 2D low-pass to non-filled disparity")
        t0 = _stage_begin()
        Z_conf_nonfilled_blurred = convolve.low_pass_q12_12_single_channel(Z_conf_raw)
        _stage_end("6) Final fixed 7x7 disparity low-pass on non-filled output", t0)

        # --- 7) Confidence-guided region filling
        # This is kept as a future-work output path. It is not the direct FPGA
        # comparison target unless equivalent region filling is added in hardware.
        print("Applying confidence-guided region filling")
        t0 = _stage_begin()
        Z_conf_filled = region_filling.fill_regions_q12_12_single_channel(
            Z_conf_raw,
            C_avg,
            confidence_threshold=REGION_FILL_CONFIDENCE_THRESHOLD
        )
        _stage_end("7) Confidence-guided region filling", t0)

        # --- 8) Final fixed 7x7 post-disparity 2D low-pass on FILLED output
        print("Applying final fixed 7x7 2D low-pass to filled disparity")
        t0 = _stage_begin()
        Z_conf_filled_blurred = convolve.low_pass_q12_12_single_channel(Z_conf_filled)
        _stage_end("8) Final fixed 7x7 disparity low-pass on filled output", t0)

        # Save disparity IMGB blobs
        os.makedirs(disp_dir, exist_ok=True)

        utils.save_imgb(Z_h, os.path.join(disp_dir, "Z_h.imgb"))
        utils.save_imgb(Z_v, os.path.join(disp_dir, "Z_v.imgb"))

        # Raw fused disparity before region filling and final smoothing.
        utils.save_imgb(Z_conf_raw, os.path.join(disp_dir, "Z_conf_raw.imgb"))

        # Non-filled fused disparity after final smoothing.
        # This is the direct comparison target for the FPGA implementation.
        utils.save_imgb(Z_conf_nonfilled_blurred, os.path.join(disp_dir, "Z_conf.imgb"))
        utils.save_imgb(
            Z_conf_nonfilled_blurred,
            os.path.join(disp_dir, "Z_conf_nonfilled_blurred.imgb"),
        )

        # Region-filled disparity before final smoothing.
        utils.save_imgb(Z_conf_filled, os.path.join(disp_dir, "Z_conf_filled.imgb"))

        # Region-filled disparity after final smoothing.
        # This is retained for future FPGA work that adds region filling.
        utils.save_imgb(
            Z_conf_filled_blurred,
            os.path.join(disp_dir, "Z_conf_filled_blurred.imgb"),
        )

        compute_total_ns = time.perf_counter_ns() - compute_t0_ns
        print("Computations complete.")

        ordered = [
            "1) Cross data Q12.12 conversion",
            "2) Build EPIs",
            "3a) Confidence + angular/spatial diffs",
            "3b) Confidence fuse avg",
            "4a) Disparity horizontal",
            "4b) Disparity vertical",
            "5) Fuse disparity precision",
            "6) Final fixed 7x7 disparity low-pass on non-filled output",
            "7) Confidence-guided region filling",
            "8) Final fixed 7x7 disparity low-pass on filled output",
        ]

        # ---------- Write compute timing summary to file ----------
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

        # Convert all IMGB to PNG.
        # This will also convert:
        #   Z_conf_raw.imgb
        #   Z_conf.imgb                         -> non-filled + smoothed
        #   Z_conf_nonfilled_blurred.imgb       -> duplicate explicit name
        #   Z_conf_filled.imgb                  -> filled, not smoothed
        #   Z_conf_filled_blurred.imgb          -> filled + smoothed
        #
        # Z_conf.imgb is intentionally the non-filled + smoothed disparity map,
        # because this is the direct comparison target for the current FPGA.
        bin_to_png.convert_scene_imgb_to_png(
            scene_dir=scene_dir,
            reliable_thresh=REGION_FILL_CONFIDENCE_THRESHOLD,
            z_conf_rel_path="disparity/Z_conf.imgb",
            c_avg_rel_path="confidence/C_avg.imgb",
            reliable_base_name="reliable_avg_Z_conf_1p25",
        )

        print("Saves complete.")

    print("\nAll complete.")
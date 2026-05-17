# main.py
# Pipeline: bit-shift convolve -> construct EPIs -> CONFIDENCE -> DISPARITY (uses confidence)
# All IMGB numeric outputs after cross are stored as:
#   dtype_code=4 (u24), biased signed Q12.12 (see utils.py)
# Crop is already 512 x 512 sized images
#
# RGB version:
#   - Computes confidence and derivatives separately for R, G, and B.
#   - Computes horizontal and vertical disparity separately for R, G, and B.
#   - Fuses RGB disparity using confidence-weighted RGB fusion.

import os
import time

import cross       # bit-shift low-pass + crop extraction -> outputs Q12.12 u24 IMGB
import EPIs        # load stacks -> builds EPI IMGB blobs (still Q12.12 u24)
import confidence  # C_h, C_v and AVG, plus angular/spatial diffs
import disparity   # fixed-point disparity and RGB fusion
import utils       # IMGB helpers + saves
import bin_to_png  # converts IMGB folders to PNG


if __name__ == "__main__":
    kernel_size = 7

    for scene in ["dino", "head", "town"]:
        print(f"\n=== Processing scene: {scene} ===")

        # --- Paths
        cross_dir_raw = f"Python_RGB/Bit_Manipulation/{scene}/cross_raw_data"
        cross_dir     = f"Python_RGB/Bit_Manipulation/{scene}/cross_data_blurred"
        disp_dir      = f"Python_RGB/Bit_Manipulation/{scene}/disparity"
        conf_dir      = f"Python_RGB/Bit_Manipulation/{scene}/confidence"

        stage_times_ns = {}

        def _stage_begin() -> int:
            return time.perf_counter_ns()

        def _stage_end(stage_name: str, t0_ns: int) -> None:
            dt_ns = time.perf_counter_ns() - t0_ns
            stage_times_ns[stage_name] = stage_times_ns.get(stage_name, 0) + dt_ns

        compute_t0_ns = time.perf_counter_ns()

        # --- 1) Apply low-pass filter
        print("Applying bit-shift low-pass filter")
        t0 = _stage_begin()
        cross.bit_shift_low_pass_filter(
            cross_dir_raw,
            kernel_size=kernel_size,
            out_dir=cross_dir
        )
        _stage_end("1) Low-pass filter", t0)

        # --- 2) Construct EPIs
        print("Building horizontal/vertical EPIs (IMGB blobs)")
        t0 = _stage_begin()
        epi_h_imgb, epi_v_imgb = EPIs.load_cross_crops_and_build_epis_imgb(cross_dir)
        _stage_end("2) Build EPIs", t0)

        # --- 3) CONFIDENCE + DERIVATIVES per RGB channel
        print("Computing confidence maps and derivatives for RGB")

        # Red
        t0 = _stage_begin()
        (
            C_h_red,
            C_v_red,
            dL_du_h_red,
            dL_dv_v_red,
            dL_ds_h_red,
            dL_dt_v_red,
        ) = confidence.compute_from_epis_with_diffs(
            epi_h_imgb,
            epi_v_imgb,
            channel=0
        )
        _stage_end("3a) Confidence + angular/spatial diffs (red)", t0)

        t0 = _stage_begin()
        C_avg_red = confidence.fuse_avg(C_h_red, C_v_red)
        _stage_end("3b) Confidence fuse avg (red)", t0)

        # Green
        t0 = _stage_begin()
        (
            C_h_green,
            C_v_green,
            dL_du_h_green,
            dL_dv_v_green,
            dL_ds_h_green,
            dL_dt_v_green,
        ) = confidence.compute_from_epis_with_diffs(
            epi_h_imgb,
            epi_v_imgb,
            channel=1
        )
        _stage_end("3c) Confidence + angular/spatial diffs (green)", t0)

        t0 = _stage_begin()
        C_avg_green = confidence.fuse_avg(C_h_green, C_v_green)
        _stage_end("3d) Confidence fuse avg (green)", t0)

        # Blue
        t0 = _stage_begin()
        (
            C_h_blue,
            C_v_blue,
            dL_du_h_blue,
            dL_dv_v_blue,
            dL_ds_h_blue,
            dL_dt_v_blue,
        ) = confidence.compute_from_epis_with_diffs(
            epi_h_imgb,
            epi_v_imgb,
            channel=2
        )
        _stage_end("3e) Confidence + angular/spatial diffs (blue)", t0)

        t0 = _stage_begin()
        C_avg_blue = confidence.fuse_avg(C_h_blue, C_v_blue)
        _stage_end("3f) Confidence fuse avg (blue)", t0)

        # --- Save confidence IMGB blobs
        os.makedirs(conf_dir, exist_ok=True)

        # Keep original filenames mapped to red for compatibility with bin_to_png.
        utils.save_imgb(C_h_red,   os.path.join(conf_dir, "C_h.imgb"))
        utils.save_imgb(C_v_red,   os.path.join(conf_dir, "C_v.imgb"))
        utils.save_imgb(C_avg_red, os.path.join(conf_dir, "C_avg.imgb"))

        utils.save_imgb(C_h_red,   os.path.join(conf_dir, "C_h_red.imgb"))
        utils.save_imgb(C_v_red,   os.path.join(conf_dir, "C_v_red.imgb"))
        utils.save_imgb(C_avg_red, os.path.join(conf_dir, "C_avg_red.imgb"))

        utils.save_imgb(C_h_green,   os.path.join(conf_dir, "C_h_green.imgb"))
        utils.save_imgb(C_v_green,   os.path.join(conf_dir, "C_v_green.imgb"))
        utils.save_imgb(C_avg_green, os.path.join(conf_dir, "C_avg_green.imgb"))

        utils.save_imgb(C_h_blue,   os.path.join(conf_dir, "C_h_blue.imgb"))
        utils.save_imgb(C_v_blue,   os.path.join(conf_dir, "C_v_blue.imgb"))
        utils.save_imgb(C_avg_blue, os.path.join(conf_dir, "C_avg_blue.imgb"))

        # --- 4) DISPARITY per-axis per channel
        Q = utils.Q_SCALE
        d = Q
        ds = Q
        dt = Q
        du = Q
        dv = Q

        print("Estimating disparity per-axis for RGB")

        # Red
        t0 = _stage_begin()
        Z_h_red = disparity.compute_horizontal_from_epis(
            epi_h_imgb,
            dL_du_h_red,
            dL_ds_h_red,
            d=d,
            ds=ds,
            du=du,
            win=5
        )
        _stage_end("4a) Disparity horizontal (red)", t0)

        t0 = _stage_begin()
        Z_v_red = disparity.compute_vertical_from_epis(
            epi_v_imgb,
            dL_dv_v_red,
            dL_dt_v_red,
            d=d,
            dt=dt,
            dv=dv,
            win=5
        )
        _stage_end("4b) Disparity vertical (red)", t0)

        # Green
        t0 = _stage_begin()
        Z_h_green = disparity.compute_horizontal_from_epis(
            epi_h_imgb,
            dL_du_h_green,
            dL_ds_h_green,
            d=d,
            ds=ds,
            du=du,
            win=5
        )
        _stage_end("4c) Disparity horizontal (green)", t0)

        t0 = _stage_begin()
        Z_v_green = disparity.compute_vertical_from_epis(
            epi_v_imgb,
            dL_dv_v_green,
            dL_dt_v_green,
            d=d,
            dt=dt,
            dv=dv,
            win=5
        )
        _stage_end("4d) Disparity vertical (green)", t0)

        # Blue
        t0 = _stage_begin()
        Z_h_blue = disparity.compute_horizontal_from_epis(
            epi_h_imgb,
            dL_du_h_blue,
            dL_ds_h_blue,
            d=d,
            ds=ds,
            du=du,
            win=5
        )
        _stage_end("4e) Disparity horizontal (blue)", t0)

        t0 = _stage_begin()
        Z_v_blue = disparity.compute_vertical_from_epis(
            epi_v_imgb,
            dL_dv_v_blue,
            dL_dt_v_blue,
            d=d,
            dt=dt,
            dv=dv,
            win=5
        )
        _stage_end("4f) Disparity vertical (blue)", t0)

        # --- 5) RGB disparity fusion
        print("Fusing RGB disparity")
        t0 = _stage_begin()
        Z_conf = disparity.fuse_disparity_precision(
            Z_h_red, Z_v_red, C_h_red, C_v_red,
            Z_h_green, Z_v_green, C_h_green, C_v_green,
            Z_h_blue, Z_v_blue, C_h_blue, C_v_blue,
            temperature=4,
            floor=1,
            cap=Q,
        )
        _stage_end("5) Fuse RGB disparity precision", t0)

        # --- Save disparity IMGB blobs
        os.makedirs(disp_dir, exist_ok=True)

        utils.save_imgb(Z_conf, os.path.join(disp_dir, "Z_conf.imgb"))

        utils.save_imgb(Z_h_red, os.path.join(disp_dir, "Z_h_red.imgb"))
        utils.save_imgb(Z_v_red, os.path.join(disp_dir, "Z_v_red.imgb"))

        utils.save_imgb(Z_h_green, os.path.join(disp_dir, "Z_h_green.imgb"))
        utils.save_imgb(Z_v_green, os.path.join(disp_dir, "Z_v_green.imgb"))

        utils.save_imgb(Z_h_blue, os.path.join(disp_dir, "Z_h_blue.imgb"))
        utils.save_imgb(Z_v_blue, os.path.join(disp_dir, "Z_v_blue.imgb"))

        compute_total_ns = time.perf_counter_ns() - compute_t0_ns
        print("Computations complete.")

        ordered = [
            "1) Low-pass filter",
            "2) Build EPIs",
            "3a) Confidence + angular/spatial diffs (red)",
            "3b) Confidence fuse avg (red)",
            "3c) Confidence + angular/spatial diffs (green)",
            "3d) Confidence fuse avg (green)",
            "3e) Confidence + angular/spatial diffs (blue)",
            "3f) Confidence fuse avg (blue)",
            "4a) Disparity horizontal (red)",
            "4b) Disparity vertical (red)",
            "4c) Disparity horizontal (green)",
            "4d) Disparity vertical (green)",
            "4e) Disparity horizontal (blue)",
            "4f) Disparity vertical (blue)",
            "5) Fuse RGB disparity precision",
        ]

        # ---------- Write compute timing summary to file ----------
        timing_path = os.path.join(
            f"Python_RGB/Bit_Manipulation/{scene}",
            "compute_timings.txt"
        )
        os.makedirs(f"Python_RGB/Bit_Manipulation/{scene}", exist_ok=True)

        with open(timing_path, "w") as f:
            f.write("=== Compute Timings Summary (nanoseconds, excludes saves) ===\n\n")
            for name in ordered:
                if name in stage_times_ns:
                    f.write(f"{name}: {stage_times_ns[name]} ns\n")
            f.write("\n")
            f.write(f"TOTAL compute time: {compute_total_ns} ns\n")
            f.write("===========================================================")

        # Convert all IMGB to PNG and write reliable mask image.
        bin_to_png.convert_scene_imgb_to_png(
            scene_dir=f"Python_RGB/Bit_Manipulation/{scene}",
            reliable_thresh=0.3,
            z_conf_rel_path="disparity/Z_conf.imgb",
            c_avg_rel_path="confidence/C_avg.imgb",
            reliable_base_name="reliable_avg_Z_conf_0_3",
        )

        print("Saves complete.")

    print("\nAll complete.")
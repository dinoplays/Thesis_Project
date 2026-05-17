# main.py
# Pipeline: low-pass convolve -> construct EPIs -> angular derivatives -> disparity
#
# This version computes:
#   Z_h
#   Z_v
#   Z_no_conf = average(Z_h, Z_v)
#
# Confidence maps are still computed and saved because confidence.py also returns
# dL_du_h and dL_dv_v, which are required by the disparity estimator.
# However, confidence is NOT used for final disparity fusion in this version.

import os
import time

import cross
import EPIs
import confidence
import disparity
import utils
import bin_to_png

EPS = 1 / 4096  # Q12.12 LSB


if __name__ == "__main__":
    kernel_size = 7

    for scene in ["dino", "head", "town"]:
        print(f"\n=== Processing scene: {scene} ===")

        # --- Paths
        scene_dir = f"Python_Red/No_Confidence/{scene}"
        cross_dir_raw = f"{scene_dir}/cross_raw_data"
        cross_dir     = f"{scene_dir}/cross_data_blurred"
        disp_dir      = f"{scene_dir}/disparity"
        conf_dir      = f"{scene_dir}/confidence"

        stage_times_ns = {}

        def _stage_begin() -> int:
            return time.perf_counter_ns()

        def _stage_end(stage_name: str, t0_ns: int) -> None:
            dt_ns = time.perf_counter_ns() - t0_ns
            stage_times_ns[stage_name] = stage_times_ns.get(stage_name, 0) + dt_ns

        compute_t0_ns = time.perf_counter_ns()

        # --- 1) Apply MAC low-pass filter
        print("Applying MAC low-pass filter")
        t0 = _stage_begin()
        cross.multiply_and_accumulate_low_pass_filter(
            cross_dir_raw,
            kernel_size=kernel_size,
            out_dir=cross_dir
        )
        _stage_end("1) Low-pass filter", t0)

        # --- 2) Construct EPIs
        print("Building horizontal/vertical EPIs")
        t0 = _stage_begin()
        epi_h_imgb, epi_v_imgb = EPIs.load_cross_crops_and_build_epis_imgb(cross_dir)
        _stage_end("2) Build EPIs", t0)

        # --- 3) Compute angular derivatives
        # Confidence maps are still produced here, but only dL_du_h and dL_dv_v
        # are needed for disparity estimation.
        print("Computing angular derivatives")
        t0 = _stage_begin()
        C_h, C_v, dL_du_h, dL_dv_v = confidence.compute_from_epis_with_diffs(
            epi_h_imgb,
            epi_v_imgb,
            channel=None
        )
        _stage_end("3a) Angular derivatives + confidence maps", t0)

        t0 = _stage_begin()
        C_avg = confidence.fuse_avg(C_h, C_v)
        _stage_end("3b) Confidence fuse avg", t0)

        # Save confidence maps for debugging/reference only
        os.makedirs(conf_dir, exist_ok=True)
        utils.save_imgb(C_h,   os.path.join(conf_dir, "C_h.imgb"))
        utils.save_imgb(C_v,   os.path.join(conf_dir, "C_v.imgb"))
        utils.save_imgb(C_avg, os.path.join(conf_dir, "C_avg.imgb"))

        # --- 4) Disparity per-axis
        d = 1.0
        ds = 1.0
        dt = 1.0
        du = 1.0
        dv = 1.0

        print("Estimating disparity per-axis")
        t0 = _stage_begin()
        Z_h = disparity.compute_horizontal_from_epis(
            epi_h_imgb,
            dL_du_h,
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
            d=d,
            dt=dt,
            dv=dv,
            win=5
        )
        _stage_end("4b) Disparity vertical", t0)

        # --- 5) NO-CONFIDENCE fusion
        print("Fusing disparity WITHOUT confidence")
        t0 = _stage_begin()
        Z_no_conf = disparity.fuse_disparity_average_no_confidence(
            Z_h,
            Z_v
        )
        _stage_end("5) Fuse disparity average no confidence", t0)

        # Save disparity IMGB blobs
        os.makedirs(disp_dir, exist_ok=True)
        utils.save_imgb(Z_h,       os.path.join(disp_dir, "Z_h.imgb"))
        utils.save_imgb(Z_v,       os.path.join(disp_dir, "Z_v.imgb"))
        utils.save_imgb(Z_no_conf, os.path.join(disp_dir, "Z_no_conf.imgb"))

        # Also save as Z_conf.imgb so existing bin_to_png and comparison scripts
        # that expect disparity/Z_conf.imgb continue to work.
        utils.save_imgb(Z_no_conf, os.path.join(disp_dir, "Z_conf.imgb"))

        compute_total_ns = time.perf_counter_ns() - compute_t0_ns
        print("Computations complete.")

        ordered = [
            "1) Low-pass filter",
            "2) Build EPIs",
            "3a) Angular derivatives + confidence maps",
            "3b) Confidence fuse avg",
            "4a) Disparity horizontal",
            "4b) Disparity vertical",
            "5) Fuse disparity average no confidence",
        ]

        # ---------- Write compute timing summary ----------
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

        # Convert all IMGB to PNG
        # This still uses C_avg only for the optional reliable-mask visualisation.
        # The actual disparity image Z_conf.imgb is the no-confidence average.
        bin_to_png.convert_scene_imgb_to_png(
            scene_dir=f"Python_Red/No_Confidence/{scene}",
            reliable_thresh=0.3,
            z_conf_rel_path="disparity/Z_conf.imgb",
            c_avg_rel_path="confidence/C_avg.imgb",
            reliable_base_name="reliable_avg_Z_conf_0_3",
        )

        print("Saves complete.")

    print("\nAll complete.")
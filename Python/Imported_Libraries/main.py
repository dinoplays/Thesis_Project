# main.py
# Pipeline: cv2 convolve -> construct EPIs -> CONFIDENCE -> DISPARITY (uses confidence)
# Computes angular diffs ONCE in confidence, reuses them in disparity.
# Crop is already 512 x 512 sized images

import os
import time

import cross       # cv2 low-pass + crop extraction
import EPIs        # build EPIs once
import confidence  # confidence + angular diffs
import disparity   # disparity using precomputed angular diffs
import utils       # shared utilities for saving, normalization, etc.

EPS = 1 / 4096  # Q12.12 in FPGA means decimal can be minimum 1/4096

if __name__ == "__main__":
    kernel_size = 7

    for scene in ["dino", "headshot", "town"]:
        print(f"\n=== Processing scene: {scene} ===")

        # --- Paths
        cross_dir_raw = f"Python/Imported_Libraries/{scene}/cross_raw_data"
        cross_dir     = f"Python/Imported_Libraries/{scene}/cross_data_blurred"
        disp_dir      = f"Python/Imported_Libraries/{scene}/disparity"
        conf_dir      = f"Python/Imported_Libraries/{scene}/confidence"

        # ---------- Timing (compute only; excludes saves) ----------
        stage_times_ns = {}

        def _stage_begin() -> int:
            return time.perf_counter_ns()

        def _stage_end(stage_name: str, t0_ns: int) -> None:
            dt_ns = time.perf_counter_ns() - t0_ns
            stage_times_ns[stage_name] = stage_times_ns.get(stage_name, 0) + dt_ns

        compute_t0_ns = time.perf_counter_ns()

        # --- 1) Apply low-pass filter
        print("Applying cv2 low-pass filter")
        t0 = _stage_begin()
        cross.cv2_low_pass_filter(cross_dir_raw, kernel_size=kernel_size, out_dir=cross_dir)
        _stage_end("1) Low-pass filter", t0)

        # --- 2) Load stacks and BUILD EPIs
        print("Loading stacks + building EPIs")
        t0 = _stage_begin()
        epi_h_rgb, epi_v_rgb = EPIs.load_cross_crops_and_build_epis(cross_dir)
        _stage_end("2) Load stacks + build EPIs", t0)

        # --- 3) CONFIDENCE (+ angular diffs computed ONCE)
        print("Computing confidence maps (C_h, C_v and AVG)")
        t0 = _stage_begin()
        C_h, C_v, dL_du_h, dL_dv_v = confidence.compute_from_epis_with_diffs(
            epi_h_rgb, epi_v_rgb, channel=None
        )
        _stage_end("3a) Confidence + angular diffs", t0)

        t0 = _stage_begin()
        C_avg = confidence.fuse_avg(C_h, C_v)
        _stage_end("3b) Confidence fuse avg", t0)

        # Save raw numeric confidence arrays (.npy)  [NOT TIMED]
        utils.save_npy(C_h, os.path.join(conf_dir, "C_h.npy"))
        utils.save_npy(C_v, os.path.join(conf_dir, "C_v.npy"))
        utils.save_npy(C_avg, os.path.join(conf_dir, "C_avg.npy"))

        # --- 4) DISPARITY per-axis (reuses angular diffs from confidence)
        d = 1.0
        ds = 1.0
        dt = 1.0
        du = 1.0
        dv = 1.0

        print("Estimating disparity per-axis (horizontal & vertical)")
        t0 = _stage_begin()
        Z_h = disparity.compute_horizontal_from_epis(epi_h_rgb, dL_du_h, d=d, ds=ds, du=du, win=5)
        _stage_end("4a) Disparity horizontal", t0)

        t0 = _stage_begin()
        Z_v = disparity.compute_vertical_from_epis(epi_v_rgb, dL_dv_v, d=d, dt=dt, dv=dv, win=5)
        _stage_end("4b) Disparity vertical", t0)

        # --- 5) Disparity fusion
        t0 = _stage_begin()
        Z_conf = disparity.fuse_disparity_precision(
            Z_h, Z_v, C_h, C_v,
            temperature=4.0,
            lo=1, hi=99,
            floor=1/4096, cap=1.0
        )
        _stage_end("5) Fuse disparity precision", t0)

        # Save raw .npy  [NOT TIMED]
        utils.save_npy(Z_h, os.path.join(disp_dir, "Z_h.npy"))
        utils.save_npy(Z_v, os.path.join(disp_dir, "Z_v.npy"))
        utils.save_npy(Z_conf, os.path.join(disp_dir, "Z_conf.npy"))

        compute_total_ns = time.perf_counter_ns() - compute_t0_ns

        print("Computations complete.")

        ordered = [
            "1) Low-pass filter",
            "2) Load stacks + build EPIs",
            "3a) Confidence + angular diffs",
            "3b) Confidence fuse avg",
            "4a) Disparity horizontal",
            "4b) Disparity vertical",
            "5) Fuse disparity precision",
        ]

        #  ---------- Write compute timing summary to file (ns only) ----------
        timing_path = os.path.join(f"Python/Bit_Manipulation/{scene}", "compute_timings.txt")
        os.makedirs(f"Python/Bit_Manipulation/{scene}", exist_ok=True)

        with open(timing_path, "w") as f:
            f.write("=== Compute Timings Summary (nanoseconds, excludes saves) ===\n\n")
            for name in ordered:
                if name in stage_times_ns:
                    f.write(f"{name}: {stage_times_ns[name]} ns\n")
            f.write("\n")
            f.write(f"TOTAL compute time: {compute_total_ns} ns\n")
            f.write("===========================================================")

        # ---------------- SAVES (not timed) ----------------
        confidence.save(C_avg, os.path.join(conf_dir, "confidence_avg_red.png"))

        disparity.save(Z_h, os.path.join(disp_dir, "disparity_h_red.png"))
        disparity.save(Z_v, os.path.join(disp_dir, "disparity_v_red.png"))
        disparity.save(Z_conf, os.path.join(disp_dir, "disparity_conf_weighted_red.png"))

        disparity.save_reliable(
            Z_conf, C_avg, 0.25,
            os.path.join(disp_dir, "reliable_avg_disparity_conf_0_25_red.png")
        )

        print("Saves complete.")
    print("\nAll complete.")
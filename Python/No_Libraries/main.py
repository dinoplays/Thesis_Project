# main.py
# Pipeline: bit-shift convolve -> construct EPIs -> CONFIDENCE -> DISPARITY (uses confidence)
# All IMGB numeric outputs after cross are stored as:
#   dtype_code=4 (u24), biased signed Q12.12 (see utils.py)
# Crop is already 512 x 512 sized images
#
# Only necessary computations done so time can be tracked.

import os
import time

import cross       # bit-shift low-pass + crop extraction -> outputs Q12.12 u24 IMGB
import EPIs        # load stacks -> builds EPI IMGB blobs (still Q12.12 u24)
import confidence  # C_h, C_v and AVG, plus angular diffs (all Q12.12 u24)
import disparity   # stdlib-only, works on IMGB blobs
import utils       # IMGB helpers + saves
import bin_to_png  # converts IMGB folders to PNG (linear + robust + reliable mask)

EPS = 1 / 4096  # Q12.12 LSB


if __name__ == "__main__":
    kernel_size = 7

    for scene in ["dino", "headshot", "town"]:
        print(f"\n=== Processing scene: {scene} ===")

        # --- Paths
        cross_dir_raw = f"Python/No_Libraries/{scene}/cross_raw_data"
        cross_dir     = f"Python/No_Libraries/{scene}/cross_data_blurred"
        disp_dir      = f"Python/No_Libraries/{scene}/disparity"
        conf_dir      = f"Python/No_Libraries/{scene}/confidence"

        stage_times_ns = {}

        def _stage_begin() -> int:
            return time.perf_counter_ns()

        def _stage_end(stage_name: str, t0_ns: int) -> None:
            dt_ns = time.perf_counter_ns() - t0_ns
            stage_times_ns[stage_name] = stage_times_ns.get(stage_name, 0) + dt_ns

        compute_t0_ns = time.perf_counter_ns()

        # --- 1) Apply MAC low-pass filter (outputs Q12.12 u24 IMGB)
        print("Applying MAC low-pass filter")
        t0 = _stage_begin()
        cross.multiply_and_accumulate_low_pass_filter(cross_dir_raw, kernel_size=kernel_size, out_dir=cross_dir)
        _stage_end("1) Low-pass filter", t0)

        # --- 2) Construct EPIs (IMGB blobs in memory, Q12.12 u24)
        print("Building horizontal/vertical EPIs (IMGB blobs)")
        t0 = _stage_begin()
        epi_h_imgb, epi_v_imgb = EPIs.load_cross_crops_and_build_epis_imgb(cross_dir)
        _stage_end("2) Build EPIs", t0)

        # --- 3) CONFIDENCE (+ angular diffs computed ONCE) (all Q12.12 u24)
        print("Computing confidence maps (C_h, C_v and AVG)")
        t0 = _stage_begin()
        C_h, C_v, dL_du_h, dL_dv_v = confidence.compute_from_epis_with_diffs(
            epi_h_imgb, epi_v_imgb, channel=None
        )
        _stage_end("3a) Confidence + angular diffs", t0)

        t0 = _stage_begin()
        C_avg = confidence.fuse_avg(C_h, C_v)
        _stage_end("3b) Confidence fuse avg", t0)

        # Save confidence IMGB blobs (.imgb)
        os.makedirs(conf_dir, exist_ok=True)
        utils.save_imgb(C_h,   os.path.join(conf_dir, "C_h.imgb"))
        utils.save_imgb(C_v,   os.path.join(conf_dir, "C_v.imgb"))
        utils.save_imgb(C_avg, os.path.join(conf_dir, "C_avg.imgb"))

        # --- 4) DISPARITY per-axis (reuses angular diffs)
        d = 1.0
        ds = 1.0
        dt = 1.0
        du = 1.0
        dv = 1.0

        print("Estimating disparity per-axis (horizontal & vertical)")
        t0 = _stage_begin()
        Z_h = disparity.compute_horizontal_from_epis(epi_h_imgb, dL_du_h, d=d, ds=ds, du=du, win=5)
        _stage_end("4a) Disparity horizontal", t0)

        t0 = _stage_begin()
        Z_v = disparity.compute_vertical_from_epis(epi_v_imgb, dL_dv_v, d=d, dt=dt, dv=dv, win=5)
        _stage_end("4b) Disparity vertical", t0)

        # --- 5) Disparity fusion
        t0 = _stage_begin()
        Z_conf = disparity.fuse_disparity_precision(
            Z_h, Z_v, C_h, C_v,
            temperature=4.0,
            floor=1/4096,
            cap=1.0
        )
        _stage_end("5) Fuse disparity precision", t0)

        # Save disparity IMGB blobs (.imgb)
        os.makedirs(disp_dir, exist_ok=True)
        utils.save_imgb(Z_h,    os.path.join(disp_dir, "Z_h.imgb"))
        utils.save_imgb(Z_v,    os.path.join(disp_dir, "Z_v.imgb"))
        utils.save_imgb(Z_conf, os.path.join(disp_dir, "Z_conf.imgb"))

        compute_total_ns = time.perf_counter_ns() - compute_t0_ns
        print("Computations complete.")

        ordered = [
            "1) Low-pass filter",
            "2) Build EPIs",
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

        # Convert all IMGB to PNG (linear + robust) and also reliable mask image
        # (writes into *_png and *_robust_png folders)
        bin_to_png.convert_scene_imgb_to_png(
            f"Python/Bit_Manipulation/{scene}",
            reliable_thresh=0.25,
            z_conf_rel_path="disparity/Z_conf.imgb",
            c_avg_rel_path="confidence/C_avg.imgb",
            reliable_base_name="reliable_avg_Z_conf_0_25",
        )

        print("Saves complete.")
    print("\nAll complete.")
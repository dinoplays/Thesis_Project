# main.py
# RGB No-Libraries pipeline:
#   raw cross data conversion
#   -> construct EPIs
#   -> confidence + derivatives for R/G/B
#   -> per-channel horizontal/vertical disparity
#   -> confidence-weighted RGB disparity fusion
#   -> confidence-guided region filling
#   -> final fixed 7x7 2D low-pass on filled disparity
#
# All IMGB numeric outputs after cross conversion are
#  stored as:
#   dtype_code=4 (u24), biased signed Q12.12 (see utils.py)
#
# No pre-EPI low-pass is applied.
# The low-pass filter is applied at the end to Z_conf_filled.
#
# Non-bit-manipulative version:
#   Uses Python_RGB/No_Libraries paths.
#   Uses floating-point scale values for d, ds, dt, du, dv.
#   Uses floating-point fusion parameters.
#
# RGB fusion:
#   Z_conf_raw = (
#       Z_h_red*C_h_red + Z_v_red*C_v_red
#     + Z_h_green*C_h_green + Z_v_green*C_v_green
#     + Z_h_blue*C_h_blue + Z_v_blue*C_v_blue
#   ) / (
#       C_h_red + C_v_red
#     + C_h_green + C_v_green
#     + C_h_blue + C_v_blue
#   )

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


REGION_FILL_CONFIDENCE_THRESHOLD = 1


if __name__ == "__main__":
    for scene in ["dino", "head", "town"]:
        print(f"\n=== Processing RGB scene: {scene} ===")

        scene_dir = f"Python_RGB/No_Libraries/{scene}"

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
        print("Converting raw RGB cross data to Q12.12 u24 IMGB")
        t0 = _stage_begin()
        cross.convert_cross_u8_to_q12_12(cross_dir_raw, cross_dir)
        _stage_end("1) Cross data Q12.12 conversion", t0)

        # --- 2) Construct EPIs
        print("Building horizontal/vertical EPIs (IMGB blobs)")
        t0 = _stage_begin()
        epi_h_imgb, epi_v_imgb = EPIs.load_cross_crops_and_build_epis_imgb(cross_dir)
        _stage_end("2) Build EPIs", t0)

        # --- 3) CONFIDENCE + DERIVATIVES per RGB channel
        print("Computing confidence maps and derivatives for RGB")

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

        t0 = _stage_begin()
        C_avg_rgb = confidence.fuse_avg_three(
            C_avg_red,
            C_avg_green,
            C_avg_blue
        )
        _stage_end("3g) Confidence fuse avg (RGB)", t0)

        os.makedirs(conf_dir, exist_ok=True)

        # Compatibility filenames use RGB-fused confidence.
        utils.save_imgb(C_avg_rgb, os.path.join(conf_dir, "C_avg.imgb"))

        # Save channel-specific confidence maps.
        utils.save_imgb(C_h_red, os.path.join(conf_dir, "C_h_red.imgb"))
        utils.save_imgb(C_v_red, os.path.join(conf_dir, "C_v_red.imgb"))
        utils.save_imgb(C_avg_red, os.path.join(conf_dir, "C_avg_red.imgb"))

        utils.save_imgb(C_h_green, os.path.join(conf_dir, "C_h_green.imgb"))
        utils.save_imgb(C_v_green, os.path.join(conf_dir, "C_v_green.imgb"))
        utils.save_imgb(C_avg_green, os.path.join(conf_dir, "C_avg_green.imgb"))

        utils.save_imgb(C_h_blue, os.path.join(conf_dir, "C_h_blue.imgb"))
        utils.save_imgb(C_v_blue, os.path.join(conf_dir, "C_v_blue.imgb"))
        utils.save_imgb(C_avg_blue, os.path.join(conf_dir, "C_avg_blue.imgb"))

        # Save RGB aggregate under explicit name as well.
        utils.save_imgb(C_avg_rgb, os.path.join(conf_dir, "C_avg_rgb.imgb"))

        # --- 4) DISPARITY per-axis per channel
        d = 1.0
        ds = 1.0
        dt = 1.0
        du = 1.0
        dv = 1.0

        print("Estimating disparity per-axis for RGB")

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

        # --- 5) Confidence-weighted RGB disparity fusion
        print("Fusing RGB disparity using confidence")
        t0 = _stage_begin()
        Z_conf_raw = disparity.fuse_rgb_disparity_precision(
            Z_h_red,
            Z_v_red,
            C_h_red,
            C_v_red,
            Z_h_green,
            Z_v_green,
            C_h_green,
            C_v_green,
            Z_h_blue,
            Z_v_blue,
            C_h_blue,
            C_v_blue,
            temperature=4.0,
            floor=1 / 4096,
            cap=1.0,
        )
        _stage_end("5) Fuse RGB disparity precision", t0)

        # --- 6) Confidence-guided region filling
        print("Applying confidence-guided region filling")
        t0 = _stage_begin()
        Z_conf_filled = region_filling.fill_regions_q12_12_single_channel(
            Z_conf_raw,
            C_avg_rgb,
            confidence_threshold=REGION_FILL_CONFIDENCE_THRESHOLD
        )
        _stage_end("6) Confidence-guided region filling", t0)

        # --- 7) Final fixed 7x7 post-disparity 2D low-pass
        print("Applying final fixed 7x7 2D low-pass to filled disparity")
        t0 = _stage_begin()
        Z_conf = convolve.low_pass_q12_12_single_channel(Z_conf_filled)
        _stage_end("7) Final fixed 7x7 disparity low-pass", t0)

        os.makedirs(disp_dir, exist_ok=True)

        # Save channel-specific disparity maps.
        utils.save_imgb(Z_h_red, os.path.join(disp_dir, "Z_h_red.imgb"))
        utils.save_imgb(Z_v_red, os.path.join(disp_dir, "Z_v_red.imgb"))

        utils.save_imgb(Z_h_green, os.path.join(disp_dir, "Z_h_green.imgb"))
        utils.save_imgb(Z_v_green, os.path.join(disp_dir, "Z_v_green.imgb"))

        utils.save_imgb(Z_h_blue, os.path.join(disp_dir, "Z_h_blue.imgb"))
        utils.save_imgb(Z_v_blue, os.path.join(disp_dir, "Z_v_blue.imgb"))

        # Save fused pipeline stages.
        utils.save_imgb(Z_conf_raw, os.path.join(disp_dir, "Z_conf_raw.imgb"))
        utils.save_imgb(Z_conf_filled, os.path.join(disp_dir, "Z_conf_filled.imgb"))
        utils.save_imgb(Z_conf, os.path.join(disp_dir, "Z_conf.imgb"))

        compute_total_ns = time.perf_counter_ns() - compute_t0_ns
        print("Computations complete.")

        ordered = [
            "1) Cross data Q12.12 conversion",
            "2) Build EPIs",
            "3a) Confidence + angular/spatial diffs (red)",
            "3b) Confidence fuse avg (red)",
            "3c) Confidence + angular/spatial diffs (green)",
            "3d) Confidence fuse avg (green)",
            "3e) Confidence + angular/spatial diffs (blue)",
            "3f) Confidence fuse avg (blue)",
            "3g) Confidence fuse avg (RGB)",
            "4a) Disparity horizontal (red)",
            "4b) Disparity vertical (red)",
            "4c) Disparity horizontal (green)",
            "4d) Disparity vertical (green)",
            "4e) Disparity horizontal (blue)",
            "4f) Disparity vertical (blue)",
            "5) Fuse RGB disparity precision",
            "6) Confidence-guided region filling",
            "7) Final fixed 7x7 disparity low-pass",
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
            z_conf_rel_path="disparity/Z_conf.imgb",
            c_avg_rel_path="confidence/C_avg.imgb",
            reliable_base_name="reliable_avg_Z_conf_1",
        )

        print("Saves complete.")

    print("\nAll complete.")

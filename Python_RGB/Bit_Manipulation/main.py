# main.py
# RGB Bit-Manipulative pipeline rebuilt from the current Red implementation:
#   raw cross data conversion
#   -> construct EPIs
#   -> confidence + derivatives for R/G/B
#   -> per-channel horizontal/vertical disparity
#   -> confidence-weighted RGB fusion over six estimates
#   -> final fixed 7x7 2D low-pass on non-filled disparity/confidence
#   -> confidence-guided region filling kept as a future-work output
#   -> final fixed 7x7 2D low-pass on filled disparity
#
# Z_conf.imgb is intentionally the non-filled + blurred output so that it is
# comparable to the current FPGA pipeline, which does not perform region filling.

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

CHANNEL_NAMES = ["red", "green", "blue"]


def _stage_begin() -> int:
    return time.perf_counter_ns()


def _stage_end(stage_times_ns: dict[str, int], stage_name: str, t0_ns: int) -> None:
    dt_ns = time.perf_counter_ns() - t0_ns
    stage_times_ns[stage_name] = stage_times_ns.get(stage_name, 0) + dt_ns


if __name__ == "__main__":
    for scene in ["dino", "head", "town"]:
        print(f"\n=== Processing RGB bit-manipulative scene: {scene} ===")

        scene_dir = f"Python_RGB/Bit_Manipulation/{scene}"

        cross_dir_raw = os.path.join(scene_dir, "cross_raw_data")
        cross_dir = os.path.join(scene_dir, "cross_data_q12_12")
        disp_dir = os.path.join(scene_dir, "disparity")
        conf_dir = os.path.join(scene_dir, "confidence")

        stage_times_ns = {}
        compute_t0_ns = time.perf_counter_ns()

        print("Converting raw RGB cross data to Q12.12 u24 IMGB")
        t0 = _stage_begin()
        cross.convert_cross_u8_to_q12_12(cross_dir_raw, cross_dir)
        _stage_end(stage_times_ns, "1) Cross data Q12.12 conversion", t0)

        print("Building horizontal/vertical EPIs (IMGB blobs)")
        t0 = _stage_begin()
        epi_h_imgb, epi_v_imgb = EPIs.load_cross_crops_and_build_epis_imgb(cross_dir)
        _stage_end(stage_times_ns, "2) Build EPIs", t0)

        # ------------------------------------------------------------
        # Confidence and derivatives for each colour channel
        # ------------------------------------------------------------
        channel_data = []

        for channel_idx, channel_name in enumerate(CHANNEL_NAMES):
            print(f"Computing confidence maps and derivatives for {channel_name}")
            t0 = _stage_begin()
            C_h, C_v, dL_du_h, dL_dv_v, dL_ds_h, dL_dt_v = confidence.compute_from_epis_with_diffs(
                epi_h_imgb,
                epi_v_imgb,
                channel=channel_idx,
            )
            _stage_end(
                stage_times_ns,
                f"3) Confidence + angular/spatial diffs ({channel_name})",
                t0,
            )

            t0 = _stage_begin()
            C_avg_channel = confidence.fuse_avg(C_h, C_v)
            _stage_end(stage_times_ns, f"3) Confidence fuse avg ({channel_name})", t0)

            channel_data.append({
                "name": channel_name,
                "C_h": C_h,
                "C_v": C_v,
                "C_avg": C_avg_channel,
                "dL_du_h": dL_du_h,
                "dL_dv_v": dL_dv_v,
                "dL_ds_h": dL_ds_h,
                "dL_dt_v": dL_dt_v,
            })

        t0 = _stage_begin()
        C_avg_raw = confidence.fuse_avg_three(
            channel_data[0]["C_avg"],
            channel_data[1]["C_avg"],
            channel_data[2]["C_avg"],
        )
        _stage_end(stage_times_ns, "3) Confidence fuse avg (RGB)", t0)

        os.makedirs(conf_dir, exist_ok=True)

        for data in channel_data:
            name = data["name"]
            utils.save_imgb(data["C_h"], os.path.join(conf_dir, f"C_h_{name}.imgb"))
            utils.save_imgb(data["C_v"], os.path.join(conf_dir, f"C_v_{name}.imgb"))
            utils.save_imgb(data["C_avg"], os.path.join(conf_dir, f"C_avg_{name}.imgb"))

        utils.save_imgb(C_avg_raw, os.path.join(conf_dir, "C_avg_raw.imgb"))
        utils.save_imgb(C_avg_raw, os.path.join(conf_dir, "C_avg_rgb_raw.imgb"))

        # ------------------------------------------------------------
        # Per-channel disparity
        # ------------------------------------------------------------
        Q = utils.Q_SCALE
        d = Q
        ds = Q
        dt = Q
        du = Q
        dv = Q

        for data in channel_data:
            name = data["name"]

            print(f"Estimating horizontal disparity for {name}")
            t0 = _stage_begin()
            data["Z_h"] = disparity.compute_horizontal_from_epis(
                epi_h_imgb,
                data["dL_du_h"],
                data["dL_ds_h"],
                d=d,
                ds=ds,
                du=du,
                win=5,
            )
            _stage_end(stage_times_ns, f"4) Disparity horizontal ({name})", t0)

            print(f"Estimating vertical disparity for {name}")
            t0 = _stage_begin()
            data["Z_v"] = disparity.compute_vertical_from_epis(
                epi_v_imgb,
                data["dL_dv_v"],
                data["dL_dt_v"],
                d=d,
                dt=dt,
                dv=dv,
                win=5,
            )
            _stage_end(stage_times_ns, f"4) Disparity vertical ({name})", t0)

        print("Fusing RGB disparity using confidence weights")
        t0 = _stage_begin()
        Z_conf_raw = disparity.fuse_rgb_disparity_precision(
            channel_data[0]["Z_h"], channel_data[0]["Z_v"], channel_data[0]["C_h"], channel_data[0]["C_v"],
            channel_data[1]["Z_h"], channel_data[1]["Z_v"], channel_data[1]["C_h"], channel_data[1]["C_v"],
            channel_data[2]["Z_h"], channel_data[2]["Z_v"], channel_data[2]["C_h"], channel_data[2]["C_v"],
            temperature=1,
            floor=0,
            cap=utils.Q_SCALE,
            eps=0,
        )
        _stage_end(stage_times_ns, "5) RGB confidence-weighted disparity fusion", t0)

        # ------------------------------------------------------------
        # Final low-pass on non-filled output: direct FPGA comparison target
        # ------------------------------------------------------------
        print("Applying final fixed 7x7 2D low-pass to non-filled disparity/confidence")
        t0 = _stage_begin()
        Z_conf = convolve.low_pass_q12_12_single_channel(Z_conf_raw)
        C_avg = convolve.low_pass_q12_12_single_channel(C_avg_raw)
        _stage_end(stage_times_ns, "6) Final fixed 7x7 non-filled disparity/confidence low-pass", t0)

        print("Applying confidence-guided region filling")
        t0 = _stage_begin()
        Z_conf_filled = region_filling.fill_regions_q12_12_single_channel(
            Z_conf_raw,
            C_avg_raw,
            confidence_threshold=REGION_FILL_CONFIDENCE_THRESHOLD,
        )
        _stage_end(stage_times_ns, "7) Confidence-guided region filling", t0)

        print("Applying final fixed 7x7 2D low-pass to filled disparity")
        t0 = _stage_begin()
        Z_conf_filled_blurred = convolve.low_pass_q12_12_single_channel(Z_conf_filled)
        _stage_end(stage_times_ns, "8) Final fixed 7x7 filled disparity low-pass", t0)

        utils.save_imgb(C_avg, os.path.join(conf_dir, "C_avg.imgb"))
        utils.save_imgb(C_avg, os.path.join(conf_dir, "C_avg_nonfilled_blurred.imgb"))
        utils.save_imgb(C_avg, os.path.join(conf_dir, "C_avg_rgb.imgb"))

        os.makedirs(disp_dir, exist_ok=True)

        for data in channel_data:
            name = data["name"]
            utils.save_imgb(data["Z_h"], os.path.join(disp_dir, f"Z_h_{name}.imgb"))
            utils.save_imgb(data["Z_v"], os.path.join(disp_dir, f"Z_v_{name}.imgb"))

        utils.save_imgb(Z_conf_raw, os.path.join(disp_dir, "Z_conf_raw.imgb"))
        utils.save_imgb(Z_conf, os.path.join(disp_dir, "Z_conf.imgb"))
        utils.save_imgb(Z_conf, os.path.join(disp_dir, "Z_conf_nonfilled_blurred.imgb"))
        utils.save_imgb(Z_conf_filled, os.path.join(disp_dir, "Z_conf_filled.imgb"))
        utils.save_imgb(Z_conf_filled_blurred, os.path.join(disp_dir, "Z_conf_filled_blurred.imgb"))

        compute_total_ns = time.perf_counter_ns() - compute_t0_ns
        print("Computations complete.")

        timing_path = os.path.join(scene_dir, "compute_timings.txt")
        os.makedirs(scene_dir, exist_ok=True)
        with open(timing_path, "w") as f:
            f.write("=== Compute Timings Summary (nanoseconds, excludes saves) ===\n\n")
            for name, value in stage_times_ns.items():
                f.write(f"{name}: {value} ns\n")
            f.write("\n")
            f.write(f"TOTAL compute time: {compute_total_ns} ns\n")
            f.write("===========================================================")

        bin_to_png.convert_scene_imgb_to_png(
            scene_dir=scene_dir,
            reliable_thresh=REGION_FILL_CONFIDENCE_THRESHOLD,
            z_conf_rel_path="disparity/Z_conf.imgb",
            c_avg_rel_path="confidence/C_avg.imgb",
            reliable_base_name="reliable_avg_Z_conf_1p25",
        )

        print("Saves complete.")

    print("\nAll complete.")

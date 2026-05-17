# bin_to_png.py
# Convert custom .imgb files (IMGB header + raw pixels) back to .png images.
#
# Produces TWO outputs for every folder:
#   1) Linear/original bounds  ->  ..._png
#   2) Robust-normalised       ->  ..._robust_png
#
# Also produces an additional "reliable disparity" visualization:
#   gray disparity with pink mask where confidence < threshold.

import os
import imageio.v3 as iio
import numpy as np
import matplotlib.pyplot as plt

from utils import (
    imgb_parse,
    BIAS_INT,
    Q_FRAC,
)

P_LO = 2.0
P_HI = 98.0


# ----------------------------------------------------------
# Fast decode helpers
# ----------------------------------------------------------

def _decode_u24_q12_12(payload: bytes, n_samples: int) -> np.ndarray:
    """
    payload: length n_samples*3
    returns float32 array length n_samples: (u24 - BIAS_INT) / (2^Q_FRAC)
    """
    b = np.frombuffer(payload, dtype=np.uint8).reshape((-1, 3))
    u = b[:, 0].astype(np.uint32) | (b[:, 1].astype(np.uint32) << 8) | (b[:, 2].astype(np.uint32) << 16)

    # (u - BIAS_INT) / 2^Q_FRAC
    # Use power-of-two scaling via numpy.ldexp: ldexp(x, -Q_FRAC) == x / (2^Q_FRAC)
    x = (u.astype(np.int32) - np.int32(BIAS_INT)).astype(np.float32)
    out = np.ldexp(x, -int(Q_FRAC)).astype(np.float32)

    return out


# ----------------------------------------------------------
# Decode IMGB -> float32 image
# ----------------------------------------------------------

def read_imgb(path_in: str) -> tuple[np.ndarray, int]:
    with open(path_in, "rb") as f:
        blob = f.read()

    W, H, C, dtype_code, payload = imgb_parse(blob)

    expected = W * H * C * (1 if dtype_code == 1 else 3)
    if len(payload) != expected:
        raise ValueError(
            f"Payload length mismatch in {path_in}: "
            f"len(payload)={len(payload)}, expected={expected}, "
            f"W={W}, H={H}, C={C}, dtype={dtype_code}"
        )

    # Raw u8
    if dtype_code == 1:
        arr = np.frombuffer(payload, dtype=np.uint8)
        if C == 1:
            arr = arr.reshape((H, W))
        else:
            arr = arr.reshape((H, W, C))
        return arr.astype(np.float32), dtype_code

    # Q12.12 biased u24
    if dtype_code == 4:
        n_samples = W * H * C
        out = _decode_u24_q12_12(payload, n_samples)
        if C == 1:
            out = out.reshape((H, W))
        else:
            out = out.reshape((H, W, C))
        return out, dtype_code

    raise ValueError(f"Unsupported dtype_code={dtype_code} in {path_in}")


# ----------------------------------------------------------
# Linear mapping (preserve original bounds)
# ----------------------------------------------------------

def linear_to_u8(img: np.ndarray) -> np.ndarray:
    return np.clip(img, 0.0, 255.0).astype(np.uint8)


# ----------------------------------------------------------
# Robust normalization
# ----------------------------------------------------------

def robust_to_u8(img: np.ndarray) -> np.ndarray:
    x = img.astype(np.float32, copy=False)

    lo = np.percentile(x, P_LO)
    hi = np.percentile(x, P_HI)

    if not np.isfinite(lo):
        lo = 0.0
    if not np.isfinite(hi):
        hi = lo + 1.0
    if hi <= lo:
        hi = lo + 1.0

    y = (x - lo) / (hi - lo)
    y = np.clip(y, 0.0, 1.0)
    y = (y * 255.0 + 0.5).astype(np.uint8)
    return y


# ----------------------------------------------------------
# Pink-mask plotting (moved from disparity.py)
# ----------------------------------------------------------

def _robust_limits(Z: np.ndarray, p_lo=2.0, p_hi=98.0) -> tuple[float, float]:
    Z = np.asarray(Z, dtype=np.float32)
    finite = np.isfinite(Z)
    if not finite.any():
        return 0.0, 1.0
    v = Z[finite]
    lo = float(np.percentile(v, p_lo))
    hi = float(np.percentile(v, p_hi))
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi

def save_gray_with_pink_mask(Z: np.ndarray, mask_ok: np.ndarray, out_png: str) -> None:
    """
    Z: float32 disparity (H,W)
    mask_ok: bool (H,W) True where reliable
    Pixels NOT reliable are shown pink.
    """
    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)

    Zm = np.where(mask_ok, Z, np.nan).astype(np.float32)
    vmin, vmax = _robust_limits(Zm, 2.0, 98.0)

    Zm = np.ma.masked_invalid(Zm)
    cmap = plt.cm.gray.copy()
    cmap.set_bad(color=(1.0, 0.4, 0.7, 1.0))

    plt.figure(figsize=(6, 6))
    plt.imshow(Zm, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    plt.axis("off")
    plt.tight_layout(pad=0)
    plt.savefig(out_png, dpi=150, bbox_inches="tight", pad_inches=0)
    plt.close()


# ----------------------------------------------------------
# Folder conversion
# ----------------------------------------------------------

def convert_folder_imgb_to_png(in_dir: str) -> tuple[str, str]:
    out_linear = in_dir.rstrip("/\\") + "_png"
    out_robust = in_dir.rstrip("/\\") + "_robust_png"

    os.makedirs(out_linear, exist_ok=True)
    os.makedirs(out_robust, exist_ok=True)

    names = [n for n in os.listdir(in_dir) if n.lower().endswith(".imgb")]
    names.sort()

    for name in names:
        src = os.path.join(in_dir, name)
        base = os.path.splitext(name)[0]

        img, _dtype = read_imgb(src)

        # -------- Linear
        if img.ndim == 3:
            linear = linear_to_u8(img)
        else:
            linear = linear_to_u8(img)
        iio.imwrite(os.path.join(out_linear, base + ".png"), linear)

        # -------- Robust
        if img.ndim == 3:
            # per-channel robust
            chans = []
            for c in range(img.shape[2]):
                chans.append(robust_to_u8(img[..., c]))
            robust = np.stack(chans, axis=2)
        else:
            robust = robust_to_u8(img)
        iio.imwrite(os.path.join(out_robust, base + ".png"), robust)

    return out_linear, out_robust


# ----------------------------------------------------------
# Reliable disparity output (into disparity_png and disparity_robust_png)
# ----------------------------------------------------------

def write_reliable_outputs(
    disp_dir: str,
    Z_path: str,
    C_path: str,
    thresh: float,
    base_name: str,
) -> None:
    """
    Writes:
      disp_dir_png/<base_name>.png
      disp_dir_robust_png/<base_name>.png

    Uses pink-mask plot (robust grayscale limits), same output for both folders,
    because the plot itself is already robust-scaled.
    """
    print("=== write_reliable_outputs debug ===")
    print(f"disp_dir:  {disp_dir}")
    print(f"Z_path:    {Z_path}")
    print(f"C_path:    {C_path}")
    print(f"threshold: {thresh}")
    print(f"base_name: {base_name}")

    if not os.path.isdir(disp_dir):
        raise FileNotFoundError(f"Disparity directory does not exist: {disp_dir}")

    if not os.path.exists(Z_path):
        raise FileNotFoundError(f"Disparity IMGB file does not exist: {Z_path}")

    if not os.path.exists(C_path):
        raise FileNotFoundError(f"Confidence IMGB file does not exist: {C_path}")

    Z, _ = read_imgb(Z_path)
    C, _ = read_imgb(C_path)

    print(f"Loaded Z shape: {Z.shape}, min/max: {np.nanmin(Z)} / {np.nanmax(Z)}")
    print(f"Loaded C shape: {C.shape}, min/max: {np.nanmin(C)} / {np.nanmax(C)}")

    if Z.ndim != 2 or C.ndim != 2:
        raise ValueError(
            f"Reliable output expects Z and C to be single-channel images (H,W). "
            f"Got Z.ndim={Z.ndim}, C.ndim={C.ndim}"
        )

    if Z.shape != C.shape:
        raise ValueError(
            f"Z and C shape mismatch: Z.shape={Z.shape}, C.shape={C.shape}"
        )

    mask_ok = np.isfinite(Z) & np.isfinite(C) & (C >= float(thresh))

    reliable_count = int(np.count_nonzero(mask_ok))
    total_count = int(mask_ok.size)

    print(f"Reliable pixels: {reliable_count} / {total_count}")

    out_linear_dir = disp_dir.rstrip("/\\") + "_png"
    out_robust_dir = disp_dir.rstrip("/\\") + "_robust_png"

    os.makedirs(out_linear_dir, exist_ok=True)
    os.makedirs(out_robust_dir, exist_ok=True)

    out_linear = os.path.join(out_linear_dir, base_name + ".png")
    out_robust = os.path.join(out_robust_dir, base_name + ".png")

    save_gray_with_pink_mask(Z, mask_ok, out_linear)
    print(f"Saved to: {out_linear}")

    save_gray_with_pink_mask(Z, mask_ok, out_robust)
    print(f"Saved to: {out_robust}")

    if not os.path.exists(out_linear):
        raise RuntimeError(f"Expected output was not created: {out_linear}")

    if not os.path.exists(out_robust):
        raise RuntimeError(f"Expected output was not created: {out_robust}")

    print("Reliable disparity outputs saved successfully.")


# ----------------------------------------------------------
# One-shot scene conversion (called from main)
# ----------------------------------------------------------

def convert_scene_imgb_to_png(
    *,
    scene_dir: str,
    reliable_thresh: float = 0.3,
    z_conf_rel_path: str = "disparity/Z_conf.imgb",
    c_avg_rel_path: str = "confidence/C_avg.imgb",
    reliable_base_name: str = "reliable_avg_Z_conf_0_3",
) -> None:
    """
    Converts:
      scene_dir/cross_data_blurred  -> *_png and *_robust_png
      scene_dir/confidence         -> *_png and *_robust_png
      scene_dir/disparity          -> *_png and *_robust_png

    And writes reliable visualization into disparity_png and disparity_robust_png.
    """
    print("=== convert_scene_imgb_to_png debug ===")
    print(f"scene_dir: {scene_dir}")
    print(f"reliable_thresh: {reliable_thresh}")
    print(f"z_conf_rel_path: {z_conf_rel_path}")
    print(f"c_avg_rel_path: {c_avg_rel_path}")
    print(f"reliable_base_name: {reliable_base_name}")

    if not os.path.isdir(scene_dir):
        raise FileNotFoundError(
            f"scene_dir does not exist or is not a directory: {scene_dir}"
        )

    cross_dir = os.path.join(scene_dir, "cross_data_blurred")
    conf_dir = os.path.join(scene_dir, "confidence")
    disp_dir = os.path.join(scene_dir, "disparity")

    print(f"cross_dir: {cross_dir} | exists={os.path.isdir(cross_dir)}")
    print(f"conf_dir:  {conf_dir} | exists={os.path.isdir(conf_dir)}")
    print(f"disp_dir:  {disp_dir} | exists={os.path.isdir(disp_dir)}")

    if os.path.isdir(cross_dir):
        out_linear, out_robust = convert_folder_imgb_to_png(cross_dir)
        print(f"Converted cross data to: {out_linear}")
        print(f"Converted cross data to: {out_robust}")
    else:
        print(f"Skipping cross conversion; missing folder: {cross_dir}")

    if os.path.isdir(conf_dir):
        out_linear, out_robust = convert_folder_imgb_to_png(conf_dir)
        print(f"Converted confidence to: {out_linear}")
        print(f"Converted confidence to: {out_robust}")
    else:
        print(f"Skipping confidence conversion; missing folder: {conf_dir}")

    if os.path.isdir(disp_dir):
        out_linear, out_robust = convert_folder_imgb_to_png(disp_dir)
        print(f"Converted disparity to: {out_linear}")
        print(f"Converted disparity to: {out_robust}")
    else:
        print(f"Skipping disparity conversion; missing folder: {disp_dir}")

    Z_path = os.path.join(scene_dir, z_conf_rel_path)
    C_path = os.path.join(scene_dir, c_avg_rel_path)

    print(f"Resolved Z_path: {Z_path}")
    print(f"Resolved C_path: {C_path}")
    print(f"Z_path exists: {os.path.exists(Z_path)}")
    print(f"C_path exists: {os.path.exists(C_path)}")
    print(f"disp_dir exists: {os.path.isdir(disp_dir)}")

    missing = []

    if not os.path.exists(Z_path):
        missing.append(f"Missing disparity file: {Z_path}")

    if not os.path.exists(C_path):
        missing.append(f"Missing confidence file: {C_path}")

    if not os.path.isdir(disp_dir):
        missing.append(f"Missing disparity output directory: {disp_dir}")

    if missing:
        for item in missing:
            print(f"ERROR: {item}")

        raise FileNotFoundError(
            "Reliable output was not written because required paths are missing:\n"
            + "\n".join(missing)
        )

    write_reliable_outputs(
        disp_dir=disp_dir,
        Z_path=Z_path,
        C_path=C_path,
        thresh=reliable_thresh,
        base_name=reliable_base_name,
    )

    print("Reliable output generation complete.")


# ----------------------------------------------------------
# Run standalone
# ----------------------------------------------------------

if __name__ == "__main__":
    convert_scene_imgb_to_png(
        scene_dir="Python_Red/Bit_Manipulation/head",
        reliable_thresh=0.3,
        z_conf_rel_path="disparity/Z_conf.imgb",
        c_avg_rel_path="confidence/C_avg.imgb",
        reliable_base_name="reliable_avg_Z_conf_0_3",
    )
    print("Done.")
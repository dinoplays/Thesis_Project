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
    Q_SCALE,
)

P_LO = 2.0
P_HI = 98.0


# ----------------------------------------------------------
# Fast decode helpers
# ----------------------------------------------------------

def _decode_u24_q12_12(payload: bytes, n_samples: int) -> np.ndarray:
    """
    payload: length n_samples*3
    returns float32 array length n_samples: (u24 - BIAS_INT) / Q_SCALE
    """
    b = np.frombuffer(payload, dtype=np.uint8).reshape((-1, 3))
    u = b[:, 0].astype(np.uint32) | (b[:, 1].astype(np.uint32) << 8) | (b[:, 2].astype(np.uint32) << 16)
    out = (u.astype(np.int32) - np.int32(BIAS_INT)).astype(np.float32) / np.float32(Q_SCALE)
    return out


# ----------------------------------------------------------
# Decode IMGB -> float32 image
# ----------------------------------------------------------

def read_imgb(path_in: str) -> tuple[np.ndarray, int]:
    with open(path_in, "rb") as f:
        blob = f.read()

    W, H, C, dtype_code, payload = imgb_parse(blob)

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
    Z, _ = read_imgb(Z_path)
    C, _ = read_imgb(C_path)

    if Z.ndim != 2 or C.ndim != 2:
        raise ValueError("Reliable output expects Z and C to be single-channel images (H,W)")

    mask_ok = np.isfinite(Z) & np.isfinite(C) & (C >= float(thresh))

    out_linear_dir = disp_dir.rstrip("/\\") + "_png"
    out_robust_dir = disp_dir.rstrip("/\\") + "_robust_png"
    os.makedirs(out_linear_dir, exist_ok=True)
    os.makedirs(out_robust_dir, exist_ok=True)

    out_linear = os.path.join(out_linear_dir, base_name + ".png")
    out_robust = os.path.join(out_robust_dir, base_name + ".png")

    # Same visual style in both output folders (pink-mask is its own visualization).
    save_gray_with_pink_mask(Z, mask_ok, out_linear)
    save_gray_with_pink_mask(Z, mask_ok, out_robust)


# ----------------------------------------------------------
# One-shot scene conversion (called from main)
# ----------------------------------------------------------

def convert_scene_imgb_to_png(
    *,
    scene_dir: str,
    reliable_thresh: float = 0.25,
    z_conf_rel_path: str = "disparity/Z_conf.imgb",
    c_avg_rel_path: str = "confidence/C_avg.imgb",
    reliable_base_name: str = "reliable_avg_Z_conf_0_25",
) -> None:
    """
    Converts:
      scene_dir/cross_data_blurred  -> *_png and *_robust_png
      scene_dir/confidence         -> *_png and *_robust_png
      scene_dir/disparity          -> *_png and *_robust_png

    And writes reliable visualization into disparity_png and disparity_robust_png.
    """
    cross_dir = os.path.join(scene_dir, "cross_data_blurred")
    conf_dir = os.path.join(scene_dir, "confidence")
    disp_dir = os.path.join(scene_dir, "disparity")

    if os.path.isdir(cross_dir):
        convert_folder_imgb_to_png(cross_dir)
    if os.path.isdir(conf_dir):
        convert_folder_imgb_to_png(conf_dir)
    if os.path.isdir(disp_dir):
        convert_folder_imgb_to_png(disp_dir)

    Z_path = os.path.join(scene_dir, z_conf_rel_path)
    C_path = os.path.join(scene_dir, c_avg_rel_path)
    if os.path.exists(Z_path) and os.path.exists(C_path) and os.path.isdir(disp_dir):
        write_reliable_outputs(
            disp_dir=disp_dir,
            Z_path=Z_path,
            C_path=C_path,
            thresh=reliable_thresh,
            base_name=reliable_base_name,
        )


# ----------------------------------------------------------
# Run standalone
# ----------------------------------------------------------

if __name__ == "__main__":
    convert_scene_imgb_to_png(
        scene_dir="headshot",
        reliable_thresh=0.25,
        z_conf_rel_path="disparity/Z_conf.imgb",
        c_avg_rel_path="confidence/C_avg.imgb",
        reliable_base_name="reliable_avg_Z_conf_0_25",
    )
    print("Done.")
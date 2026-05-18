# bin_to_png.py
# Convert custom .imgb files (IMGB header + raw pixels) back to .png images.
#
# Produces TWO outputs for every folder:
#   1) Linear/original bounds  ->  ..._png
#   2) Full-range normalised   ->  ..._normalised_png
#
# Also produces an additional reliable disparity visualisation:
#   gray disparity with pink mask where confidence < threshold.
#
# Important:
#   The signed disparity stored in .imgb is NOT modified here.
#   Clamping and black/white inversion are visualisation-only.
#
# Display convention for disparity folders:
#   - Z <= 0 remains black.
#   - Positive disparity is normalised using 0-100 range.
#   - The positive disparity grayscale is inverted:
#       larger positive disparity -> darker
#       smaller positive disparity -> whiter

import os
import imageio.v3 as iio
import numpy as np

from utils import (
    imgb_parse,
    BIAS_INT,
    Q_SCALE,
)

P_LO = 0.0
P_HI = 100.0

INVERT_DISPARITY_DISPLAY = True


# ----------------------------------------------------------
# Fast decode helpers
# ----------------------------------------------------------

def _decode_u24_q12_12(payload: bytes, n_samples: int) -> np.ndarray:
    """
    payload:
        length n_samples * 3

    returns:
        float32 array length n_samples:
            (u24 - BIAS_INT) / Q_SCALE
    """

    b = np.frombuffer(payload, dtype=np.uint8).reshape((-1, 3))

    u = (
        b[:, 0].astype(np.uint32)
        | (b[:, 1].astype(np.uint32) << 8)
        | (b[:, 2].astype(np.uint32) << 16)
    )

    out = (
        u.astype(np.int32) - np.int32(BIAS_INT)
    ).astype(np.float32) / np.float32(Q_SCALE)

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
# Path/type helpers
# ----------------------------------------------------------

def _is_disparity_path(path: str) -> bool:
    """
    Returns True for images inside a disparity folder.

    Only disparity visualisations:
        - force values <= 0 to black
        - invert positive grayscale if INVERT_DISPARITY_DISPLAY=True
    """

    parts = path.replace("\\", "/").split("/")
    return "disparity" in parts


# ----------------------------------------------------------
# Linear mapping
# ----------------------------------------------------------

def linear_to_u8(
    img: np.ndarray,
    *,
    clamp_nonpositive: bool = False,
    invert_valid: bool = False,
) -> np.ndarray:
    """
    Linear mapping to u8.

    If clamp_nonpositive=True:
        values <= 0 are forced to black for visualisation only.

    If invert_valid=True:
        only valid displayed pixels are inverted:
            0   -> 255
            255 -> 0

        Invalid/non-positive pixels remain black.
    """

    x = img.astype(np.float32, copy=False)

    if clamp_nonpositive:
        valid = np.isfinite(x) & (x > 0.0)
    else:
        valid = np.isfinite(x)

    out = np.zeros(x.shape, dtype=np.uint8)

    if not valid.any():
        return out

    y = np.clip(x, 0.0, 255.0).astype(np.uint8)

    if invert_valid:
        y = 255 - y

    out[valid] = y[valid]

    return out


# ----------------------------------------------------------
# Full-range normalisation
# ----------------------------------------------------------

def normalise_to_u8(
    img: np.ndarray,
    *,
    clamp_nonpositive: bool = False,
    invert_valid: bool = False,
) -> np.ndarray:
    """
    Full-range normalise image to u8 using 0-100 percentile range.

    If clamp_nonpositive=True:
        values <= 0 are forced to black for visualisation only.
        The 0-100 range is computed using only positive finite values.

    If invert_valid=True:
        only valid displayed pixels are inverted:
            smallest positive value -> white
            largest positive value  -> black

        Invalid/non-positive pixels remain black.
    """

    x = img.astype(np.float32, copy=False)

    if clamp_nonpositive:
        valid = np.isfinite(x) & (x > 0.0)
    else:
        valid = np.isfinite(x)

    out = np.zeros(x.shape, dtype=np.uint8)

    if not valid.any():
        return out

    vals = x[valid]

    lo = np.percentile(vals, P_LO)
    hi = np.percentile(vals, P_HI)

    if not np.isfinite(lo):
        lo = 0.0

    if not np.isfinite(hi):
        hi = lo + 1.0

    if hi <= lo:
        hi = lo + 1.0

    y = (x - lo) / (hi - lo)
    y = np.clip(y, 0.0, 1.0)
    y = (y * 255.0 + 0.5).astype(np.uint8)

    if invert_valid:
        y = 255 - y

    out[valid] = y[valid]

    return out


# ----------------------------------------------------------
# Reliable disparity visualisation helpers
# ----------------------------------------------------------

def _visual_limits_positive(Z: np.ndarray) -> tuple[float, float]:
    """
    Return 0-100 percentile visualisation limits over positive finite disparity only.
    """

    Z = np.asarray(Z, dtype=np.float32)

    valid = np.isfinite(Z) & (Z > 0.0)

    if not valid.any():
        return 0.0, 1.0

    vals = Z[valid]

    lo = float(np.percentile(vals, P_LO))
    hi = float(np.percentile(vals, P_HI))

    if not np.isfinite(lo):
        lo = 0.0

    if not np.isfinite(hi):
        hi = lo + 1.0

    if hi <= lo:
        hi = lo + 1.0

    return lo, hi


def save_gray_with_pink_mask(Z: np.ndarray, mask_ok: np.ndarray, out_png: str) -> None:
    """
    Z:
        float32 disparity image, shape (H, W)

    mask_ok:
        bool mask, shape (H, W), True where reliable

    Visualisation behaviour:
        - Z <= 0 is black.
        - reliable positive Z is grayscale.
        - unreliable positive Z is pink.
        - positive grayscale is inverted if INVERT_DISPARITY_DISPLAY=True.
    """

    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)

    Z = np.asarray(Z, dtype=np.float32)
    mask_ok = np.asarray(mask_ok, dtype=bool)

    if Z.ndim != 2:
        raise ValueError("save_gray_with_pink_mask expects Z to be a 2D image")

    if mask_ok.shape != Z.shape:
        raise ValueError("mask_ok shape must match Z shape")

    positive = np.isfinite(Z) & (Z > 0.0)

    vmin, vmax = _visual_limits_positive(Z)

    norm = (Z - vmin) / (vmax - vmin)
    norm = np.clip(norm, 0.0, 1.0)
    gray = (norm * 255.0 + 0.5).astype(np.uint8)

    if INVERT_DISPARITY_DISPLAY:
        gray = 255 - gray

    rgb = np.zeros((Z.shape[0], Z.shape[1], 3), dtype=np.uint8)

    reliable_positive = positive & mask_ok
    unreliable_positive = positive & (~mask_ok)

    # Reliable positive disparity: grayscale.
    rgb[..., 0][reliable_positive] = gray[reliable_positive]
    rgb[..., 1][reliable_positive] = gray[reliable_positive]
    rgb[..., 2][reliable_positive] = gray[reliable_positive]

    # Unreliable positive disparity: pink.
    rgb[..., 0][unreliable_positive] = 255
    rgb[..., 1][unreliable_positive] = 102
    rgb[..., 2][unreliable_positive] = 179

    # Z <= 0 remains black because rgb was initialised to zero.
    iio.imwrite(out_png, rgb)


# ----------------------------------------------------------
# Folder conversion
# ----------------------------------------------------------

def convert_folder_imgb_to_png(in_dir: str) -> tuple[str, str]:
    out_linear = in_dir.rstrip("/\\") + "_png"
    out_normalised = in_dir.rstrip("/\\") + "_normalised_png"

    os.makedirs(out_linear, exist_ok=True)
    os.makedirs(out_normalised, exist_ok=True)

    names = [n for n in os.listdir(in_dir) if n.lower().endswith(".imgb")]
    names.sort()

    is_disparity = _is_disparity_path(in_dir)

    clamp_nonpositive = is_disparity
    invert_valid = is_disparity and INVERT_DISPARITY_DISPLAY

    for name in names:
        src = os.path.join(in_dir, name)
        base = os.path.splitext(name)[0]

        img, _dtype = read_imgb(src)

        # -------- Linear
        linear = linear_to_u8(
            img,
            clamp_nonpositive=clamp_nonpositive,
            invert_valid=invert_valid,
        )
        iio.imwrite(os.path.join(out_linear, base + ".png"), linear)

        # -------- Full-range normalised
        if img.ndim == 3:
            chans = []

            for c in range(img.shape[2]):
                chans.append(
                    normalise_to_u8(
                        img[..., c],
                        clamp_nonpositive=clamp_nonpositive,
                        invert_valid=invert_valid,
                    )
                )

            normalised = np.stack(chans, axis=2)
        else:
            normalised = normalise_to_u8(
                img,
                clamp_nonpositive=clamp_nonpositive,
                invert_valid=invert_valid,
            )

        iio.imwrite(os.path.join(out_normalised, base + ".png"), normalised)

    return out_linear, out_normalised


# ----------------------------------------------------------
# Reliable disparity output
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
      disp_dir_normalised_png/<base_name>.png

    Visualisation behaviour:
        - Z <= 0 is black.
        - reliable positive Z is grayscale.
        - unreliable positive Z is pink.
        - positive grayscale is inverted if INVERT_DISPARITY_DISPLAY=True.
    """

    Z, _ = read_imgb(Z_path)
    C, _ = read_imgb(C_path)

    if Z.ndim != 2 or C.ndim != 2:
        raise ValueError("Reliable output expects Z and C to be single-channel images (H,W)")

    mask_ok = np.isfinite(Z) & np.isfinite(C) & (C >= float(thresh))

    out_linear_dir = disp_dir.rstrip("/\\") + "_png"
    out_normalised_dir = disp_dir.rstrip("/\\") + "_normalised_png"

    os.makedirs(out_linear_dir, exist_ok=True)
    os.makedirs(out_normalised_dir, exist_ok=True)

    out_linear = os.path.join(out_linear_dir, base_name + ".png")
    out_normalised = os.path.join(out_normalised_dir, base_name + ".png")

    save_gray_with_pink_mask(Z, mask_ok, out_linear)
    print(f"Saved to: {out_linear}")

    save_gray_with_pink_mask(Z, mask_ok, out_normalised)
    print(f"Saved to: {out_normalised}")


# ----------------------------------------------------------
# One-shot scene conversion
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
      scene_dir/cross_data_q12_12  -> *_png and *_normalised_png
      scene_dir/confidence         -> *_png and *_normalised_png
      scene_dir/disparity          -> *_png and *_normalised_png

    And writes reliable visualisation into disparity_png and disparity_normalised_png.
    """

    print("=== convert_scene_imgb_to_png debug ===")
    print(f"scene_dir: {scene_dir}")
    print(f"reliable_thresh: {reliable_thresh}")
    print(f"z_conf_rel_path: {z_conf_rel_path}")
    print(f"c_avg_rel_path: {c_avg_rel_path}")
    print(f"invert_disparity_display: {INVERT_DISPARITY_DISPLAY}")

    if not os.path.isdir(scene_dir):
        raise FileNotFoundError(
            f"scene_dir does not exist or is not a directory: {scene_dir}"
        )

    cross_dir = os.path.join(scene_dir, "cross_data_q12_12")
    conf_dir = os.path.join(scene_dir, "confidence")
    disp_dir = os.path.join(scene_dir, "disparity")

    print(f"cross_dir: {cross_dir} | exists={os.path.isdir(cross_dir)}")
    print(f"conf_dir:  {conf_dir} | exists={os.path.isdir(conf_dir)}")
    print(f"disp_dir:  {disp_dir} | exists={os.path.isdir(disp_dir)}")

    if os.path.isdir(cross_dir):
        out_linear, out_normalised = convert_folder_imgb_to_png(cross_dir)
        print(f"Converted cross data to: {out_linear}")
        print(f"Converted cross data to: {out_normalised}")
    else:
        print(f"Skipping cross conversion; missing folder: {cross_dir}")

    if os.path.isdir(conf_dir):
        out_linear, out_normalised = convert_folder_imgb_to_png(conf_dir)
        print(f"Converted confidence to: {out_linear}")
        print(f"Converted confidence to: {out_normalised}")
    else:
        print(f"Skipping confidence conversion; missing folder: {conf_dir}")

    if os.path.isdir(disp_dir):
        out_linear, out_normalised = convert_folder_imgb_to_png(disp_dir)
        print(f"Converted disparity to: {out_linear}")
        print(f"Converted disparity to: {out_normalised}")
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
    for scene in ["dino", "head", "town"]:
        convert_scene_imgb_to_png(
            scene_dir=f"Python_Red/No_Libraries/{scene}",
            reliable_thresh=1,
            z_conf_rel_path="disparity/Z_conf.imgb",
            c_avg_rel_path="confidence/C_avg.imgb",
            reliable_base_name="reliable_avg_Z_conf_1",
        )

    print("Done.")
# bin_to_png.py
# Convert custom .imgb files (IMGB header + raw pixels) back to .png images.
#
# Produces TWO outputs for every folder:
#   1) Linear/original bounds  ->  ..._png
#   2) Full-range normalised   ->  ..._normalised_png
#
# Also produces reliable disparity visualisations for both non-filled and filled outputs:
#   gray disparity with pink mask where confidence < threshold.
#
# Important:
#   The signed disparity stored in .imgb is NOT modified here.
#   Clamping and black/white inversion are visualisation-only.
#
# Display convention for disparity folders:
#   The stored disparity is not modified. For display only, the plotted value is:
#       Z_display = Z_stored - DISPARITY_DISPLAY_OFFSET
#
#   Linear/original PNGs:
#       - Z_display <= 0 remains black.
#       - Positive Z_display is clipped to 0..255.
#
#   Normalised PNGs:
#       - Z_display < 0 remains black.
#       - Z_display = 0 is white.
#       - Positive Z_display is normalised using the 0-100 percentile range.
#       - The positive disparity grayscale is inverted:
#           smaller positive Z_display -> whiter
#           larger positive Z_display  -> darker / blacker.
#
# This matches the intended depth-display convention after removing the +1
# inverse-depth baseline used by the estimator:
#   negative = black, zero/near = white, far/infinity = black.

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
DISPARITY_DISPLAY_OFFSET = 1.0


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
# Disparity display offset
# ----------------------------------------------------------

def apply_disparity_display_offset(img: np.ndarray) -> np.ndarray:
    """
    Return the display-only disparity values.

    The stored IMGB disparity is not modified.  Only PNG visualisation uses
    Z_display = Z_stored - DISPARITY_DISPLAY_OFFSET.
    """

    return img.astype(np.float32, copy=False) - np.float32(DISPARITY_DISPLAY_OFFSET)


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
        only valid positive/displayed pixels are inverted:
            0 -> 255
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
        only valid positive/displayed pixels are inverted:
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
# Disparity-specific normalisation
# ----------------------------------------------------------

def normalise_disparity_to_u8(img: np.ndarray) -> np.ndarray:
    """
    Normalise a disparity image using the intended display convention.

    Behaviour:
        - NaN/Inf -> black
        - Z < 0   -> black
        - Z = 0   -> white
        - Z > 0   -> inverse-normalised grayscale:
              small positive disparity -> white
              large positive disparity -> black

    The percentile limits are computed from positive finite disparity only.
    Negative and zero values are not used to set the positive-disparity range.
    """

    x = img.astype(np.float32, copy=False)

    finite = np.isfinite(x)
    negative = finite & (x < 0.0)
    zero = finite & (x == 0.0)
    positive = finite & (x > 0.0)

    out = np.zeros(x.shape, dtype=np.uint8)

    # Zero disparity is explicitly white.
    out[zero] = 255

    # Negative and invalid pixels remain black because out was initialised to 0.
    _ = negative

    if not positive.any():
        return out

    vals = x[positive]

    lo = np.percentile(vals, P_LO)
    hi = np.percentile(vals, P_HI)

    if not np.isfinite(lo):
        lo = 0.0

    if not np.isfinite(hi):
        hi = lo + 1.0

    if hi <= lo:
        # Degenerate positive disparity case: all positive values are the same.
        # Treat them as near/white while negatives remain black.
        out[positive] = 255
        return out

    norm = (x - lo) / (hi - lo)
    norm = np.clip(norm, 0.0, 1.0)

    # Invert positive disparity:
    #   lo / small positive -> 255
    #   hi / large positive -> 0
    inv = 1.0 - norm
    inv_u8 = (inv * 255.0 + 0.5).astype(np.uint8)

    out[positive] = inv_u8[positive]

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
        - The stored Z is first converted to Z_display = Z - DISPARITY_DISPLAY_OFFSET.
        - Z_display < 0 is black.
        - Z_display = 0 is white.
        - reliable positive Z_display is grayscale.
        - unreliable positive Z_display is pink.
        - positive grayscale can be inverted using INVERT_DISPARITY_DISPLAY.
    """

    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)

    Z = np.asarray(Z, dtype=np.float32)
    mask_ok = np.asarray(mask_ok, dtype=bool)

    if Z.ndim != 2:
        raise ValueError("save_gray_with_pink_mask expects Z to be a 2D image")

    if mask_ok.shape != Z.shape:
        raise ValueError("mask_ok shape must match Z shape")

    # Display-only conversion. Do not modify the stored disparity values.
    Z = apply_disparity_display_offset(Z)

    finite = np.isfinite(Z)
    zero = finite & (Z == 0.0)
    positive = finite & (Z > 0.0)

    vmin, vmax = _visual_limits_positive(Z)

    norm = (Z - vmin) / (vmax - vmin)
    norm = np.clip(norm, 0.0, 1.0)
    gray = (norm * 255.0 + 0.5).astype(np.uint8)

    if INVERT_DISPARITY_DISPLAY:
        gray = 255 - gray

    rgb = np.zeros((Z.shape[0], Z.shape[1], 3), dtype=np.uint8)

    reliable_positive = positive & mask_ok
    unreliable_positive = positive & (~mask_ok)

    # Zero disparity is white.
    rgb[..., 0][zero] = 255
    rgb[..., 1][zero] = 255
    rgb[..., 2][zero] = 255

    # Reliable positive disparity: grayscale.
    rgb[..., 0][reliable_positive] = gray[reliable_positive]
    rgb[..., 1][reliable_positive] = gray[reliable_positive]
    rgb[..., 2][reliable_positive] = gray[reliable_positive]

    # Unreliable positive disparity: pink.
    rgb[..., 0][unreliable_positive] = 255
    rgb[..., 1][unreliable_positive] = 102
    rgb[..., 2][unreliable_positive] = 179

    # Z < 0 and invalid pixels remain black because rgb was initialised to zero.
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

        if is_disparity:
            img_for_display = apply_disparity_display_offset(img)
        else:
            img_for_display = img

        # -------- Linear
        linear = linear_to_u8(
            img_for_display,
            clamp_nonpositive=clamp_nonpositive,
            invert_valid=invert_valid,
        )
        iio.imwrite(os.path.join(out_linear, base + ".png"), linear)

        # -------- Full-range normalised
        if is_disparity:
            if img.ndim == 3:
                chans = []

                for c in range(img.shape[2]):
                    chans.append(normalise_disparity_to_u8(img_for_display[..., c]))

                normalised = np.stack(chans, axis=2)
            else:
                normalised = normalise_disparity_to_u8(img_for_display)
        else:
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
                    img_for_display,
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
        - Z < 0 is black.
        - Z = 0 is white.
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

def _filled_reliable_base_name(base_name: str) -> str:
    """
    Build the filled-output reliable PNG base name from the non-filled base name.

    Examples:
        reliable_avg_Z_conf_1p25 -> reliable_avg_Z_conf_filled_blurred_1p25
        reliable_avg_Z_conf_1    -> reliable_avg_Z_conf_filled_blurred_1
    """

    if "Z_conf" in base_name:
        return base_name.replace("Z_conf", "Z_conf_filled_blurred", 1)

    return base_name + "_filled_blurred"


def _build_reliable_specs(
    *,
    scene_dir: str,
    z_conf_rel_path: str,
    reliable_base_name: str,
    reliable_specs: list[tuple[str, str]] | None,
) -> list[tuple[str, str]]:
    """
    Build the list of reliable visualisations to write.

    By default this writes:
        1) the requested Z_conf path, normally the non-filled blurred output
        2) disparity/Z_conf_filled_blurred.imgb, if it exists

    This keeps Z_conf.imgb as the direct FPGA comparison target while still
    producing the filled output for future-work visualisation.
    """

    if reliable_specs is not None:
        return list(reliable_specs)

    specs: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(rel_path: str, base_name: str) -> None:
        norm = rel_path.replace("\\", "/")
        if norm in seen:
            return
        seen.add(norm)
        specs.append((rel_path, base_name))

    add(z_conf_rel_path, reliable_base_name)

    filled_rel_path = "disparity/Z_conf_filled_blurred.imgb"
    filled_abs_path = os.path.join(scene_dir, filled_rel_path)

    if os.path.exists(filled_abs_path):
        add(filled_rel_path, _filled_reliable_base_name(reliable_base_name))

    return specs


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
    reliable_specs: list[tuple[str, str]] | None = None,
) -> None:
    """
    Converts:
      scene_dir/cross_data_q12_12  -> *_png and *_normalised_png
      scene_dir/confidence         -> *_png and *_normalised_png
      scene_dir/disparity          -> *_png and *_normalised_png

    Reliable visualisations:
      - non-filled blurred output, normally disparity/Z_conf.imgb
      - filled blurred output, disparity/Z_conf_filled_blurred.imgb, when present

    The non-filled blurred output is the direct FPGA comparison target. The
    filled blurred output is kept for future work and should not be used for
    current FPGA comparisons unless the FPGA also implements filling.
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

    C_path = os.path.join(scene_dir, c_avg_rel_path)
    print(f"Resolved C_path: {C_path}")
    print(f"C_path exists: {os.path.exists(C_path)}")
    print(f"disp_dir exists: {os.path.isdir(disp_dir)}")

    missing = []

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

    specs = _build_reliable_specs(
        scene_dir=scene_dir,
        z_conf_rel_path=z_conf_rel_path,
        reliable_base_name=reliable_base_name,
        reliable_specs=reliable_specs,
    )

    written = 0
    for z_rel_path, base_name in specs:
        Z_path = os.path.join(scene_dir, z_rel_path)
        print(f"Resolved Z_path: {Z_path}")
        print(f"Z_path exists: {os.path.exists(Z_path)}")

        if not os.path.exists(Z_path):
            print(f"Skipping reliable output; missing disparity file: {Z_path}")
            continue

        write_reliable_outputs(
            disp_dir=disp_dir,
            Z_path=Z_path,
            C_path=C_path,
            thresh=reliable_thresh,
            base_name=base_name,
        )
        written += 1

    if written == 0:
        raise FileNotFoundError(
            "No reliable disparity outputs were written because no requested Z paths existed."
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
# center_crop_png.py
# Input images are expected to be 512x512.
# The crop is the exact central 64x64 region.
#
# Directory structure:
#   Python_RGB/No_Libraries/{scene}/cross_raw_data_png
#   Python_RGB/No_Libraries/{scene}/confidence_png
#   Python_RGB/No_Libraries/{scene}/confidence_normalised_png
#   Python_RGB/No_Libraries/{scene}/disparity_png
#   Python_RGB/No_Libraries/{scene}/disparity_normalised_png
#
# Only final/summary outputs are cropped from confidence/disparity folders, including both non-filled and filled variants.
# Intermediate per-channel/per-axis files such as C_h_red, C_v_blue, Z_h_red,
# Z_v_green, etc. are skipped.
#
# Important:
#   Any cropped output whose path/name contains normalised/normalized/robust
#   is renormalised AFTER the centre crop. This means the crop gets its own
#   full 0-255 display range instead of inheriting the original scale.
#
#   Disparity normalised outputs use a special renormalisation:
#       - black pixels remain black (negative/invalid/far values)
#       - white pixels remain white (zero/near values)
#       - non-black grayscale disparity pixels are renormalised only within
#         the displayed positive-disparity range.
#
#   This preserves the intended convention used by bin_to_png.py:
#       negative = black, zero/near = white, far/infinity = black.

import os
import numpy as np
import imageio.v3 as iio


# ------------------------------------------------------------
# User-configurable settings
# ------------------------------------------------------------

ROOT = "Python_RGB/No_Libraries"

SCENES = [
    "dino",
    "head",
    "town",
]

CROP_H = 64
CROP_W = 64

EXPECTED_H = 512
EXPECTED_W = 512

# This controls the reliable confidence output file name.
# Example:
#   1.25 -> reliable_avg_Z_conf_1p25.png
#   1.0  -> reliable_avg_Z_conf_1.png
#   0.3  -> reliable_avg_Z_conf_0p3.png
RELIABLE_CONFIDENCE_THRESHOLD = 1.25

# Pink mask colour used by reliable disparity visualisations.
# Keep this fixed so masked/invalid pixels are not destroyed by renormalisation.
MASK_RGB = (255, 102, 179)


# ------------------------------------------------------------
# Naming helper
# ------------------------------------------------------------

def threshold_to_filename_token(threshold: float) -> str:
    """
    Convert a numeric threshold into the filename token used by bin_to_png.py.

    Examples:
        1.25 -> "1p25"
        1.0  -> "1"
        0.3  -> "0p3"
    """

    text = str(float(threshold))

    if text.endswith(".0"):
        text = text[:-2]

    return text.replace(".", "p")


# ------------------------------------------------------------
# Crop helper
# ------------------------------------------------------------

def crop_center_image(img, crop_h: int = 64, crop_w: int = 64):
    img_h = int(img.shape[0])
    img_w = int(img.shape[1])

    if crop_h > img_h or crop_w > img_w:
        raise ValueError(
            f"Crop size ({crop_h}x{crop_w}) is larger than image size ({img_h}x{img_w})"
        )

    start_y = (img_h - crop_h) // 2
    start_x = (img_w - crop_w) // 2

    end_y = start_y + crop_h
    end_x = start_x + crop_w

    return img[start_y:end_y, start_x:end_x]


# ------------------------------------------------------------
# Renormalisation helpers
# ------------------------------------------------------------

def should_renormalise_after_crop(path: str) -> bool:
    """
    Decide whether the cropped PNG should be renormalised.

    This catches folders/files such as:
        confidence_normalised_png
        disparity_normalised_png
        *_normalised.png
        *_normalized.png
        *_robust.png
    """

    lower = path.replace("\\", "/").lower()

    tokens = [
        "normalised",
        "normalized",
        "normalise",
        "normalize",
        "robust",
    ]

    for token in tokens:
        if token in lower:
            return True

    return False



def is_disparity_normalised_path(path: str) -> bool:
    """
    Return True for normalised disparity visualisations.

    These images already encode the intended display convention:
        black = negative/invalid/far
        white = zero/near
        positive disparity uses inverted grayscale
    """

    lower = path.replace("\\", "/").lower()

    has_disparity = "disparity" in lower or "z_conf" in lower
    has_normalised = (
        "normalised" in lower
        or "normalized" in lower
        or "normalise" in lower
        or "normalize" in lower
        or "robust" in lower
    )

    return has_disparity and has_normalised


def normalise_disparity_display_gray_u8(arr) -> np.ndarray:
    """
    Renormalise a cropped normalised disparity PNG without breaking its display
    convention.

    Input assumption:
        - black pixels represent negative/invalid/far values
        - brighter pixels represent smaller/nearer valid disparity
        - white represents zero/near

    Behaviour:
        - black pixels stay black
        - non-black grayscale values are stretched to the full 1..255 range
        - the ordering is preserved: brighter stays nearer/whiter
    """

    x = arr.astype(np.float32)
    valid = np.isfinite(x)
    nonblack = valid & (x > 0.0)

    out = np.zeros(x.shape, dtype=np.uint8)

    if not np.any(nonblack):
        return out

    vals = x[nonblack]

    lo = float(np.min(vals))
    hi = float(np.max(vals))

    if not np.isfinite(lo):
        lo = 0.0

    if not np.isfinite(hi):
        hi = lo + 1.0

    if hi <= lo:
        out[nonblack] = 255
        return out

    y = (x - lo) / (hi - lo)
    y = np.clip(y, 0.0, 1.0)

    # Map non-black valid display range to 1..255 so black remains reserved
    # for negative/invalid/far pixels.
    out[nonblack] = (y[nonblack] * 254.0 + 1.0 + 0.5).astype(np.uint8)

    return out



def normalise_gray_u8(arr) -> np.ndarray:
    """
    Min-max renormalise a grayscale crop to uint8 [0, 255].

    If the crop is constant, returns zeros to avoid divide-by-zero.
    """

    x = arr.astype(np.float32)

    valid = np.isfinite(x)

    out = np.zeros(x.shape, dtype=np.uint8)

    if not np.any(valid):
        return out

    vals = x[valid]

    lo = float(np.min(vals))
    hi = float(np.max(vals))

    if not np.isfinite(lo):
        lo = 0.0

    if not np.isfinite(hi):
        hi = lo + 1.0

    if hi <= lo:
        return out

    y = (x - lo) / (hi - lo)
    y = np.clip(y, 0.0, 1.0)

    out[valid] = (y[valid] * 255.0 + 0.5).astype(np.uint8)

    return out


def is_pink_mask_rgb(img_rgb: np.ndarray) -> np.ndarray:
    """
    Detect pink mask pixels.

    Uses exact RGB match because the mask is normally written as:
        (255, 102, 179)

    A small tolerance is included in case the PNG was saved with minor changes.
    """

    rgb = img_rgb.astype(np.int16)

    r = rgb[..., 0]
    g = rgb[..., 1]
    b = rgb[..., 2]

    return (
        (np.abs(r - MASK_RGB[0]) <= 2)
        & (np.abs(g - MASK_RGB[1]) <= 2)
        & (np.abs(b - MASK_RGB[2]) <= 2)
    )


def is_grayscale_rgb_pixel(img_rgb: np.ndarray) -> np.ndarray:
    """
    Detect pixels where R, G, and B are effectively equal.
    """

    rgb = img_rgb.astype(np.int16)

    r = rgb[..., 0]
    g = rgb[..., 1]
    b = rgb[..., 2]

    return (
        (np.abs(r - g) <= 1)
        & (np.abs(r - b) <= 1)
        & (np.abs(g - b) <= 1)
    )


def normalise_rgb_preserve_mask_u8(img_rgb: np.ndarray) -> np.ndarray:
    """
    Renormalise an RGB crop.

    If the image is a grayscale visualisation with a pink mask:
        - renormalise only the grayscale pixels
        - preserve pink mask pixels exactly

    Otherwise:
        - renormalise each RGB channel independently
    """

    if img_rgb.ndim != 3:
        raise ValueError("normalise_rgb_preserve_mask_u8 expects an RGB/RGBA image")

    # Drop alpha only for processing; alpha is not needed for these PNGs.
    if img_rgb.shape[2] == 4:
        rgb = img_rgb[..., :3]
    else:
        rgb = img_rgb

    pink = is_pink_mask_rgb(rgb)
    gray_like = is_grayscale_rgb_pixel(rgb)
    gray_valid = gray_like & (~pink)

    out = np.zeros(rgb.shape, dtype=np.uint8)

    # Case 1: reliable disparity style image:
    # mostly grayscale, possibly with pink invalid pixels.
    if np.any(gray_valid):
        gray_values = rgb[..., 0].astype(np.float32)
        gray_nonblack = gray_valid & (gray_values > 0.0)

        if np.any(gray_nonblack):
            vals = gray_values[gray_nonblack]

            lo = float(np.min(vals))
            hi = float(np.max(vals))

            if hi > lo:
                norm = (gray_values - lo) / (hi - lo)
                norm = np.clip(norm, 0.0, 1.0)
                # Keep 0 reserved for black negative/invalid/far pixels.
                norm_u8 = (norm * 254.0 + 1.0 + 0.5).astype(np.uint8)
            else:
                norm_u8 = np.zeros(gray_values.shape, dtype=np.uint8)
                norm_u8[gray_nonblack] = 255

            out[..., 0][gray_nonblack] = norm_u8[gray_nonblack]
            out[..., 1][gray_nonblack] = norm_u8[gray_nonblack]
            out[..., 2][gray_nonblack] = norm_u8[gray_nonblack]

        # Black grayscale pixels remain black.

        out[..., 0][pink] = MASK_RGB[0]
        out[..., 1][pink] = MASK_RGB[1]
        out[..., 2][pink] = MASK_RGB[2]

        # Any non-gray, non-pink pixels are copied through unchanged.
        other = (~gray_valid) & (~pink)

        out[..., 0][other] = rgb[..., 0][other]
        out[..., 1][other] = rgb[..., 1][other]
        out[..., 2][other] = rgb[..., 2][other]

        return out

    # Case 2: generic RGB image.
    for c in range(3):
        out[..., c] = normalise_gray_u8(rgb[..., c])

    return out


def renormalise_after_crop_if_needed(cropped, source_path: str, output_path: str):
    """
    Renormalise the crop if either the source path or output path implies
    a normalised/robust visualisation.
    """

    renorm = (
        should_renormalise_after_crop(source_path)
        or should_renormalise_after_crop(output_path)
    )

    if not renorm:
        return cropped

    arr = np.asarray(cropped)

    is_disp_norm = (
        is_disparity_normalised_path(source_path)
        or is_disparity_normalised_path(output_path)
    )

    if arr.ndim == 2:
        if is_disp_norm:
            return normalise_disparity_display_gray_u8(arr)
        return normalise_gray_u8(arr)

    if arr.ndim == 3:
        if is_disp_norm:
            return normalise_rgb_preserve_mask_u8(arr)
        return normalise_rgb_preserve_mask_u8(arr)

    raise ValueError(f"Unsupported image dimensions for renormalisation: {arr.shape}")


# ------------------------------------------------------------
# File filtering
# ------------------------------------------------------------

def should_crop_file(folder_kind: str, name: str) -> bool:
    """
    Decide whether a PNG should be centre-cropped.

    folder_kind:
        "cross_raw"
        "confidence"
        "disparity"

    Rules:
        cross_raw:
            crop all PNGs in cross_raw_data_png.

        confidence:
            crop only final average confidence files.
            This avoids C_h_red, C_v_blue, C_avg_red, etc.

        disparity:
            crop only final fused/reliable disparity files.
            This avoids Z_h_red, Z_v_green, etc.
    """

    lower = name.lower()

    if not lower.endswith(".png"):
        return False

    if folder_kind == "cross_raw":
        return True

    if folder_kind == "confidence":
        allowed = {
            "c_avg.png",
            "c_avg_rgb.png",
        }

        return lower in allowed

    if folder_kind == "disparity":
        threshold_token = threshold_to_filename_token(
            RELIABLE_CONFIDENCE_THRESHOLD
        )

        reliable_name = f"reliable_avg_z_conf_{threshold_token}.png"
        reliable_filled_name = f"reliable_avg_z_conf_filled_blurred_{threshold_token}.png"

        allowed = {
            # Direct FPGA comparison target: non-filled + final low-pass.
            "z_conf.png",
            "z_conf_nonfilled_blurred.png",

            # Future-work / dense-output targets: filled before and after low-pass.
            "z_conf_filled.png",
            "z_conf_filled_blurred.png",

            # Legacy/non-explicit raw fused output, useful for debugging only.
            "z_conf_raw.png",

            # Reliable visualisations.
            reliable_name,
            reliable_filled_name,
        }

        if lower in allowed:
            return True

        # Also crop any other reliable Z_conf visualisations generated by
        # bin_to_png.py, while still excluding per-axis intermediate outputs.
        if lower.startswith("reliable") and "z_conf" in lower:
            return True

        return False

    return False


# ------------------------------------------------------------
# Folder conversion
# ------------------------------------------------------------

def convert_folder_center_crop_to_png(
    in_dir: str,
    out_dir: str | None = None,
    expected_h: int = EXPECTED_H,
    expected_w: int = EXPECTED_W,
    crop_h: int = CROP_H,
    crop_w: int = CROP_W,
    folder_kind: str = "cross_raw",
):
    if out_dir is None:
        out_dir = in_dir.rstrip("/\\") + f"_center_{crop_h}x{crop_w}_png"

    if not os.path.isdir(in_dir):
        print(f"Skipping missing folder: {in_dir}")
        return None

    os.makedirs(out_dir, exist_ok=True)

    names = [
        name
        for name in os.listdir(in_dir)
        if should_crop_file(folder_kind, name)
    ]

    names.sort()

    if not names:
        print(f"No matching PNG files found in: {in_dir}")
        return out_dir

    for name in names:
        src = os.path.join(in_dir, name)
        base = os.path.splitext(name)[0]
        dst = os.path.join(out_dir, base + ".png")

        img = iio.imread(src)

        img_h = int(img.shape[0])
        img_w = int(img.shape[1])

        if img_h != expected_h or img_w != expected_w:
            raise ValueError(
                f"{src} has size {img_h}x{img_w}, expected {expected_h}x{expected_w}."
            )

        cropped = crop_center_image(
            img,
            crop_h=crop_h,
            crop_w=crop_w,
        )

        cropped = renormalise_after_crop_if_needed(
            cropped,
            source_path=src,
            output_path=dst,
        )

        iio.imwrite(dst, cropped)

    return out_dir


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

if __name__ == "__main__":
    folder_specs = [
        {
            "folder_name": "cross_raw_data_png",
            "folder_kind": "cross_raw",
        },
        {
            "folder_name": "confidence_png",
            "folder_kind": "confidence",
        },
        {
            "folder_name": "confidence_normalised_png",
            "folder_kind": "confidence",
        },
        {
            "folder_name": "disparity_png",
            "folder_kind": "disparity",
        },
        {
            "folder_name": "disparity_normalised_png",
            "folder_kind": "disparity",
        },
    ]

    print("Reliable confidence threshold:", RELIABLE_CONFIDENCE_THRESHOLD)
    print(
        "Reliable filename token:",
        threshold_to_filename_token(RELIABLE_CONFIDENCE_THRESHOLD),
    )

    for scene in SCENES:
        for spec in folder_specs:
            folder = os.path.join(
                ROOT,
                scene,
                spec["folder_name"],
            )

            out_png = convert_folder_center_crop_to_png(
                folder,
                folder_kind=spec["folder_kind"],
            )

            if out_png is not None:
                print("Wrote:", out_png)
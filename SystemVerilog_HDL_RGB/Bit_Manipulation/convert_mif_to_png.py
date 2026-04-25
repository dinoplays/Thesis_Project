"""
===============================================================================
LIGHT FIELD OUTPUT RECONSTRUCTOR (MIF outputs -> PNG reconstructions)
===============================================================================

This script reconstructs the top-level fused aligned output images

Main fixes in this version:
- Confidence visualisation now preserves Q8.7 granularity properly
- Robust confidence PNGs are computed from RAW Q8.7 values, not from already
  quantised 8-bit PNGs
- Confidence and fused-confidence now save both:
    * linear full-range PNG
    * robust 2-98 percentile PNG
- Disparity robust visualisation remains supported
- Code cleaned and commented throughout

===============================================================================
"""

import os
from PIL import Image


# -----------------------------------------------------------------------------
# CONFIG : Top-level reconstruction
# -----------------------------------------------------------------------------

TL_BASE_DIR = "SystemVerilog_HDL_RGB/Bit_Manipulation/tb/dino/output_data"

TL_SOLF_MIF = "SIM_SOLF_OUT.mif"
TL_EOLF_MIF = "SIM_EOLF_OUT.mif"
TL_VALID_MIF = "SIM_PIXEL_VALID_OUT.mif"
TL_ROW_IDX_MIF = "SIM_ROW_IDX_OUT.mif"
TL_COLUMN_IDX_MIF = "SIM_COLUMN_IDX_OUT.mif"
TL_CONF_PIXEL_MIF = "SIM_CONFIDENCE_PIXEL_BIT_DATA.mif"
TL_WEIGHTED_DISP_MIF = "SIM_WEIGHTED_DISPARITY_PIXEL_BIT_DATA.mif"


# -----------------------------------------------------------------------------
# COMMON CONFIG
# -----------------------------------------------------------------------------

# Output frame size
CROP_W = 64
CROP_H = 64

# Unsigned Q8.7 stored in 15 bits
PIX_WIDTH_BITS = 15

# Signed Q12.12 stored as 24-bit two's complement
FAO_DISP_WIDTH_BITS = 24
FAO_DISP_FRAC_BITS = 12

# Signed Q15.16 stored as 32-bit two's complement
DISP_FRAC_BITS = 16


# -----------------------------------------------------------------------------
# MIF PARSING HELPERS
# -----------------------------------------------------------------------------

def _read_depth_from_mif_header(path: str) -> int:
    """
    Read DEPTH=<N>; from a MIF header.

    Time complexity:
    - O(L), where L is the number of lines until DEPTH is found
    """
    with open(path, "r", encoding="utf-8") as file_obj:
        for line in file_obj:
            stripped = line.strip()
            if stripped.startswith("DEPTH=") and stripped.endswith(";"):
                try:
                    return int(stripped[len("DEPTH="):-1])
                except ValueError:
                    pass

    raise ValueError(f"Could not parse DEPTH from MIF header: {path}")


def _parse_content_bits_lines(path: str) -> dict[int, str]:
    """
    Parse the CONTENT BEGIN ... END; region of a MIF file.

    Returns:
    - dict mapping address -> raw bit string

    Time complexity:
    - O(L), where L is the total number of lines in the file
    """
    addr_to_bits = {}
    in_content = False

    with open(path, "r", encoding="utf-8") as file_obj:
        for raw_line in file_obj:
            stripped = raw_line.strip()

            if not in_content:
                if stripped == "CONTENT BEGIN":
                    in_content = True
                continue

            if stripped == "END;":
                break

            if ":" not in stripped or not stripped.endswith(";"):
                continue

            left, right = stripped[:-1].split(":", 1)
            left = left.strip()
            right = right.strip()

            try:
                addr = int(left)
            except ValueError:
                continue

            bits = right.replace(" ", "")
            addr_to_bits[addr] = bits

    return addr_to_bits


def load_mif_bits(path: str, width: int) -> list[int]:
    """
    Load a MIF as unsigned integers of a given width.

    Time complexity:
    - O(D), where D is the DEPTH of the MIF
    """
    depth = _read_depth_from_mif_header(path)
    addr_to_bits = _parse_content_bits_lines(path)

    out = [0] * depth

    for addr, bits in addr_to_bits.items():
        if 0 <= addr < depth:
            if len(bits) > width:
                bits_use = bits[-width:]
            elif len(bits) < width:
                bits_use = ("0" * (width - len(bits))) + bits
            else:
                bits_use = bits

            try:
                out[addr] = int(bits_use, 2)
            except ValueError:
                out[addr] = 0

    return out


def twos_complement_to_int(word: int, width: int) -> int:
    """
    Convert a width-bit two's complement integer into Python_Red int.

    Time complexity:
    - O(1)
    """
    sign_bit = 1 << (width - 1)
    full_mod = 1 << width

    if word & sign_bit:
        return word - full_mod

    return word


def load_mif_bits_signed(path: str, width: int) -> list[int]:
    """
    Load a MIF as signed two's complement integers.

    Time complexity:
    - O(D), where D is the DEPTH of the MIF
    """
    raw = load_mif_bits(path, width)
    return [twos_complement_to_int(value, width) for value in raw]


# -----------------------------------------------------------------------------
# FIXED-POINT HELPERS
# -----------------------------------------------------------------------------

def q15_16_s32_to_float(word32_signed: int) -> float:
    """
    Convert signed Q15.16 to float.

    Time complexity:
    - O(1)
    """
    return float(word32_signed) / float(1 << DISP_FRAC_BITS)


# -----------------------------------------------------------------------------
# GENERAL HELPERS
# -----------------------------------------------------------------------------

def _require_file(path: str) -> None:
    """
    Raise if a required file is missing.

    Time complexity:
    - O(1) for the Python_Red call itself; filesystem dependent in practice
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Missing required file: {path}")


# -----------------------------------------------------------------------------
# RAW U15 VISUALISATION HELPERS (USED FOR CONFIDENCE)
# -----------------------------------------------------------------------------

def _save_raw_u15_image_linear(
    img_matrix: list[list[int]],
    out_path: str
) -> tuple[float, float]:
    """
    Save unsigned 15-bit Q8.7 data with NO scaling.

    Mapping:
    - PNG bit[7:0] = raw_u15 bit[14:7]

    This means the PNG directly keeps the top 8 bits of the 15-bit word and
    drops the 7 fractional LSBs.

    Returns:
    - (min_float, max_float) in Q8.7 real units

    Time complexity:
    - O(H * W)
    """
    height = len(img_matrix)
    width = len(img_matrix[0]) if height > 0 else 0

    img = Image.new("L", (width, height), 0)

    min_val = None
    max_val = None

    for y_coord in range(height):
        for x_coord in range(width):
            raw_val = int(img_matrix[y_coord][x_coord]) & 0x7FFF

            if min_val is None or raw_val < min_val:
                min_val = raw_val
            if max_val is None or raw_val > max_val:
                max_val = raw_val

            pixel_val = (raw_val >> 7) & 0xFF
            img.putpixel((x_coord, y_coord), pixel_val)

    img.save(out_path)

    if min_val is None:
        return 0.0, 0.0

    return float(min_val) / 128.0, float(max_val) / 128.0


def _save_raw_u15_image_robust(
    img_matrix: list[list[int]],
    out_path: str,
    ignore_zero: bool = True
) -> tuple[float, float, float, float]:
    """
    Save unsigned 15-bit Q8.7 data using raw-domain robust 2..98 percentile
    normalisation.

    Important:
    - This computes percentiles from RAW Q8.7 values
    - It does NOT use an already-quantised 8-bit PNG as input

    Returns:
    - (min_float, max_float, p2_float, p98_float)

    Time complexity:
    - O(H * W) for array creation and output
    - percentile cost depends on numpy internals
    """
    import numpy as np

    arr = np.array(img_matrix, dtype=np.int32) & 0x7FFF

    if ignore_zero:
        valid_mask = (arr != 0)
    else:
        valid_mask = np.ones_like(arr, dtype=bool)

    valid_vals = arr[valid_mask]

    if valid_vals.size == 0:
        empty_img = Image.new("L", (arr.shape[1], arr.shape[0]), 0)
        empty_img.save(out_path)
        return 0.0, 0.0, 0.0, 0.0

    min_val = int(valid_vals.min())
    max_val = int(valid_vals.max())

    p2 = float(np.percentile(valid_vals, 2))
    p98 = float(np.percentile(valid_vals, 98))

    if p98 <= p2:
        p98 = p2 + 1.0

    clipped = np.clip(arr.astype(np.float32), p2, p98)
    norm = (clipped - p2) / (p98 - p2)
    norm_u8 = np.clip(np.round(norm * 255.0), 0, 255).astype(np.uint8)

    if ignore_zero:
        norm_u8[arr == 0] = 0

    out_img = Image.fromarray(norm_u8, mode="L")
    out_img.save(out_path)

    return (
        float(min_val) / 128.0,
        float(max_val) / 128.0,
        float(p2) / 128.0,
        float(p98) / 128.0,
    )


# -----------------------------------------------------------------------------
# SIGNED FIXED-POINT VISUALISATION HELPERS
# -----------------------------------------------------------------------------

def _save_signed_fixed_gray_png(
    img_matrix: list[list[int | None]],
    out_path: str,
    frac_bits: int,
    width_bits: int
) -> tuple[float, float]:
    """
    Save signed fixed-point values with NO scaling.

    Correct signed mapping:
    - interpret each value as signed
    - arithmetic right shift by frac_bits to keep the integer part
    - clamp to [0, 255] for PNG output

    Example:
    - signed Q12.12 in 24 bits:
        pixel = clamp(signed_value >> 12, 0, 255)

    This preserves signed ordering:
    - more negative / smaller values -> darker
    - larger positive values -> brighter

    The width_bits argument is kept for interface compatibility.

    Returns:
    - (min_float, max_float)

    Time complexity:
    - O(H * W)
    """
    height = len(img_matrix)
    width = len(img_matrix[0]) if height > 0 else 0

    values = []
    for y_coord in range(height):
        for x_coord in range(width):
            value = img_matrix[y_coord][x_coord]
            if value is not None:
                values.append(int(value))

    img = Image.new("L", (width, height), 0)

    if len(values) == 0:
        img.save(out_path)
        return 0.0, 0.0

    min_val = min(values)
    max_val = max(values)

    for y_coord in range(height):
        for x_coord in range(width):
            value = img_matrix[y_coord][x_coord]
            if value is None:
                continue

            signed_val = int(value)

            # Arithmetic shift keeps the signed integer part
            pixel_val = signed_val >> frac_bits

            # No scaling, only clamp to PNG range
            if pixel_val < 0:
                pixel_val = 0
            if pixel_val > 255:
                pixel_val = 255

            img.putpixel((x_coord, y_coord), pixel_val)

    img.save(out_path)

    return (
        float(min_val) / float(1 << frac_bits),
        float(max_val) / float(1 << frac_bits),
    )


def _save_signed_fixed_gray_png_robust_raw(
    img_matrix: list[list[int | None]],
    out_path: str,
    frac_bits: int,
    ignore_zero: bool = True
) -> tuple[float, float, float, float]:
    """
    Save signed fixed-point values using RAW-domain robust 2..98 percentile
    normalisation.

    Important:
    - This computes percentiles from the raw signed fixed-point values
    - It does NOT use an already-rendered 8-bit PNG as input
    - None entries are treated as invalid / unwritten pixels and remain black

    Returns:
    - (min_float, max_float, p2_float, p98_float)

    Time complexity:
    - O(H * W) for array creation and output
    - percentile cost depends on numpy internals
    """
    import numpy as np

    height = len(img_matrix)
    width = len(img_matrix[0]) if height > 0 else 0

    arr = np.zeros((height, width), dtype=np.int64)
    valid_mask = np.zeros((height, width), dtype=bool)

    for y_coord in range(height):
        for x_coord in range(width):
            value = img_matrix[y_coord][x_coord]
            if value is not None:
                arr[y_coord, x_coord] = int(value)
                valid_mask[y_coord, x_coord] = True

    if ignore_zero:
        stats_mask = valid_mask & (arr != 0)
    else:
        stats_mask = valid_mask

    valid_vals = arr[stats_mask]

    if valid_vals.size == 0:
        out_img = Image.new("L", (width, height), 0)
        out_img.save(out_path)
        return 0.0, 0.0, 0.0, 0.0

    min_val = int(valid_vals.min())
    max_val = int(valid_vals.max())

    p2 = float(np.percentile(valid_vals, 2))
    p98 = float(np.percentile(valid_vals, 98))

    if p98 <= p2:
        p98 = p2 + 1.0

    clipped = np.clip(arr.astype(np.float32), p2, p98)
    norm = (clipped - p2) / (p98 - p2)
    norm_u8 = np.clip(np.round(norm * 255.0), 0, 255).astype(np.uint8)

    norm_u8[~valid_mask] = 0

    out_img = Image.fromarray(norm_u8, mode="L")
    out_img.save(out_path)

    return (
        float(min_val) / float(1 << frac_bits),
        float(max_val) / float(1 << frac_bits),
        float(p2) / float(1 << frac_bits),
        float(p98) / float(1 << frac_bits),
    )


# -----------------------------------------------------------------------------
# TOP-LEVEL RECONSTRUCTION
# -----------------------------------------------------------------------------

def reconstruct_fused_aligned_output(
    base_dir: str,
    solf_mif: str,
    eolf_mif: str,
    valid_mif: str,
    row_mif: str,
    col_mif: str,
    conf_mif: str,
    wdisp_mif: str
) -> tuple[int, int, int, bool, bool, float, float, float, float]:
    """
    Reconstruct a fused aligned output image set.

    This function is used for both:
    - FAO_BASE_DIR
    - TL_BASE_DIR

    Saves:
    - fused_confidence.png              (top 8 bits of raw Q8.7, no scaling)
    - fused_confidence_robust.png       (raw-domain robust 2..98)
    - fused_weighted_disparity.png      (top 8 bits of raw fixed-point word, no scaling)
    - fused_weighted_disparity_robust.png

    Returns:
    - (
        valid_samples_seen,
        conf_pixels_written,
        disp_pixels_written,
        seen_solf,
        seen_eolf,
        disp_min,
        disp_max,
        conf_p2,
        conf_p98
      )

    Time complexity:
    - O(D), where D is the stream depth
    """
    p_solf = os.path.join(base_dir, solf_mif)
    p_eolf = os.path.join(base_dir, eolf_mif)
    p_valid = os.path.join(base_dir, valid_mif)
    p_row = os.path.join(base_dir, row_mif)
    p_col = os.path.join(base_dir, col_mif)
    p_conf = os.path.join(base_dir, conf_mif)
    p_wdisp = os.path.join(base_dir, wdisp_mif)

    _require_file(p_solf)
    _require_file(p_eolf)
    _require_file(p_valid)
    _require_file(p_row)
    _require_file(p_col)
    _require_file(p_conf)
    _require_file(p_wdisp)

    solf = load_mif_bits(p_solf, 1)
    eolf = load_mif_bits(p_eolf, 1)
    valid = load_mif_bits(p_valid, 1)
    row_idx = load_mif_bits(p_row, 7)
    col_idx = load_mif_bits(p_col, 7)
    conf_q = load_mif_bits(p_conf, PIX_WIDTH_BITS)
    wdisp_q = load_mif_bits_signed(p_wdisp, FAO_DISP_WIDTH_BITS)

    depth = len(valid)

    if len(solf) != depth or len(eolf) != depth or len(row_idx) != depth or len(col_idx) != depth:
        raise ValueError(f"Control/index MIF DEPTH mismatch in: {base_dir}")

    if len(conf_q) != depth or len(wdisp_q) != depth:
        raise ValueError(f"Pixel MIF DEPTH mismatch in: {base_dir}")

    conf_img_raw = [[0 for _ in range(CROP_W)] for _ in range(CROP_H)]
    disp_img = [[None for _ in range(CROP_W)] for _ in range(CROP_H)]

    valid_samples_seen = 0
    conf_pixels_written = 0
    disp_pixels_written = 0
    seen_solf = False
    seen_eolf = False

    for stream_idx in range(depth):
        if (solf[stream_idx] & 1) == 1:
            seen_solf = True

        if (valid[stream_idx] & 1) == 0:
            if (eolf[stream_idx] & 1) == 1:
                seen_eolf = True
                break
            continue

        valid_samples_seen += 1

        x_coord = col_idx[stream_idx] & 0x7F
        y_coord = row_idx[stream_idx] & 0x7F

        if not (0 <= x_coord < CROP_W and 0 <= y_coord < CROP_H):
            if (eolf[stream_idx] & 1) == 1:
                seen_eolf = True
                break
            continue

        conf15 = conf_q[stream_idx] & 0x7FFF
        conf_img_raw[y_coord][x_coord] = conf15
        conf_pixels_written += 1

        disp_img[y_coord][x_coord] = wdisp_q[stream_idx]
        disp_pixels_written += 1

        if (eolf[stream_idx] & 1) == 1:
            seen_eolf = True
            break

    _save_raw_u15_image_linear(
        conf_img_raw,
        os.path.join(base_dir, "fused_confidence.png")
    )

    _, _, conf_p2, conf_p98 = _save_raw_u15_image_robust(
        conf_img_raw,
        os.path.join(base_dir, "fused_confidence_robust.png"),
        ignore_zero=True
    )

    disp_min, disp_max = _save_signed_fixed_gray_png(
        disp_img,
        os.path.join(base_dir, "fused_weighted_disparity.png"),
        frac_bits=FAO_DISP_FRAC_BITS,
        width_bits=FAO_DISP_WIDTH_BITS
    )

    _save_signed_fixed_gray_png_robust_raw(
        disp_img,
        os.path.join(base_dir, "fused_weighted_disparity_robust.png"),
        frac_bits=FAO_DISP_FRAC_BITS,
        ignore_zero=True
    )

    return (
        valid_samples_seen,
        conf_pixels_written,
        disp_pixels_written,
        seen_solf,
        seen_eolf,
        disp_min,
        disp_max,
        conf_p2,
        conf_p98,
    )


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main() -> None:
    """
    Run top level reconstructions.

    Time complexity:
    - Dominated by the total size of all loaded MIF streams
    """
    print("Reconstructing top-level fused aligned output images ===")
    print("TL_BASE_DIR:", TL_BASE_DIR)

    try:
        (
            valid_samples_seen,
            conf_pixels_written,
            disp_pixels_written,
            seen_solf,
            seen_eolf,
            disp_min,
            disp_max,
            conf_p2,
            conf_p98,
        ) = reconstruct_fused_aligned_output(
            base_dir=TL_BASE_DIR,
            solf_mif=TL_SOLF_MIF,
            eolf_mif=TL_EOLF_MIF,
            valid_mif=TL_VALID_MIF,
            row_mif=TL_ROW_IDX_MIF,
            col_mif=TL_COLUMN_IDX_MIF,
            conf_mif=TL_CONF_PIXEL_MIF,
            wdisp_mif=TL_WEIGHTED_DISP_MIF
        )

        print("Done.")
        print("Seen SOLF:", seen_solf)
        print("Seen EOLF:", seen_eolf)
        print("Valid fused samples seen:", valid_samples_seen)
        print("Confidence pixels written:", conf_pixels_written)
        print("Weighted disparity pixels written:", disp_pixels_written)
        print("Weighted disparity range:", disp_min, "to", disp_max)
        print("Fused confidence robust p2..p98:", conf_p2, "to", conf_p98)

        expected_areas = [
            (CROP_W - 2) * (CROP_H - 2),
            (CROP_W - 4) * (CROP_H - 4),
            (CROP_W - 6) * (CROP_H - 6),
            (CROP_W - 8) * (CROP_H - 8),
        ]

        if conf_pixels_written not in expected_areas:
            print("WARNING: Unexpected confidence pixel count:", conf_pixels_written)

        if disp_pixels_written not in expected_areas:
            print("WARNING: Unexpected weighted disparity pixel count:", disp_pixels_written)

        print("Saved:", os.path.join(TL_BASE_DIR, "fused_confidence.png"))
        print("Saved:", os.path.join(TL_BASE_DIR, "fused_confidence_robust.png"))
        print("Saved:", os.path.join(TL_BASE_DIR, "fused_weighted_disparity.png"))
        print("Saved:", os.path.join(TL_BASE_DIR, "fused_weighted_disparity_robust.png"))

    except Exception as exc:
        print("ERROR converting top-level fused aligned output:", TL_BASE_DIR)
        print("Reason:", str(exc))

    print("\nAll conversions attempted.")


if __name__ == "__main__":
    main()
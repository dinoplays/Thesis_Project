"""
===============================================================================
LIGHT FIELD OUTPUT RECONSTRUCTOR (MIF outputs -> PNG reconstructions)
===============================================================================

This script reconstructs:
1) Filtered RGB frame outputs
2) EPI images
3) Confidence images
4) Disparity images
5) Fused aligned output images
6) Top-level fused aligned output images

Main fixes in this version:
- Updated for the reduced FPGA formats:
    * EPI pixels are 8-bit unsigned
    * confidence is 10-bit unsigned Q8.2
    * disparity and weighted disparity are 16-bit signed Q8.8
- Normalised confidence PNGs are computed from RAW Q8.2 values, not from already
  quantised 8-bit PNGs
- Confidence and fused-confidence save both:
    * linear full-range PNG
    * 0-100 min-max normalised PNG
- Disparity normalised visualisation uses signed Q8.8 raw values with inverse mapping: smaller nonzero disparity is white, larger disparity is black, and zero stays black
- Stage-specific output cropping is used: pre-final outputs use 5-pixel crop, final BSLPF/top-level outputs use 7-pixel crop
- Code cleaned and commented throughout

===============================================================================
"""

import os
from PIL import Image


# -----------------------------------------------------------------------------
# CONFIG : Top-level reconstruction
# -----------------------------------------------------------------------------

CAPTURES_PER_AXIS = 9

TL_BASE_DIR = "SystemVerilog_HDL_Red/Bit_Manipulation_Throttled/tb/output_data"

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
CROP_W = 128
CROP_H = 128

# Legacy filtered RGB path used Q8.7 stored in 15 bits.
# Kept only for Part 1 compatibility.
PIX_WIDTH_BITS = 15

# New EPIC path stores raw 8-bit pixels.
EPI_PIXEL_WIDTH_BITS = 8

# New confidence path uses unsigned Q8.2 stored in 10 bits.
CONF_WIDTH_BITS = 10
CONF_FRAC_BITS = 2

# EPI packed column width
EPI_COLUMN_WIDTH_BITS = CAPTURES_PER_AXIS * EPI_PIXEL_WIDTH_BITS

# New FAO / top-level weighted disparity uses signed Q8.8 in 16 bits.
FAO_DISP_WIDTH_BITS = 16
FAO_DISP_FRAC_BITS = 8

CAPTURE_ORDER = [
    "v_00.png", "v_01.png", "v_02.png", "v_03.png",
    "h_00.png", "h_01.png", "h_02.png", "h_03.png",
    "h_04.png", "h_05.png", "h_06.png", "h_07.png", "h_08.png",
    "v_05.png", "v_06.png", "v_07.png", "v_08.png",
]


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

def q8_7_u15_to_u8_integer_part(word15: int) -> int:
    """
    Convert unsigned Q8.7 into 8-bit by keeping only the integer part.

    This is okay for RGB frame reconstruction, because those values represent
    image intensity stored in Q8.7 and the original integer pixel value is
    the top 8 bits.

    Time complexity:
    - O(1)
    """
    return int((word15 >> 7) & 0xFF)


def fixed_signed_to_float(word_signed: int, frac_bits: int) -> float:
    """
    Convert a signed fixed-point integer to float.

    Time complexity:
    - O(1)
    """
    return float(word_signed) / float(1 << frac_bits)


def unsigned_fixed_to_u8_integer_part(word_unsigned: int, frac_bits: int) -> int:
    """
    Convert an unsigned fixed-point integer to an 8-bit display value by
    keeping the integer part and clamping to [0, 255].

    Time complexity:
    - O(1)
    """
    pixel_val = int(word_unsigned) >> frac_bits

    if pixel_val < 0:
        pixel_val = 0
    if pixel_val > 255:
        pixel_val = 255

    return pixel_val


# -----------------------------------------------------------------------------
# GENERAL HELPERS
# -----------------------------------------------------------------------------

def ensure_dir(path: str) -> None:
    """
    Create a directory if it does not already exist.

    Time complexity:
    - O(1) for the Python_Red call itself; filesystem dependent in practice
    """
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def _require_file(path: str) -> None:
    """
    Raise if a required file is missing.

    Time complexity:
    - O(1) for the Python_Red call itself; filesystem dependent in practice
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Missing required file: {path}")


# -----------------------------------------------------------------------------
# RAW UNSIGNED FIXED-POINT VISUALISATION HELPERS (USED FOR CONFIDENCE)
# -----------------------------------------------------------------------------

def _save_raw_unsigned_fixed_image_linear(
    img_matrix: list[list[int]],
    out_path: str,
    width_bits: int,
    frac_bits: int
) -> tuple[float, float]:
    """
    Save unsigned fixed-point data with NO contrast scaling.

    Mapping:
    - PNG value = clamp(raw_value >> frac_bits, 0, 255)

    For the current reduced design:
    - confidence is unsigned 10-bit Q8.2, so PNG = raw_q8_2 >> 2.

    Returns:
    - (min_float, max_float) in real fixed-point units

    Time complexity:
    - O(H * W)
    """
    height = len(img_matrix)
    width = len(img_matrix[0]) if height > 0 else 0

    mask = (1 << width_bits) - 1
    img = Image.new("L", (width, height), 0)

    min_val = None
    max_val = None

    for y_coord in range(height):
        for x_coord in range(width):
            raw_val = int(img_matrix[y_coord][x_coord]) & mask

            if min_val is None or raw_val < min_val:
                min_val = raw_val
            if max_val is None or raw_val > max_val:
                max_val = raw_val

            pixel_val = unsigned_fixed_to_u8_integer_part(raw_val, frac_bits)
            img.putpixel((x_coord, y_coord), pixel_val)

    img.save(out_path)

    if min_val is None:
        return 0.0, 0.0

    scale = float(1 << frac_bits)
    return float(min_val) / scale, float(max_val) / scale


def _save_raw_unsigned_fixed_image_normalised(
    img_matrix: list[list[int]],
    out_path: str,
    width_bits: int,
    frac_bits: int,
    ignore_zero: bool = True
) -> tuple[float, float, float, float]:
    """
    Save unsigned fixed-point data using RAW-domain 0..100 min-max
    normalisation.

    Important:
    - No 0..100 min-max clipping is used.
    - The minimum valid raw value maps to 0.
    - The maximum valid raw value maps to 255.
    - If ignore_zero=True, zero pixels are excluded from the min/max statistics
      and remain black in the output image.

    Returns:
    - (min_float, max_float, norm_min_float, norm_max_float)

    Time complexity:
    - O(H * W) for array creation and output
    """
    import numpy as np

    mask = (1 << width_bits) - 1
    arr = np.array(img_matrix, dtype=np.int32) & mask

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

    if max_val <= min_val:
        norm_u8 = np.zeros_like(arr, dtype=np.uint8)
    else:
        norm = (arr.astype(np.float32) - float(min_val)) / float(max_val - min_val)
        norm_u8 = np.clip(np.round(norm * 255.0), 0, 255).astype(np.uint8)

    if ignore_zero:
        norm_u8[arr == 0] = 0

    out_img = Image.fromarray(norm_u8, mode="L")
    out_img.save(out_path)

    scale = float(1 << frac_bits)
    return (
        float(min_val) / scale,
        float(max_val) / scale,
        float(min_val) / scale,
        float(max_val) / scale,
    )


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


def _save_signed_disparity_inverse_normalised_raw(
    img_matrix: list[list[int | None]],
    out_path: str,
    frac_bits: int,
    ignore_zero: bool = True
) -> tuple[float, float, float, float]:
    """
    Save signed fixed-point disparity using RAW-domain 0..100 min-max
    normalisation with inverse grayscale mapping.

    Required disparity display convention:
    - zero disparity is always black
    - smaller nonzero disparity -> whiter / closer
    - larger nonzero disparity -> blacker / farther

    Therefore, for all valid nonzero disparity values:
    - minimum valid nonzero raw value maps to 255
    - maximum valid nonzero raw value maps to 0

    None entries remain black.

    Returns:
    - (min_float, max_float, norm_min_float, norm_max_float)

    Time complexity:
    - O(H * W) for array creation and output
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

    norm_u8 = np.zeros((height, width), dtype=np.uint8)

    if max_val <= min_val:
        # Degenerate case: all valid nonzero disparity values are identical.
        # Display them as white, while zeros/invalid remain black.
        norm_u8[stats_mask] = 255
    else:
        # Direct normalisation gives min -> 0 and max -> 255.
        # Invert it so min -> 255 and max -> 0.
        norm = (arr.astype(np.float32) - float(min_val)) / float(max_val - min_val)
        inv_norm = 1.0 - norm
        norm_u8 = np.clip(np.round(inv_norm * 255.0), 0, 255).astype(np.uint8)

    norm_u8[~valid_mask] = 0
    if ignore_zero:
        norm_u8[arr == 0] = 0

    out_img = Image.fromarray(norm_u8, mode="L")
    out_img.save(out_path)

    scale = float(1 << frac_bits)
    return (
        float(min_val) / scale,
        float(max_val) / scale,
        float(min_val) / scale,
        float(max_val) / scale,
    )


# -----------------------------------------------------------------------------
# TOP-LEVEL RECONSTRUCTION
# -----------------------------------------------------------------------------

def crop_edges_2d(img_matrix, edge=5):
    """
    Remove `edge` pixels from all 4 sides of a 2D list image.

    Time complexity:
    - O(H * W)
    """
    if edge <= 0:
        return img_matrix

    h = len(img_matrix)
    w = len(img_matrix[0]) if h > 0 else 0

    if h <= 2 * edge or w <= 2 * edge:
        raise ValueError("Crop too large for image size")

    return [
        row[edge:w - edge]
        for row in img_matrix[edge:h - edge]
    ]

def reconstruct_fused_aligned_output(
    base_dir: str,
    solf_mif: str,
    eolf_mif: str,
    valid_mif: str,
    row_mif: str,
    col_mif: str,
    conf_mif: str,
    wdisp_mif: str,
    crop_edge: int = 5
) -> tuple[int, int, int, bool, bool, float, float, float, float]:
    """
    Reconstruct a fused aligned output image set.

    This function is used for both:
    - FAO_BASE_DIR
    - TL_BASE_DIR

    Saves:
    - fused_confidence.png              (top 8 bits of raw Q8.2, no scaling)
    - fused_confidence_normalised.png       (raw-domain 0..100 min-max)
    - fused_weighted_disparity.png      (integer part of raw signed Q8.8 word, no scaling)
    - fused_weighted_disparity_normalised.png

    crop_edge:
    - Use 5 for pre-final FAO-like outputs.
    - Use 7 for final BSLPF/top-level outputs because the input region is
      already 4..123 and the 7x7 kernel removes another 3 pixels per side,
      so the valid output region is 7..120.

    Returns:
    - (
        valid_samples_seen,
        conf_pixels_written,
        disp_pixels_written,
        seen_solf,
        seen_eolf,
        disp_min,
        disp_max,
        conf_min_norm,
        conf_max_norm
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
    conf_q = load_mif_bits(p_conf, CONF_WIDTH_BITS)
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

        conf10 = conf_q[stream_idx] & 0x3FF
        conf_img_raw[y_coord][x_coord] = conf10
        conf_pixels_written += 1

        disp_img[y_coord][x_coord] = wdisp_q[stream_idx]
        disp_pixels_written += 1

        if (eolf[stream_idx] & 1) == 1:
            seen_eolf = True
            break

    # APPLY STAGE-SPECIFIC CROP
    conf_img_raw = crop_edges_2d(conf_img_raw, crop_edge)
    disp_img = crop_edges_2d(disp_img, crop_edge)

    _save_raw_unsigned_fixed_image_linear(
        conf_img_raw,
        os.path.join(base_dir, "fused_confidence.png"),
        width_bits=CONF_WIDTH_BITS,
        frac_bits=CONF_FRAC_BITS
    )

    _, _, conf_min_norm, conf_max_norm = _save_raw_unsigned_fixed_image_normalised(
        conf_img_raw,
        os.path.join(base_dir, "fused_confidence_normalised.png"),
        width_bits=CONF_WIDTH_BITS,
        frac_bits=CONF_FRAC_BITS,
        ignore_zero=True
    )

    disp_min, disp_max = _save_signed_fixed_gray_png(
        disp_img,
        os.path.join(base_dir, "fused_weighted_disparity.png"),
        frac_bits=FAO_DISP_FRAC_BITS,
        width_bits=FAO_DISP_WIDTH_BITS
    )

    _save_signed_disparity_inverse_normalised_raw(
        disp_img,
        os.path.join(base_dir, "fused_weighted_disparity_normalised.png"),
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
        conf_min_norm,
        conf_max_norm,
    )


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main() -> None:
    """
    Run all reconstructions.

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
            conf_min_norm,
            conf_max_norm,
        ) = reconstruct_fused_aligned_output(
            base_dir=TL_BASE_DIR,
            solf_mif=TL_SOLF_MIF,
            eolf_mif=TL_EOLF_MIF,
            valid_mif=TL_VALID_MIF,
            row_mif=TL_ROW_IDX_MIF,
            col_mif=TL_COLUMN_IDX_MIF,
            conf_mif=TL_CONF_PIXEL_MIF,
            wdisp_mif=TL_WEIGHTED_DISP_MIF,
            crop_edge=7
        )

        print("Done.")
        print("Seen SOLF:", seen_solf)
        print("Seen EOLF:", seen_eolf)
        print("Valid fused samples seen:", valid_samples_seen)
        print("Confidence pixels written:", conf_pixels_written)
        print("Weighted disparity pixels written:", disp_pixels_written)
        print("Weighted disparity range:", disp_min, "to", disp_max)
        print("Fused confidence normalised min..max:", conf_min_norm, "to", conf_max_norm)

        expected_areas = [
            (CROP_W - 14) * (CROP_H - 14),
        ]

        if conf_pixels_written not in expected_areas:
            print("WARNING: Unexpected confidence pixel count:", conf_pixels_written)

        if disp_pixels_written not in expected_areas:
            print("WARNING: Unexpected weighted disparity pixel count:", disp_pixels_written)

        print("Saved:", os.path.join(TL_BASE_DIR, "fused_confidence.png"))
        print("Saved:", os.path.join(TL_BASE_DIR, "fused_confidence_normalised.png"))
        print("Saved:", os.path.join(TL_BASE_DIR, "fused_weighted_disparity.png"))
        print("Saved:", os.path.join(TL_BASE_DIR, "fused_weighted_disparity_normalised.png"))

    except Exception as exc:
        print("ERROR converting top-level fused aligned output:", TL_BASE_DIR)
        print("Reason:", str(exc))

    print("\nAll conversions attempted.")


if __name__ == "__main__":
    main()
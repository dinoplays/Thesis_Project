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

Note: FPGA reconstruction has no region-filling stage, so these outputs should
be compared against the Python non-filled blurred output.

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
- Disparity visualisation subtracts 1.0 from the signed Q8.8 raw value before applying the inverse mapping: negative displayed disparity is black, zero displayed disparity is white, and larger positive displayed disparity fades toward black
- Stage-specific output cropping is used: pre-final outputs use 5-pixel crop, final BSLPF/top-level outputs use 7-pixel crop
- Code cleaned and commented throughout

===============================================================================
"""

import os
from PIL import Image


# -----------------------------------------------------------------------------
# CONFIG : Part 1 frame reconstruction
# -----------------------------------------------------------------------------

BASE_DIR = "SystemVerilog_HDL_Red/Bit_Manipulation/tb/bslpf/output_data"

OUT_VALID_MIF = "SIM_PIXEL_VALID_OUT.mif"
OUT_SOC_MIF = "SIM_SOC_OUT.mif"
OUT_EOC_MIF = "SIM_EOC_OUT.mif"
OUT_SOLF_MIF = "SIM_SOLF_OUT.mif"
OUT_EOLF_MIF = "SIM_EOLF_OUT.mif"

OUT_RED_MIF = "SIM_PIXEL_OUT_RED.mif"
OUT_GREEN_MIF = "SIM_PIXEL_OUT_GREEN.mif"
OUT_BLUE_MIF = "SIM_PIXEL_OUT_BLUE.mif"


# -----------------------------------------------------------------------------
# CONFIG : Part 2 EPI reconstruction
# -----------------------------------------------------------------------------

EPI_BASE_DIR = "SystemVerilog_HDL_Red/Bit_Manipulation/tb/epic/output_data"

EPI_CHANNEL_SUBDIRS = [
    "red",
    "green",
    "blue",
]

EPI_VALID_MIF = "SIM_EPI_VALID_OUT.mif"
EPI_COLUMN_IDX_MIF = "SIM_EPI_COLUMN_IDX_OUT.mif"
EPI_IDX_MIF = "SIM_EPI_IDX_OUT.mif"
EPI_ORIENTATION_MIF = "SIM_ORIENTATION_OUT.mif"
EPI_COLUMN_OUT_PREFIX = "SIM_EPI_COLUMN_OUT_"

CAPTURES_PER_AXIS = 9


# -----------------------------------------------------------------------------
# CONFIG : Part 3 confidence reconstruction
# -----------------------------------------------------------------------------

CONF_BASE_DIR = "SystemVerilog_HDL_Red/Bit_Manipulation/tb/conf_comp/output_data"

CONF_VALID_MIF = "SIM_CONF_VALID_OUT.mif"
CONF_ROW_IDX_MIF = "SIM_CONF_ROW_IDX_OUT.mif"
CONF_COLUMN_IDX_MIF = "SIM_CONF_COLUMN_IDX_OUT.mif"
CONF_ORIENTATION_MIF = "SIM_CONF_ORIENTATION_OUT.mif"
CONF_PIXEL_MIF = "SIM_CONF_PIXEL_OUT.mif"


# -----------------------------------------------------------------------------
# CONFIG : Part 4 disparity reconstruction
# -----------------------------------------------------------------------------

DISP_BASE_DIR = "SystemVerilog_HDL_Red/Bit_Manipulation/tb/disp_est/output_data"

DISP_VALID_MIF = "SIM_DISP_VALID_OUT.mif"
DISP_ROW_IDX_MIF = "SIM_DISP_ROW_IDX_OUT.mif"
DISP_COLUMN_IDX_MIF = "SIM_DISP_COLUMN_IDX_OUT.mif"
DISP_ORIENTATION_MIF = "SIM_DISP_ORIENTATION_OUT.mif"
DISP_PIXEL_MIF = "SIM_DISP_PIXEL_OUT.mif"

# Signed Q8.8 stored as 16-bit two's complement
DISP_WIDTH_BITS = 16
DISP_FRAC_BITS = 8


# -----------------------------------------------------------------------------
# CONFIG : Part 5 FAO reconstruction
# -----------------------------------------------------------------------------

FAO_BASE_DIR = "SystemVerilog_HDL_Red/Bit_Manipulation/tb/fao/output_data"

FAO_SOLF_MIF = "SIM_SOLF_OUT.mif"
FAO_EOLF_MIF = "SIM_EOLF_OUT.mif"
FAO_VALID_MIF = "SIM_PIXEL_VALID_OUT.mif"
FAO_ROW_IDX_MIF = "SIM_ROW_IDX_OUT.mif"
FAO_COLUMN_IDX_MIF = "SIM_COLUMN_IDX_OUT.mif"
FAO_CONF_PIXEL_MIF = "SIM_CONFIDENCE_PIXEL_BIT_DATA.mif"
FAO_WEIGHTED_DISP_MIF = "SIM_WEIGHTED_DISPARITY_PIXEL_BIT_DATA.mif"


# -----------------------------------------------------------------------------
# CONFIG : Part 6 top-level reconstruction
# -----------------------------------------------------------------------------

TL_BASE_DIR = "SystemVerilog_HDL_Red/Bit_Manipulation/tb/output_data"

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

# Display-only offset for disparity PNG visualisation.
# The stored FPGA value represents 1 + ratio. For display, show ratio by
# subtracting 1.0 before applying the negative/zero/positive convention.
# This does NOT modify the raw MIF values or reported raw numeric ranges.
DISPARITY_DISPLAY_OFFSET = 1.0

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


def q15_16_s32_to_float(word32_signed: int) -> float:
    """
    Convert signed Q15.16 to float.

    Time complexity:
    - O(1)
    """
    return float(word32_signed) / float(1 << DISP_FRAC_BITS)


def q12_12_s24_to_float(word24_signed: int) -> float:
    """
    Convert signed Q12.12 to float.

    Time complexity:
    - O(1)
    """
    return float(word24_signed) / float(1 << FAO_DISP_FRAC_BITS)


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


def _save_frame_png(frame_pixels: list[tuple[int, int, int]], out_path: str) -> None:
    """
    Save an RGB frame from a flat list of pixels.

    Time complexity:
    - O(CROP_W * CROP_H)
    """
    img = Image.new("RGB", (CROP_W, CROP_H), (0, 0, 0))
    num_pixels = min(len(frame_pixels), CROP_W * CROP_H)

    pixel_idx = 0
    for y_coord in range(CROP_H):
        for x_coord in range(CROP_W):
            if pixel_idx < num_pixels:
                img.putpixel((x_coord, y_coord), frame_pixels[pixel_idx])
            pixel_idx += 1

    img.save(out_path)


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


def _save_raw_u15_image_normalised(
    img_matrix: list[list[int]],
    out_path: str,
    ignore_zero: bool = True
) -> tuple[float, float, float, float]:
    """
    Save unsigned 15-bit Q8.7 data using RAW-domain 0..100 min-max
    normalisation.

    Important:
    - No 0..100 min-max clipping is used.
    - The minimum valid raw value maps to 0.
    - The maximum valid raw value maps to 255.

    Returns:
    - (min_float, max_float, norm_min_float, norm_max_float)

    Time complexity:
    - O(H * W) for array creation and output
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

    if max_val <= min_val:
        norm_u8 = np.zeros_like(arr, dtype=np.uint8)
    else:
        norm = (arr.astype(np.float32) - float(min_val)) / float(max_val - min_val)
        norm_u8 = np.clip(np.round(norm * 255.0), 0, 255).astype(np.uint8)

    if ignore_zero:
        norm_u8[arr == 0] = 0

    out_img = Image.fromarray(norm_u8, mode="L")
    out_img.save(out_path)

    return (
        float(min_val) / 128.0,
        float(max_val) / 128.0,
        float(min_val) / 128.0,
        float(max_val) / 128.0,
    )


def _save_signed_disparity_png(
    img_matrix: list[list[int | None]],
    out_path: str
) -> tuple[float, float]:
    """
    Save signed Q8.8 disparity with NO scaling.

    Correct signed mapping:
    - interpret each value as signed
    - arithmetic right shift by DISP_FRAC_BITS to keep the integer part
    - clamp to [0, 255] for PNG output

    This preserves signed ordering:
    - more negative / smaller values -> darker
    - larger positive values -> brighter

    Returns:
    - (min_disp_float, max_disp_float)

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

            # Display only: subtract the 1.0 inverse-depth/disparity baseline.
            # The raw stored value is left unchanged; only the PNG uses this offset.
            signed_val = int(value) - int(round(DISPARITY_DISPLAY_OFFSET * (1 << DISP_FRAC_BITS)))

            # Arithmetic shift keeps the signed integer part of Q8.8
            pixel_val = signed_val >> DISP_FRAC_BITS

            # No scaling, only clamp to PNG range
            if pixel_val < 0:
                pixel_val = 0
            if pixel_val > 255:
                pixel_val = 255

            img.putpixel((x_coord, y_coord), pixel_val)

    img.save(out_path)
    return fixed_signed_to_float(min_val, DISP_FRAC_BITS), fixed_signed_to_float(max_val, DISP_FRAC_BITS)


def _save_signed_fixed_gray_png(
    img_matrix: list[list[int | None]],
    out_path: str,
    frac_bits: int,
    width_bits: int,
    display_offset_real: float = 0.0,
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

    If display_offset_real is non-zero, it is subtracted from each value for
    PNG visualisation only. Raw min/max return values are still based on the
    stored values.

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

            # Display only: optionally subtract a real-valued baseline before
            # converting to an 8-bit PNG.
            signed_val = int(value) - int(round(float(display_offset_real) * float(1 << frac_bits)))

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


def _save_signed_fixed_gray_png_normalised_raw(
    img_matrix: list[list[int | None]],
    out_path: str,
    frac_bits: int,
    ignore_zero: bool = True
) -> tuple[float, float, float, float]:
    """
    Save signed fixed-point values using RAW-domain 0..100 min-max
    normalisation with the conventional direct grayscale mapping.

    Mapping:
    - minimum valid raw value -> black
    - maximum valid raw value -> white
    - None entries remain black
    - if ignore_zero=True, zero entries are excluded from the min/max statistics
      and remain black

    This helper is kept for non-disparity signed fixed-point outputs.

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

    if max_val <= min_val:
        norm_u8 = np.zeros((height, width), dtype=np.uint8)
    else:
        norm = (arr.astype(np.float32) - float(min_val)) / float(max_val - min_val)
        norm_u8 = np.clip(np.round(norm * 255.0), 0, 255).astype(np.uint8)

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


def _save_signed_disparity_inverse_normalised_raw(
    img_matrix: list[list[int | None]],
    out_path: str,
    frac_bits: int,
    ignore_zero: bool = True
) -> tuple[float, float, float, float]:
    """
    Save signed fixed-point disparity using RAW-domain min-max normalisation with
    the intended inverse depth-like grayscale mapping.

    Display-only convention:
    - the stored value represents 1 + ratio
    - before visualisation, 1.0 is subtracted so the displayed value represents
      the ratio relative to the baseline

    Required disparity display convention:
    - invalid / None entries remain black
    - negative disparity values are black
    - zero disparity is white
    - small positive disparity is close to white
    - larger positive disparity becomes darker, with the largest positive value black

    Therefore, only strictly positive disparity values are used for the
    normalisation statistics:
    - minimum positive raw value maps near 255
    - maximum positive raw value maps to 0

    The ignore_zero argument is kept for interface compatibility. In this
    disparity visualisation, zero is always displayed as white and is not used
    for the positive-value normalisation range.

    Returns:
    - (min_float, max_float, norm_min_float, norm_max_float), where the min/max
      values refer to the positive disparity range used for normalisation.

    Time complexity:
    - O(H * W) for array creation and output
    """
    import numpy as np

    height = len(img_matrix)
    width = len(img_matrix[0]) if height > 0 else 0

    arr = np.zeros((height, width), dtype=np.int64)
    valid_mask = np.zeros((height, width), dtype=bool)
    display_offset_raw = int(round(DISPARITY_DISPLAY_OFFSET * float(1 << frac_bits)))

    for y_coord in range(height):
        for x_coord in range(width):
            value = img_matrix[y_coord][x_coord]
            if value is not None:
                # Store the display-domain value only in arr. The source
                # img_matrix is untouched, so this is a PNG-only convention.
                arr[y_coord, x_coord] = int(value) - display_offset_raw
                valid_mask[y_coord, x_coord] = True

    negative_mask = valid_mask & (arr < 0)
    zero_mask = valid_mask & (arr == 0)
    positive_mask = valid_mask & (arr > 0)

    norm_u8 = np.zeros((height, width), dtype=np.uint8)

    # Zero disparity is the nearest/brightest visual value.
    norm_u8[zero_mask] = 255

    positive_vals = arr[positive_mask]

    if positive_vals.size == 0:
        # No positive range exists. Negative and invalid remain black; zeros
        # have already been set to white.
        out_img = Image.fromarray(norm_u8, mode="L")
        out_img.save(out_path)
        return 0.0, 0.0, 0.0, 0.0

    min_val = int(positive_vals.min())
    max_val = int(positive_vals.max())

    if max_val <= min_val:
        # Degenerate case: every positive disparity is the same. Treat all
        # positive values as just above zero, so they remain white.
        norm_u8[positive_mask] = 255
    else:
        # Positive disparity convention:
        #   small positive -> white
        #   large positive -> black
        norm = (arr.astype(np.float32) - float(min_val)) / float(max_val - min_val)
        inv_norm = 1.0 - norm
        positive_u8 = np.clip(np.round(inv_norm * 255.0), 0, 255).astype(np.uint8)
        norm_u8[positive_mask] = positive_u8[positive_mask]

    # Negative and invalid values remain black because norm_u8 was initialised
    # to zero. This line is explicit for readability.
    norm_u8[negative_mask] = 0
    norm_u8[~valid_mask] = 0

    out_img = Image.fromarray(norm_u8, mode="L")
    out_img.save(out_path)

    scale = float(1 << frac_bits)
    return (
        float(min_val) / scale,
        float(max_val) / scale,
        float(min_val) / scale,
        float(max_val) / scale,
    )

def reconstruct_one_dir(in_dir: str, out_dir: str) -> tuple[bool, int]:
    """
    Reconstruct RGB frames from one filter output directory.

    Returns:
    - (seen_solf, frames_saved)

    Time complexity:
    - O(D), where D is the stream depth
    """
    ensure_dir(out_dir)

    p_valid = os.path.join(in_dir, OUT_VALID_MIF)
    p_soc = os.path.join(in_dir, OUT_SOC_MIF)
    p_eoc = os.path.join(in_dir, OUT_EOC_MIF)
    p_solf = os.path.join(in_dir, OUT_SOLF_MIF)
    p_eolf = os.path.join(in_dir, OUT_EOLF_MIF)
    p_r = os.path.join(in_dir, OUT_RED_MIF)
    p_g = os.path.join(in_dir, OUT_GREEN_MIF)
    p_b = os.path.join(in_dir, OUT_BLUE_MIF)

    _require_file(p_valid)
    _require_file(p_soc)
    _require_file(p_eoc)
    _require_file(p_solf)
    _require_file(p_eolf)
    _require_file(p_r)
    _require_file(p_g)
    _require_file(p_b)

    valid = load_mif_bits(p_valid, 1)
    soc = load_mif_bits(p_soc, 1)
    eoc = load_mif_bits(p_eoc, 1)
    solf = load_mif_bits(p_solf, 1)
    eolf = load_mif_bits(p_eolf, 1)

    r_q = load_mif_bits(p_r, PIX_WIDTH_BITS)
    g_q = load_mif_bits(p_g, PIX_WIDTH_BITS)
    b_q = load_mif_bits(p_b, PIX_WIDTH_BITS)

    depth = len(valid)

    if len(soc) != depth or len(eoc) != depth or len(solf) != depth or len(eolf) != depth:
        raise ValueError(f"Flag MIF DEPTH mismatch in: {in_dir}")

    if len(r_q) != depth or len(g_q) != depth or len(b_q) != depth:
        raise ValueError(f"Pixel MIF DEPTH mismatch in: {in_dir}")

    pixels_per_frame = CROP_W * CROP_H

    frames_saved = 0
    capture_index = -1
    frame_pixels = []
    seen_solf = False

    for stream_idx in range(depth):
        valid_bit = valid[stream_idx] & 1
        soc_bit = soc[stream_idx] & 1
        eoc_bit = eoc[stream_idx] & 1
        solf_bit = solf[stream_idx] & 1
        eolf_bit = eolf[stream_idx] & 1

        if valid_bit == 1:
            if solf_bit == 1:
                seen_solf = True

            if soc_bit == 1:
                if len(frame_pixels) != 0:
                    debug_name = f"debug_partial_{frames_saved:02d}.png"
                    _save_frame_png(frame_pixels, os.path.join(out_dir, debug_name))
                    frame_pixels = []

                capture_index += 1

            r15 = r_q[stream_idx] & 0x7FFF
            g15 = g_q[stream_idx] & 0x7FFF
            b15 = b_q[stream_idx] & 0x7FFF

            r8 = q8_7_u15_to_u8_integer_part(r15)
            g8 = q8_7_u15_to_u8_integer_part(g15)
            b8 = q8_7_u15_to_u8_integer_part(b15)

            frame_pixels.append((r8, g8, b8))

            if eoc_bit == 1:
                if len(frame_pixels) != pixels_per_frame:
                    print(
                        f"WARNING: {in_dir} frame {capture_index} ended with "
                        f"{len(frame_pixels)} valid pixels (expected {pixels_per_frame}). "
                        f"Saving anyway."
                    )

                if 0 <= capture_index < len(CAPTURE_ORDER):
                    out_name = CAPTURE_ORDER[capture_index]
                else:
                    out_name = f"capture_{capture_index:02d}.png"

                _save_frame_png(frame_pixels, os.path.join(out_dir, out_name))
                frames_saved += 1
                frame_pixels = []

            if eolf_bit == 1:
                break

    return seen_solf, frames_saved


# -----------------------------------------------------------------------------
# PART 2 : EPI RECONSTRUCTION
# -----------------------------------------------------------------------------

def _save_epi_gray_png(
    epi_columns: dict[int, list[int]],
    out_path: str,
    width: int,
    height: int
) -> None:
    """
    Save one EPI image from a dictionary:
      column_idx -> list of CAPTURES_PER_AXIS grayscale pixels

    Time complexity:
    - O(width * height) in the worst case
    """
    img = Image.new("L", (width, height), 0)

    for x_coord, col_pixels in epi_columns.items():
        if x_coord < 0 or x_coord >= width:
            continue

        for y_coord in range(min(height, len(col_pixels))):
            img.putpixel((x_coord, y_coord), int(col_pixels[y_coord]))

    img.save(out_path)


def reconstruct_epi_one_channel(channel_dir: str) -> tuple[int, int]:
    """
    Reconstruct the requested EPI images for one channel folder.

    Only the following EPI indices are saved:
    - first
    - middle-1
    - middle
    - last

    Returns:
    - (epis_saved, valid_samples_seen)

    Time complexity:
    - O(D), where D is the stream depth
    """
    ensure_dir(channel_dir)

    p_valid = os.path.join(channel_dir, EPI_VALID_MIF)
    p_col_idx = os.path.join(channel_dir, EPI_COLUMN_IDX_MIF)
    p_epi_idx = os.path.join(channel_dir, EPI_IDX_MIF)
    p_orientation = os.path.join(channel_dir, EPI_ORIENTATION_MIF)

    _require_file(p_valid)
    _require_file(p_col_idx)
    _require_file(p_epi_idx)
    _require_file(p_orientation)

    p_col_files = []
    for k_idx in range(CAPTURES_PER_AXIS):
        p_col_files.append(os.path.join(channel_dir, f"{EPI_COLUMN_OUT_PREFIX}{k_idx}.mif"))

    for path in p_col_files:
        _require_file(path)

    valid = load_mif_bits(p_valid, 1)
    col_idx_out = load_mif_bits(p_col_idx, 7)
    epi_idx_out = load_mif_bits(p_epi_idx, 7)
    orientation = load_mif_bits(p_orientation, 1)
    col_out_list = [load_mif_bits(path, EPI_PIXEL_WIDTH_BITS) for path in p_col_files]

    depth = len(valid)

    if len(col_idx_out) != depth or len(epi_idx_out) != depth or len(orientation) != depth:
        raise ValueError(f"EPI index/orientation MIF DEPTH mismatch in: {channel_dir}")

    for column_idx, col_stream in enumerate(col_out_list):
        if len(col_stream) != depth:
            raise ValueError(
                f"EPI column MIF DEPTH mismatch for column {column_idx} in: {channel_dir}"
            )

    first_idx = 0
    mid0_idx = (CROP_H // 2) - 1
    mid1_idx = (CROP_H // 2)
    last_idx = CROP_H - 1

    wanted_epi_idxs = [first_idx, mid0_idx, mid1_idx, last_idx]
    wanted_epi_set = set(wanted_epi_idxs)

    epi_store = {}
    valid_samples_seen = 0

    for stream_idx in range(depth):
        if (valid[stream_idx] & 1) == 0:
            continue

        valid_samples_seen += 1

        ori = orientation[stream_idx] & 1
        epi_idx = epi_idx_out[stream_idx] & 0x7F
        col_idx = col_idx_out[stream_idx] & 0x7F

        if epi_idx not in wanted_epi_set:
            continue

        if ori == 0:
            if not (0 <= col_idx < CROP_W):
                continue
        else:
            if not (0 <= col_idx < CROP_H):
                continue

        pixels_u8 = []
        for k_idx in range(CAPTURES_PER_AXIS):
            px8 = col_out_list[k_idx][stream_idx] & 0xFF
            pixels_u8.append(px8)

        key = (ori, epi_idx)
        if key not in epi_store:
            epi_store[key] = {}

        epi_store[key][col_idx] = pixels_u8

    epis_saved = 0

    for epi_idx in wanted_epi_idxs:
        h_key = (0, epi_idx)
        if h_key in epi_store:
            out_name = f"h_epi_{epi_idx:03d}.png"
            _save_epi_gray_png(
                epi_store[h_key],
                os.path.join(channel_dir, out_name),
                width=CROP_W,
                height=CAPTURES_PER_AXIS
            )
            epis_saved += 1

        v_key = (1, epi_idx)
        if v_key in epi_store:
            out_name = f"v_epi_{epi_idx:03d}.png"
            _save_epi_gray_png(
                epi_store[v_key],
                os.path.join(channel_dir, out_name),
                width=CROP_H,
                height=CAPTURES_PER_AXIS
            )
            epis_saved += 1

    return epis_saved, valid_samples_seen


# -----------------------------------------------------------------------------
# PART 3 : CONFIDENCE RECONSTRUCTION
# -----------------------------------------------------------------------------

def reconstruct_confidence_images(
    conf_dir: str
) -> tuple[int, int, int, float, float, float, float, float, float, float, float]:
    """
    Reconstruct confidence images.

    Important:
    - confidence is unsigned Q8.2 in 10 bits
    - we preserve RAW Q8.2 granularity in the saved visualisations

    Saves:
    - confidence_horizontal.png              (linear full-range from raw Q8.2)
    - confidence_vertical.png                (linear full-range from raw Q8.2)
    - confidence_horizontal_normalised.png       (raw-domain 0..100 min-max)
    - confidence_vertical_normalised.png         (raw-domain 0..100 min-max)

    Returns:
    - (
        valid_samples_seen,
        h_pixels_written,
        v_pixels_written,
        h_min, h_max,
        v_min, v_max,
        h_min_norm, h_max_norm,
        v_min_norm, v_max_norm
      )

    Time complexity:
    - O(D), where D is the stream depth
    """
    p_valid = os.path.join(conf_dir, CONF_VALID_MIF)
    p_row_idx = os.path.join(conf_dir, CONF_ROW_IDX_MIF)
    p_col_idx = os.path.join(conf_dir, CONF_COLUMN_IDX_MIF)
    p_orientation = os.path.join(conf_dir, CONF_ORIENTATION_MIF)
    p_conf = os.path.join(conf_dir, CONF_PIXEL_MIF)

    _require_file(p_valid)
    _require_file(p_row_idx)
    _require_file(p_col_idx)
    _require_file(p_orientation)
    _require_file(p_conf)

    valid = load_mif_bits(p_valid, 1)
    row_idx_out = load_mif_bits(p_row_idx, 7)
    col_idx_out = load_mif_bits(p_col_idx, 7)
    orientation = load_mif_bits(p_orientation, 1)
    conf_out = load_mif_bits(p_conf, CONF_WIDTH_BITS)

    depth = len(valid)

    if len(row_idx_out) != depth or len(col_idx_out) != depth or len(orientation) != depth or len(conf_out) != depth:
        raise ValueError(f"Confidence MIF DEPTH mismatch in: {conf_dir}")

    # Store RAW Q8.2 u15 values here, not pre-quantised 8-bit display values.
    h_img_raw = [[0 for _ in range(CROP_W)] for _ in range(CROP_H)]
    v_img_raw = [[0 for _ in range(CROP_W)] for _ in range(CROP_H)]

    valid_samples_seen = 0
    h_pixels_written = 0
    v_pixels_written = 0

    for stream_idx in range(depth):
        if (valid[stream_idx] & 1) == 0:
            continue

        valid_samples_seen += 1

        ori = orientation[stream_idx] & 1
        row_idx = row_idx_out[stream_idx] & 0x7F
        col_idx = col_idx_out[stream_idx] & 0x7F
        conf10 = conf_out[stream_idx] & 0x3FF

        x_coord = col_idx
        y_coord = row_idx

        if not (0 <= x_coord < CROP_W and 0 <= y_coord < CROP_H):
            continue

        if ori == 0:
            h_img_raw[y_coord][x_coord] = conf10
            h_pixels_written += 1
        else:
            v_img_raw[y_coord][x_coord] = conf10
            v_pixels_written += 1

    # APPLY CROP
    h_img_raw = crop_edges_2d(h_img_raw, 5)
    v_img_raw = crop_edges_2d(v_img_raw, 5)

    h_min, h_max = _save_raw_unsigned_fixed_image_linear(
        h_img_raw,
        os.path.join(conf_dir, "confidence_horizontal.png"),
        width_bits=CONF_WIDTH_BITS,
        frac_bits=CONF_FRAC_BITS
    )

    v_min, v_max = _save_raw_unsigned_fixed_image_linear(
        v_img_raw,
        os.path.join(conf_dir, "confidence_vertical.png"),
        width_bits=CONF_WIDTH_BITS,
        frac_bits=CONF_FRAC_BITS
    )

    _, _, h_min_norm, h_max_norm = _save_raw_unsigned_fixed_image_normalised(
        h_img_raw,
        os.path.join(conf_dir, "confidence_horizontal_normalised.png"),
        width_bits=CONF_WIDTH_BITS,
        frac_bits=CONF_FRAC_BITS,
        ignore_zero=True
    )

    _, _, v_min_norm, v_max_norm = _save_raw_unsigned_fixed_image_normalised(
        v_img_raw,
        os.path.join(conf_dir, "confidence_vertical_normalised.png"),
        width_bits=CONF_WIDTH_BITS,
        frac_bits=CONF_FRAC_BITS,
        ignore_zero=True
    )

    return (
        valid_samples_seen,
        h_pixels_written,
        v_pixels_written,
        h_min, h_max,
        v_min, v_max,
        h_min_norm, h_max_norm,
        v_min_norm, v_max_norm,
    )


# -----------------------------------------------------------------------------
# PART 4 : DISPARITY RECONSTRUCTION
# -----------------------------------------------------------------------------

def reconstruct_disparity_images(
    disp_dir: str
) -> tuple[
    int, int, int,
    float, float, float, float, float, float,
    float, float, float, float, float, float
]:
    """
    Reconstruct disparity images from disparity_estimator outputs.

    Assumption:
    - The SV module already outputs image coordinates
    - For both orientations:
        x = column_idx
        y = row_idx

    Saves:
    - disparity_horizontal.png
    - disparity_vertical.png
    - disparity_combined.png
    - disparity_horizontal_normalised.png
    - disparity_vertical_normalised.png
    - disparity_combined_normalised.png

    Returns:
    - (
        valid_samples_seen,
        h_pixels_written,
        v_pixels_written,
        h_min, h_max,
        v_min, v_max,
        c_min, c_max,
        h_min_norm, h_max_norm,
        v_min_norm, v_max_norm,
        c_min_norm, c_max_norm
      )

    Time complexity:
    - O(D), where D is the stream depth
    """
    p_valid = os.path.join(disp_dir, DISP_VALID_MIF)
    p_row_idx = os.path.join(disp_dir, DISP_ROW_IDX_MIF)
    p_col_idx = os.path.join(disp_dir, DISP_COLUMN_IDX_MIF)
    p_orientation = os.path.join(disp_dir, DISP_ORIENTATION_MIF)
    p_disp = os.path.join(disp_dir, DISP_PIXEL_MIF)

    _require_file(p_valid)
    _require_file(p_row_idx)
    _require_file(p_col_idx)
    _require_file(p_orientation)
    _require_file(p_disp)

    valid = load_mif_bits(p_valid, 1)
    row_idx_out = load_mif_bits(p_row_idx, 7)
    col_idx_out = load_mif_bits(p_col_idx, 7)
    orientation = load_mif_bits(p_orientation, 1)
    disp_out = load_mif_bits_signed(p_disp, DISP_WIDTH_BITS)

    depth = len(valid)

    if len(row_idx_out) != depth or len(col_idx_out) != depth or len(orientation) != depth or len(disp_out) != depth:
        raise ValueError(f"Disparity MIF DEPTH mismatch in: {disp_dir}")

    h_img = [[None for _ in range(CROP_W)] for _ in range(CROP_H)]
    v_img = [[None for _ in range(CROP_W)] for _ in range(CROP_H)]
    c_img = [[None for _ in range(CROP_W)] for _ in range(CROP_H)]

    valid_samples_seen = 0
    h_pixels_written = 0
    v_pixels_written = 0

    for stream_idx in range(depth):
        if (valid[stream_idx] & 1) == 0:
            continue

        valid_samples_seen += 1

        ori = orientation[stream_idx] & 1
        row_idx = row_idx_out[stream_idx] & 0x7F
        col_idx = col_idx_out[stream_idx] & 0x7F
        disp_q = disp_out[stream_idx]

        x_coord = col_idx
        y_coord = row_idx

        if not (0 <= x_coord < CROP_W and 0 <= y_coord < CROP_H):
            continue

        c_img[y_coord][x_coord] = disp_q

        if ori == 0:
            h_img[y_coord][x_coord] = disp_q
            h_pixels_written += 1
        else:
            v_img[y_coord][x_coord] = disp_q
            v_pixels_written += 1

    # APPLY CROP
    h_img = crop_edges_2d(h_img, 5)
    v_img = crop_edges_2d(v_img, 5)
    c_img = crop_edges_2d(c_img, 5)

    h_min, h_max = _save_signed_disparity_png(
        h_img,
        os.path.join(disp_dir, "disparity_horizontal.png")
    )

    v_min, v_max = _save_signed_disparity_png(
        v_img,
        os.path.join(disp_dir, "disparity_vertical.png")
    )

    c_min, c_max = _save_signed_disparity_png(
        c_img,
        os.path.join(disp_dir, "disparity_combined.png")
    )

    _, _, h_min_norm, h_max_norm = _save_signed_disparity_inverse_normalised_raw(
        h_img,
        os.path.join(disp_dir, "disparity_horizontal_normalised.png"),
        frac_bits=DISP_FRAC_BITS,
        ignore_zero=True
    )

    _, _, v_min_norm, v_max_norm = _save_signed_disparity_inverse_normalised_raw(
        v_img,
        os.path.join(disp_dir, "disparity_vertical_normalised.png"),
        frac_bits=DISP_FRAC_BITS,
        ignore_zero=True
    )

    _, _, c_min_norm, c_max_norm = _save_signed_disparity_inverse_normalised_raw(
        c_img,
        os.path.join(disp_dir, "disparity_combined_normalised.png"),
        frac_bits=DISP_FRAC_BITS,
        ignore_zero=True
    )

    return (
        valid_samples_seen,
        h_pixels_written,
        v_pixels_written,
        h_min, h_max,
        v_min, v_max,
        c_min, c_max,
        h_min_norm, h_max_norm,
        v_min_norm, v_max_norm,
        c_min_norm, c_max_norm,
    )


# -----------------------------------------------------------------------------
# PART 5 / 6 : FAO + TOP-LEVEL RECONSTRUCTION
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

    print("\n=== Part 1: Converting EPI channel folders ===")
    print("EPI_BASE_DIR:", EPI_BASE_DIR)
    print("CAPTURES_PER_AXIS:", CAPTURES_PER_AXIS)

    for channel_subdir in EPI_CHANNEL_SUBDIRS:
        channel_dir = os.path.join(EPI_BASE_DIR, channel_subdir)

        print("\n---")
        print("EPI channel folder:", channel_dir)

        try:
            epis_saved, valid_samples_seen = reconstruct_epi_one_channel(channel_dir)
            print("Done.")
            print("Valid EPI samples seen:", valid_samples_seen)
            print("EPI PNGs saved:", epis_saved)

            if epis_saved != 8:
                print("WARNING: Expected up to 8 EPI PNGs (4 horizontal + 4 vertical). Saved:", epis_saved)

        except Exception as exc:
            print("ERROR converting EPI folder:", channel_dir)
            print("Reason:", str(exc))

    print("\n=== Part 2: Reconstructing confidence images ===")
    print("CONF_BASE_DIR:", CONF_BASE_DIR)

    try:
        (
            valid_samples_seen,
            h_pixels_written,
            v_pixels_written,
            h_min, h_max,
            v_min, v_max,
            h_min_norm, h_max_norm,
            v_min_norm, v_max_norm,
        ) = reconstruct_confidence_images(CONF_BASE_DIR)

        print("Done.")
        print("Valid confidence samples seen:", valid_samples_seen)
        print("Horizontal pixels written:", h_pixels_written)
        print("Vertical pixels written:", v_pixels_written)
        print("Horizontal confidence range:", h_min, "to", h_max)
        print("Vertical confidence range:", v_min, "to", v_max)
        print("Horizontal normalised min..max:", h_min_norm, "to", h_max_norm)
        print("Vertical normalised min..max:", v_min_norm, "to", v_max_norm)

        print("Saved:", os.path.join(CONF_BASE_DIR, "confidence_horizontal.png"))
        print("Saved:", os.path.join(CONF_BASE_DIR, "confidence_vertical.png"))
        print("Saved:", os.path.join(CONF_BASE_DIR, "confidence_horizontal_normalised.png"))
        print("Saved:", os.path.join(CONF_BASE_DIR, "confidence_vertical_normalised.png"))

    except Exception as exc:
        print("ERROR converting confidence outputs:", CONF_BASE_DIR)
        print("Reason:", str(exc))

    print("\n=== Part 3: Reconstructing disparity images ===")
    print("DISP_BASE_DIR:", DISP_BASE_DIR)

    try:
        (
            valid_samples_seen,
            h_pixels_written,
            v_pixels_written,
            h_min, h_max,
            v_min, v_max,
            c_min, c_max,
            h_min_norm, h_max_norm,
            v_min_norm, v_max_norm,
            c_min_norm, c_max_norm,
        ) = reconstruct_disparity_images(DISP_BASE_DIR)

        print("Done.")
        print("Valid disparity samples seen:", valid_samples_seen)
        print("Horizontal pixels written:", h_pixels_written)
        print("Vertical pixels written:", v_pixels_written)
        print("Horizontal disparity range:", h_min, "to", h_max)
        print("Vertical disparity range:", v_min, "to", v_max)
        print("Combined disparity range  :", c_min, "to", c_max)
        print("Horizontal normalised min..max:", h_min_norm, "to", h_max_norm)
        print("Vertical normalised min..max  :", v_min_norm, "to", v_max_norm)
        print("Combined normalised min..max  :", c_min_norm, "to", c_max_norm)

        print("Saved:", os.path.join(DISP_BASE_DIR, "disparity_horizontal.png"))
        print("Saved:", os.path.join(DISP_BASE_DIR, "disparity_vertical.png"))
        print("Saved:", os.path.join(DISP_BASE_DIR, "disparity_combined.png"))
        print("Saved:", os.path.join(DISP_BASE_DIR, "disparity_horizontal_normalised.png"))
        print("Saved:", os.path.join(DISP_BASE_DIR, "disparity_vertical_normalised.png"))
        print("Saved:", os.path.join(DISP_BASE_DIR, "disparity_combined_normalised.png"))

    except Exception as exc:
        print("ERROR converting disparity outputs:", DISP_BASE_DIR)
        print("Reason:", str(exc))

    print("\n=== Part 4: Reconstructing fused aligned output images ===")
    print("FAO_BASE_DIR:", FAO_BASE_DIR)

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
            base_dir=FAO_BASE_DIR,
            solf_mif=FAO_SOLF_MIF,
            eolf_mif=FAO_EOLF_MIF,
            valid_mif=FAO_VALID_MIF,
            row_mif=FAO_ROW_IDX_MIF,
            col_mif=FAO_COLUMN_IDX_MIF,
            conf_mif=FAO_CONF_PIXEL_MIF,
            wdisp_mif=FAO_WEIGHTED_DISP_MIF
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
            (CROP_W - 2) * (CROP_H - 2),
            (CROP_W - 4) * (CROP_H - 4),
            (CROP_W - 6) * (CROP_H - 6),
            (CROP_W - 8) * (CROP_H - 8),
        ]

        if conf_pixels_written not in expected_areas:
            print("WARNING: Unexpected confidence pixel count:", conf_pixels_written)

        if disp_pixels_written not in expected_areas:
            print("WARNING: Unexpected weighted disparity pixel count:", disp_pixels_written)

        print("Saved:", os.path.join(FAO_BASE_DIR, "fused_confidence.png"))
        print("Saved:", os.path.join(FAO_BASE_DIR, "fused_confidence_normalised.png"))
        print("Saved:", os.path.join(FAO_BASE_DIR, "fused_weighted_disparity.png"))
        print("Saved:", os.path.join(FAO_BASE_DIR, "fused_weighted_disparity_normalised.png"))

    except Exception as exc:
        print("ERROR converting fused aligned output:", FAO_BASE_DIR)
        print("Reason:", str(exc))

    print("\n=== Part 5: Reconstructing final low-pass filter output images ===")
    print("BSLPF_BASE_DIR:", BASE_DIR)

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
            base_dir=BASE_DIR,
            solf_mif=OUT_SOLF_MIF,
            eolf_mif=OUT_EOLF_MIF,
            valid_mif=OUT_VALID_MIF,
            row_mif="SIM_ROW_IDX_OUT.mif",
            col_mif="SIM_COLUMN_IDX_OUT.mif",
            conf_mif="SIM_CONFIDENCE_PIXEL_BIT_DATA.mif",
            wdisp_mif="SIM_WEIGHTED_DISPARITY_PIXEL_BIT_DATA.mif",
            crop_edge=7
        )

        print("Done.")
        print("Seen SOLF:", seen_solf)
        print("Seen EOLF:", seen_eolf)
        print("Valid filtered samples seen:", valid_samples_seen)
        print("Confidence pixels written:", conf_pixels_written)
        print("Weighted disparity pixels written:", disp_pixels_written)
        print("Weighted disparity range:", disp_min, "to", disp_max)
        print("Filtered confidence normalised min..max:", conf_min_norm, "to", conf_max_norm)

    except Exception as exc:
        print("ERROR converting final low-pass outputs:", BASE_DIR)
        print("Reason:", str(exc))

    print("\n=== Part 6: Reconstructing top-level fused aligned output images ===")
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
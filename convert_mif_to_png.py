"""
===============================================================================
LIGHT FIELD OUTPUT RECONSTRUCTOR (7x MIF outputs -> 17x PNG frames)
===============================================================================

Now converts ALL kernel folders in one run:
  - no_filter
  - 3x3_filter
  - 5x5_filter
  - 7x7_filter

Each folder is expected to contain the standard ModelSim output MIFs.
PNGs are written into: <kernel_folder>/png/

===============================================================================
"""

import os
from PIL import Image


# -----------------------------
# CONFIG
# -----------------------------

# Base directory containing subfolders for each kernel run
BASE_DIR = "SystemVerilog_HDL/Bit_Manipulation/tb/bslpf_output_data"

# Kernel subfolders to convert (matches your TB output dirs)
KERNEL_SUBDIRS = [
    "no_filter",
    "3x3_filter",
    "5x5_filter",
    "7x7_filter",
]

# Output MIF filenames (read from each kernel folder)
OUT_VALID_MIF = "SIM_PIXEL_VALID_OUT.mif"
OUT_SOC_MIF   = "SIM_SOC_OUT.mif"
OUT_EOC_MIF   = "SIM_EOC_OUT.mif"
OUT_SOLF_MIF  = "SIM_SOLF_OUT.mif"
OUT_EOLF_MIF  = "SIM_EOLF_OUT.mif"

OUT_RED_MIF   = "SIM_PIXEL_OUT_RED.mif"
OUT_GREEN_MIF = "SIM_PIXEL_OUT_GREEN.mif"
OUT_BLUE_MIF  = "SIM_PIXEL_OUT_BLUE.mif"


# -----------------------------------------------------------------------------
# CONFIG : EPI reconstruction
# -----------------------------------------------------------------------------

EPI_BASE_DIR = "SystemVerilog_HDL/Bit_Manipulation/tb/epic/output_data"

EPI_CHANNEL_SUBDIRS = [
    "red",
    "green",
    "blue",
]

# These names assume the TB writes these files.
# Change them here if your TB uses slightly different filenames.
EPI_VALID_MIF       = "SIM_EPI_VALID_OUT.mif"
EPI_COLUMN_OUT_MIF  = "SIM_EPI_COLUMN_OUT.mif"
EPI_COLUMN_IDX_MIF  = "SIM_EPI_COLUMN_IDX_OUT.mif"
EPI_IDX_MIF         = "SIM_EPI_IDX_OUT.mif"
EPI_ORIENTATION_MIF = "SIM_ORIENTATION_OUT.mif"

# Base name only; actual files are:
#   SIM_EPI_COLUMN_OUT_0.mif ... SIM_EPI_COLUMN_OUT_8.mif
EPI_COLUMN_OUT_PREFIX = "SIM_EPI_COLUMN_OUT_"

# Number of views per axis in each EPI column
CAPTURES_PER_AXIS = 9


# -----------------------------------------------------------------------------
# CONFIG : Confidence reconstruction
# -----------------------------------------------------------------------------

CONF_BASE_DIR = "SystemVerilog_HDL/Bit_Manipulation/tb/conf_comp/output_data"

CONF_VALID_MIF       = "SIM_CONF_VALID_OUT.mif"
CONF_ROW_IDX_MIF     = "SIM_CONF_ROW_IDX_OUT.mif"
CONF_COLUMN_IDX_MIF  = "SIM_CONF_COLUMN_IDX_OUT.mif"
CONF_ORIENTATION_MIF = "SIM_CONF_ORIENTATION_OUT.mif"
CONF_PIXEL_MIF       = "SIM_CONF_PIXEL_OUT.mif"


# -----------------------------------------------------------------------------
# CONFIG : Disparity reconstruction
# -----------------------------------------------------------------------------

DISP_BASE_DIR = "SystemVerilog_HDL/Bit_Manipulation/tb/disp_est/output_data"

DISP_VALID_MIF       = "SIM_DISP_VALID_OUT.mif"
DISP_ROW_IDX_MIF     = "SIM_DISP_ROW_IDX_OUT.mif"
DISP_COLUMN_IDX_MIF  = "SIM_DISP_COLUMN_IDX_OUT.mif"
DISP_ORIENTATION_MIF = "SIM_DISP_ORIENTATION_OUT.mif"
DISP_PIXEL_MIF       = "SIM_DISP_PIXEL_OUT.mif"

# Disparity output format from SV:
# signed Q15.16 stored as 32-bit two's complement
DISP_WIDTH_BITS = 32
DISP_FRAC_BITS  = 16


# -----------------------------------------------------------------------------
# COMMON CONFIG
# -----------------------------------------------------------------------------

# Frame size (must match your DUT IMAGE_DIM)
CROP_W = 128
CROP_H = 128

# Pixel fixed-point format in the MIFs:
# Q8.7 stored as unsigned 15-bit (u15)
PIX_WIDTH_BITS = 15

# EPI packed column width = 9 pixels * 15 bits each
EPI_COLUMN_WIDTH_BITS = CAPTURES_PER_AXIS * PIX_WIDTH_BITS

# Capture ordering (kept identical to your generator)
CAPTURE_ORDER = [
    "v_00.png", "v_01.png", "v_02.png", "v_03.png",
    "h_00.png", "h_01.png", "h_02.png", "h_03.png", "h_04.png", "h_05.png", "h_06.png", "h_07.png", "h_08.png",
    "v_05.png", "v_06.png", "v_07.png", "v_08.png",
]


# -----------------------------------------------------------------------------
# MIF parsing helpers
# -----------------------------------------------------------------------------

def _read_depth_from_mif_header(path: str) -> int:
    depth = -1
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("DEPTH=") and line.endswith(";"):
                try:
                    depth = int(line[len("DEPTH="):-1])
                    return depth
                except ValueError:
                    pass
    raise ValueError(f"Could not parse DEPTH from MIF header: {path}")


def _parse_content_bits_lines(path: str) -> dict[int, str]:
    data = {}
    in_content = False

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()

            if not in_content:
                if line == "CONTENT BEGIN":
                    in_content = True
                continue

            if line == "END;":
                break

            if ":" not in line or not line.endswith(";"):
                continue

            left, right = line[:-1].split(":", 1)
            left = left.strip()
            right = right.strip()

            try:
                addr = int(left)
            except ValueError:
                continue

            bits = right.replace(" ", "")
            data[addr] = bits

    return data


def load_mif_bits(path: str, width: int) -> list[int]:
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
    sign_bit = 1 << (width - 1)
    full_mod = 1 << width
    if word & sign_bit:
        return word - full_mod
    return word


def load_mif_bits_signed(path: str, width: int) -> list[int]:
    raw = load_mif_bits(path, width)
    return [twos_complement_to_int(v, width) for v in raw]

# -----------------------------------------------------------------------------
# Fixed-point helpers
# -----------------------------------------------------------------------------

def q8_7_u15_to_u8(word15: int) -> int:
    return int((word15 >> 7) & 0xFF)


def q15_16_s32_to_float(word32_signed: int) -> float:
    return float(word32_signed) / float(1 << DISP_FRAC_BITS)


# -----------------------------------------------------------------------------
# General helpers
# -----------------------------------------------------------------------------

def ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def _save_frame_png(frame_pixels: list[tuple[int, int, int]], out_path: str) -> None:
    img = Image.new("RGB", (CROP_W, CROP_H), (0, 0, 0))
    n = min(len(frame_pixels), CROP_W * CROP_H)

    idx = 0
    for y in range(CROP_H):
        for x in range(CROP_W):
            if idx < n:
                img.putpixel((x, y), frame_pixels[idx])
            idx += 1

    img.save(out_path)


def _require_file(path: str) -> None:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Missing required file: {path}")


def reconstruct_one_dir(in_dir: str, out_dir: str) -> tuple[bool, int]:
    """
    Returns (seen_solf, frames_saved)
    """
    ensure_dir(out_dir)

    # Build full paths
    p_valid = os.path.join(in_dir, OUT_VALID_MIF)
    p_soc   = os.path.join(in_dir, OUT_SOC_MIF)
    p_eoc   = os.path.join(in_dir, OUT_EOC_MIF)
    p_solf  = os.path.join(in_dir, OUT_SOLF_MIF)
    p_eolf  = os.path.join(in_dir, OUT_EOLF_MIF)

    p_r = os.path.join(in_dir, OUT_RED_MIF)
    p_g = os.path.join(in_dir, OUT_GREEN_MIF)
    p_b = os.path.join(in_dir, OUT_BLUE_MIF)

    # Validate required files exist (fail fast per kernel)
    _require_file(p_valid)
    _require_file(p_soc)
    _require_file(p_eoc)
    _require_file(p_solf)
    _require_file(p_eolf)
    _require_file(p_r)
    _require_file(p_g)
    _require_file(p_b)

    # Load streams
    valid = load_mif_bits(p_valid, 1)
    soc   = load_mif_bits(p_soc,   1)
    eoc   = load_mif_bits(p_eoc,   1)
    solf  = load_mif_bits(p_solf,  1)
    eolf  = load_mif_bits(p_eolf,  1)

    # Pixel data is now u15 (Q8.7)
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
    cap_idx = -1
    frame_pixels: list[tuple[int, int, int]] = []
    seen_solf = False

    for i in range(depth):
        v  = valid[i] & 1
        s  = soc[i] & 1
        e  = eoc[i] & 1
        sf = solf[i] & 1
        ef = eolf[i] & 1

        if v == 1:
            if sf == 1:
                seen_solf = True

            if s == 1:
                if len(frame_pixels) != 0:
                    debug_name = f"debug_partial_{frames_saved:02d}.png"
                    _save_frame_png(frame_pixels, os.path.join(out_dir, debug_name))
                    frame_pixels = []
                cap_idx += 1

            r15 = r_q[i] & 0x7FFF
            g15 = g_q[i] & 0x7FFF
            b15 = b_q[i] & 0x7FFF

            r8 = q8_7_u15_to_u8(r15)
            g8 = q8_7_u15_to_u8(g15)
            b8 = q8_7_u15_to_u8(b15)
            frame_pixels.append((r8, g8, b8))

            if e == 1:
                if len(frame_pixels) != pixels_per_frame:
                    print(
                        f"WARNING: {in_dir} frame {cap_idx} ended with {len(frame_pixels)} valid pixels "
                        f"(expected {pixels_per_frame}). Saving anyway."
                    )

                if 0 <= cap_idx < len(CAPTURE_ORDER):
                    out_name = CAPTURE_ORDER[cap_idx]
                else:
                    out_name = f"capture_{cap_idx:02d}.png"

                _save_frame_png(frame_pixels, os.path.join(out_dir, out_name))
                frames_saved += 1
                frame_pixels = []

            if ef == 1:
                break

    return seen_solf, frames_saved


# -----------------------------------------------------------------------------
# Part 2 : EPI reconstruction
# -----------------------------------------------------------------------------

def _save_epi_gray_png(epi_columns: dict[int, list[int]], out_path: str, width: int, height: int) -> None:
    img = Image.new("L", (width, height), 0)

    for x, col_pixels in epi_columns.items():
        if x < 0 or x >= width:
            continue

        for y in range(min(height, len(col_pixels))):
            img.putpixel((x, y), int(col_pixels[y]))

    img.save(out_path)


def reconstruct_epi_one_channel(channel_dir: str) -> tuple[int, int]:
    """
    Reads the FULL cycle-by-cycle EPI output MIFs from the TB, then reconstructs
    EPIs using only the entries where EPI_VALID_OUT == 1.

    Returns:
        (epis_saved, valid_samples_seen)
    """
    png_dir = channel_dir
    ensure_dir(png_dir)

    p_valid       = os.path.join(channel_dir, EPI_VALID_MIF)
    p_col_idx     = os.path.join(channel_dir, EPI_COLUMN_IDX_MIF)
    p_epi_idx     = os.path.join(channel_dir, EPI_IDX_MIF)
    p_orientation = os.path.join(channel_dir, EPI_ORIENTATION_MIF)

    _require_file(p_valid)
    _require_file(p_col_idx)
    _require_file(p_epi_idx)
    _require_file(p_orientation)

    p_col_files = [
        os.path.join(channel_dir, f"{EPI_COLUMN_OUT_PREFIX}{k}.mif")
        for k in range(CAPTURES_PER_AXIS)
    ]
    for p in p_col_files:
        _require_file(p)

    # Load full cycle-by-cycle output traces
    valid       = load_mif_bits(p_valid, 1)
    col_idx_out = load_mif_bits(p_col_idx, 7)
    epi_idx_out = load_mif_bits(p_epi_idx, 7)
    orientation = load_mif_bits(p_orientation, 1)
    col_out_list = [load_mif_bits(p, PIX_WIDTH_BITS) for p in p_col_files]

    depth = len(valid)

    if len(col_idx_out) != depth or len(epi_idx_out) != depth or len(orientation) != depth:
        raise ValueError(f"EPI index/orientation MIF DEPTH mismatch in: {channel_dir}")

    for k, col_stream in enumerate(col_out_list):
        if len(col_stream) != depth:
            raise ValueError(f"EPI column MIF DEPTH mismatch for column {k} in: {channel_dir}")

    # Only reconstruct the desired EPI indices
    first_idx = 0
    mid0_idx = (CROP_H // 2) - 1
    mid1_idx = (CROP_H // 2)
    last_idx = CROP_H - 1

    wanted_epi_idxs = [first_idx, mid0_idx, mid1_idx, last_idx]
    wanted_epi_set = set(wanted_epi_idxs)

    # key = (orientation, epi_idx)
    # value = {column_idx: [9 grayscale pixels]}
    epi_store: dict[tuple[int, int], dict[int, list[int]]] = {}

    valid_samples_seen = 0
    kept_samples_seen = 0

    for i in range(depth):
        # Just like Part 1: only trust entries when valid is asserted
        if (valid[i] & 1) == 0:
            continue

        valid_samples_seen += 1

        ori = orientation[i] & 1
        epi_idx = epi_idx_out[i] & ((1 << 7) - 1)
        col_idx = col_idx_out[i] & ((1 << 7) - 1)

        # Keep only requested EPIs
        if epi_idx not in wanted_epi_set:
            continue

        # Width of reconstructed image depends on orientation
        # ori == 0 : horizontal EPI, width is image columns
        # ori == 1 : vertical EPI, width is image rows
        if ori == 0:
            if not (0 <= col_idx < CROP_W):
                continue
        else:
            if not (0 <= col_idx < CROP_H):
                continue

        px_u8: list[int] = []
        for k in range(CAPTURES_PER_AXIS):
            px15 = col_out_list[k][i] & 0x7FFF
            px_u8.append(q8_7_u15_to_u8(px15))

        key = (ori, epi_idx)
        if key not in epi_store:
            epi_store[key] = {}

        # If same column appears more than once, latest valid sample wins
        epi_store[key][col_idx] = px_u8
        kept_samples_seen += 1

    epis_saved = 0

    for epi_idx in wanted_epi_idxs:
        # Horizontal EPI
        h_key = (0, epi_idx)
        if h_key in epi_store:
            out_name = f"h_epi_{epi_idx:03d}.png"
            _save_epi_gray_png(
                epi_store[h_key],
                os.path.join(png_dir, out_name),
                width=CROP_W,
                height=CAPTURES_PER_AXIS
            )
            epis_saved += 1

        # Vertical EPI
        v_key = (1, epi_idx)
        if v_key in epi_store:
            out_name = f"v_epi_{epi_idx:03d}.png"
            _save_epi_gray_png(
                epi_store[v_key],
                os.path.join(png_dir, out_name),
                width=CROP_H,
                height=CAPTURES_PER_AXIS
            )
            epis_saved += 1

    return epis_saved, valid_samples_seen


# -----------------------------------------------------------------------------
# Part 3 : Confidence reconstruction
# -----------------------------------------------------------------------------

def _save_gray_image_from_matrix(img_matrix: list[list[int]], out_path: str) -> None:
    height = len(img_matrix)
    width = len(img_matrix[0]) if height > 0 else 0

    img = Image.new("L", (width, height), 0)

    for y in range(height):
        for x in range(width):
            img.putpixel((x, y), int(img_matrix[y][x]))

    img.save(out_path)


def reconstruct_confidence_images(conf_dir: str) -> tuple[int, int, int]:
    """
    Reconstructs two grayscale confidence images:
      - confidence_horizontal.png
      - confidence_vertical.png

    Assumed semantics:
      orientation == 0:
          x = column_idx
          y = epi_idx

      orientation == 1:
          x = epi_idx
          y = column_idx
    """
    p_valid       = os.path.join(conf_dir, CONF_VALID_MIF)
    p_row_idx     = os.path.join(conf_dir, CONF_ROW_IDX_MIF)
    p_col_idx     = os.path.join(conf_dir, CONF_COLUMN_IDX_MIF)
    p_orientation = os.path.join(conf_dir, CONF_ORIENTATION_MIF)
    p_conf        = os.path.join(conf_dir, CONF_PIXEL_MIF)

    _require_file(p_valid)
    _require_file(p_row_idx)
    _require_file(p_col_idx)
    _require_file(p_orientation)
    _require_file(p_conf)

    valid       = load_mif_bits(p_valid, 1)
    row_idx_out = load_mif_bits(p_row_idx, 7)
    col_idx_out = load_mif_bits(p_col_idx, 7)
    orientation = load_mif_bits(p_orientation, 1)
    conf_out    = load_mif_bits(p_conf, PIX_WIDTH_BITS)

    depth = len(valid)

    if len(row_idx_out) != depth or len(col_idx_out) != depth or len(orientation) != depth or len(conf_out) != depth:
        raise ValueError(f"Confidence MIF DEPTH mismatch in: {conf_dir}")

    h_img = [[0 for _ in range(CROP_W)] for _ in range(CROP_H)]
    v_img = [[0 for _ in range(CROP_W)] for _ in range(CROP_H)]

    valid_samples_seen = 0
    h_pixels_written = 0
    v_pixels_written = 0

    for i in range(depth):
        if (valid[i] & 1) == 0:
            continue

        valid_samples_seen += 1

        ori = orientation[i] & 1
        row_idx = row_idx_out[i] & 0x7F
        col_idx = col_idx_out[i] & 0x7F

        conf15 = conf_out[i] & 0x7FFF
        conf8 = q8_7_u15_to_u8(conf15)

        if ori == 0:
            x = col_idx
            y = row_idx
            if 0 <= x < CROP_W and 0 <= y < CROP_H:
                h_img[y][x] = conf8
                h_pixels_written += 1
        else:
            x = col_idx
            y = row_idx
            if 0 <= x < CROP_W and 0 <= y < CROP_H:
                v_img[y][x] = conf8
                v_pixels_written += 1

    _save_gray_image_from_matrix(h_img, os.path.join(conf_dir, "confidence_horizontal.png"))
    _save_gray_image_from_matrix(v_img, os.path.join(conf_dir, "confidence_vertical.png"))

    return valid_samples_seen, h_pixels_written, v_pixels_written


# -----------------------------------------------------------------------------
# Disparity PNG Helper
# -----------------------------------------------------------------------------

def _save_signed_disparity_png(img_matrix: list[list[int | None]], out_path: str) -> tuple[float, float]:
    """
    Saves a grayscale PNG from signed Q15.16 disparity values.

    Behaviour:
      - If all valid values are >= 0, map min..max -> 0..255
      - If there are negative values, use symmetric mapping around zero:
            -max_abs -> 0
             0       -> 128
            +max_abs -> 255

    Returns:
      (min_disp_float, max_disp_float)
    """
    height = len(img_matrix)
    width = len(img_matrix[0]) if height > 0 else 0

    vals = []
    for y in range(height):
        for x in range(width):
            v = img_matrix[y][x]
            if v is not None:
                vals.append(v)

    img = Image.new("L", (width, height), 0)

    if len(vals) == 0:
        img.save(out_path)
        return 0.0, 0.0

    min_v = min(vals)
    max_v = max(vals)

    if min_v == max_v:
        # Constant image
        px = 255 if max_v > 0 else 0
        for y in range(height):
            for x in range(width):
                if img_matrix[y][x] is not None:
                    img.putpixel((x, y), px)
        img.save(out_path)
        return q15_16_s32_to_float(min_v), q15_16_s32_to_float(max_v)

    has_negative = (min_v < 0)

    if has_negative:
        max_abs = max(abs(min_v), abs(max_v))
        if max_abs == 0:
            max_abs = 1

        for y in range(height):
            for x in range(width):
                v = img_matrix[y][x]
                if v is None:
                    continue

                # symmetric signed visualization
                norm = (float(v) / float(max_abs))
                px = int(round(128.0 + 127.0 * norm))
                if px < 0:
                    px = 0
                if px > 255:
                    px = 255
                img.putpixel((x, y), px)
    else:
        span = max_v - min_v
        if span <= 0:
            span = 1

        for y in range(height):
            for x in range(width):
                v = img_matrix[y][x]
                if v is None:
                    continue

                px = int(round(255.0 * (float(v - min_v) / float(span))))
                if px < 0:
                    px = 0
                if px > 255:
                    px = 255
                img.putpixel((x, y), px)

    img.save(out_path)
    return q15_16_s32_to_float(min_v), q15_16_s32_to_float(max_v)


# -----------------------------------------------------------------------------
# Part 4 : Disparity reconstruction
# -----------------------------------------------------------------------------

def reconstruct_disparity_images(disp_dir: str) -> tuple[int, int, int, float, float, float, float, float, float]:
    """
    Reconstructs disparity images from:
      - SIM_DISP_VALID_OUT.mif
      - SIM_DISP_ROW_IDX_OUT.mif
      - SIM_DISP_COLUMN_IDX_OUT.mif
      - SIM_DISP_ORIENTATION_OUT.mif
      - SIM_DISP_PIXEL_OUT.mif

    Assumption:
      The SV disparity_estimator already converts coordinates to image coordinates.
      Therefore for BOTH orientations:
          x = column_idx
          y = row_idx

    Saves:
      - disparity_horizontal.png
      - disparity_vertical.png
      - disparity_combined.png

    Returns:
      (
        valid_samples_seen,
        h_pixels_written,
        v_pixels_written,
        h_min, h_max,
        v_min, v_max,
        c_min, c_max
      )
    """
    p_valid       = os.path.join(disp_dir, DISP_VALID_MIF)
    p_row_idx     = os.path.join(disp_dir, DISP_ROW_IDX_MIF)
    p_col_idx     = os.path.join(disp_dir, DISP_COLUMN_IDX_MIF)
    p_orientation = os.path.join(disp_dir, DISP_ORIENTATION_MIF)
    p_disp        = os.path.join(disp_dir, DISP_PIXEL_MIF)

    _require_file(p_valid)
    _require_file(p_row_idx)
    _require_file(p_col_idx)
    _require_file(p_orientation)
    _require_file(p_disp)

    valid       = load_mif_bits(p_valid, 1)
    row_idx_out = load_mif_bits(p_row_idx, 7)
    col_idx_out = load_mif_bits(p_col_idx, 7)
    orientation = load_mif_bits(p_orientation, 1)
    disp_out    = load_mif_bits_signed(p_disp, DISP_WIDTH_BITS)

    depth = len(valid)

    if len(row_idx_out) != depth or len(col_idx_out) != depth or len(orientation) != depth or len(disp_out) != depth:
        raise ValueError(f"Disparity MIF DEPTH mismatch in: {disp_dir}")

    h_img = [[None for _ in range(CROP_W)] for _ in range(CROP_H)]
    v_img = [[None for _ in range(CROP_W)] for _ in range(CROP_H)]
    c_img = [[None for _ in range(CROP_W)] for _ in range(CROP_H)]

    valid_samples_seen = 0
    h_pixels_written = 0
    v_pixels_written = 0

    for i in range(depth):
        if (valid[i] & 1) == 0:
            continue

        valid_samples_seen += 1

        ori = orientation[i] & 1
        row_idx = row_idx_out[i] & 0x7F
        col_idx = col_idx_out[i] & 0x7F
        disp_q = disp_out[i]

        x = col_idx
        y = row_idx

        if not (0 <= x < CROP_W and 0 <= y < CROP_H):
            continue

        # Combined image: latest valid sample wins
        c_img[y][x] = disp_q

        if ori == 0:
            h_img[y][x] = disp_q
            h_pixels_written += 1
        else:
            v_img[y][x] = disp_q
            v_pixels_written += 1

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

    return (
        valid_samples_seen,
        h_pixels_written,
        v_pixels_written,
        h_min, h_max,
        v_min, v_max,
        c_min, c_max
    )


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> None:
    print("=== Part 1: Converting all kernel folders ===")
    print("BASE_DIR:", BASE_DIR)

    for sub in KERNEL_SUBDIRS:
        in_dir = os.path.join(BASE_DIR, sub)
        out_dir = in_dir

        print("\n---")
        print("Kernel folder:", in_dir)
        print("PNG out dir :", out_dir)

        try:
            seen_solf, frames_saved = reconstruct_one_dir(in_dir, out_dir)
            print("Done.")
            print("Seen SOLF:", seen_solf)
            print("Frames saved:", frames_saved)

            if frames_saved != 17:
                print("WARNING: Expected 17 frames but saved:", frames_saved)

        except Exception as e:
            print("ERROR converting:", in_dir)
            print("Reason:", str(e))

    print("\n=== Part 2: Converting EPI channel folders ===")
    print("EPI_BASE_DIR:", EPI_BASE_DIR)
    print("CAPTURES_PER_AXIS:", CAPTURES_PER_AXIS)

    for sub in EPI_CHANNEL_SUBDIRS:
        channel_dir = os.path.join(EPI_BASE_DIR, sub)

        print("\n---")
        print("EPI channel folder:", channel_dir)

        try:
            epis_saved, valid_samples_seen = reconstruct_epi_one_channel(channel_dir)
            print("Done.")
            print("Valid EPI samples seen:", valid_samples_seen)
            print("EPI PNGs saved:", epis_saved)

            if epis_saved != 8:
                print("WARNING: Expected up to 8 EPI PNGs (4 horizontal + 4 vertical). Saved:", epis_saved)

        except Exception as e:
            print("ERROR converting EPI folder:", channel_dir)
            print("Reason:", str(e))
    
    print("\n=== Part 3: Reconstructing confidence images ===")
    print("CONF_BASE_DIR:", CONF_BASE_DIR)

    try:
        valid_samples_seen, h_pixels_written, v_pixels_written = reconstruct_confidence_images(CONF_BASE_DIR)
        print("Done.")
        print("Valid confidence samples seen:", valid_samples_seen)
        print("Horizontal pixels written:", h_pixels_written)
        print("Vertical pixels written:", v_pixels_written)
        print("Saved:", os.path.join(CONF_BASE_DIR, "confidence_horizontal.png"))
        print("Saved:", os.path.join(CONF_BASE_DIR, "confidence_vertical.png"))

    except Exception as e:
        print("ERROR converting confidence outputs:", CONF_BASE_DIR)
        print("Reason:", str(e))

    print("\n=== Part 4: Reconstructing disparity images ===")
    print("DISP_BASE_DIR:", DISP_BASE_DIR)

    try:
        (
            valid_samples_seen,
            h_pixels_written,
            v_pixels_written,
            h_min, h_max,
            v_min, v_max,
            c_min, c_max
        ) = reconstruct_disparity_images(DISP_BASE_DIR)

        print("Done.")
        print("Valid disparity samples seen:", valid_samples_seen)
        print("Horizontal pixels written:", h_pixels_written)
        print("Vertical pixels written:", v_pixels_written)

        print("Horizontal disparity range:", h_min, "to", h_max)
        print("Vertical disparity range:", v_min, "to", v_max)
        print("Combined disparity range  :", c_min, "to", c_max)

        print("Saved:", os.path.join(DISP_BASE_DIR, "disparity_horizontal.png"))
        print("Saved:", os.path.join(DISP_BASE_DIR, "disparity_vertical.png"))
        print("Saved:", os.path.join(DISP_BASE_DIR, "disparity_combined.png"))

    except Exception as e:
        print("ERROR converting disparity outputs:", DISP_BASE_DIR)
        print("Reason:", str(e))

    print("\nAll conversions attempted.")


if __name__ == "__main__":
    main()
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


# -----------------------------------------------------------------------------
# Fixed-point helpers
# -----------------------------------------------------------------------------

def q8_7_u15_to_u8(word15: int) -> int:
    return int((word15 >> 7) & 0xFF)


def unpack_epi_column_word(word: int) -> list[int]:
    """
    Unpacks a 135-bit packed EPI column into 9x 15-bit pixels.

    Assumes pixel 0 is the most-significant 15-bit slice and
    pixel 8 is the least-significant 15-bit slice.

    If your testbench packed them in reverse order, just reverse
    the returned list.
    """
    pixels = []
    for i in range(CAPTURES_PER_AXIS):
        shift = (CAPTURES_PER_AXIS - 1 - i) * PIX_WIDTH_BITS
        px = (word >> shift) & ((1 << PIX_WIDTH_BITS) - 1)
        pixels.append(px)
    return pixels


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
    # Save PNGs directly in the same directory as the MIF files
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

    first_idx = 0
    mid0_idx = (CROP_H // 2) - 1
    mid1_idx = (CROP_H // 2)
    last_idx = CROP_H - 1

    wanted_epi_idxs = {
        first_idx,
        mid0_idx,
        mid1_idx,
        last_idx,
    }

    # key = (orientation, epi_idx)
    # value = {column_idx: [9 grayscale pixels]}
    epi_store: dict[tuple[int, int], dict[int, list[int]]] = {}

    valid_samples_seen = 0

    for i in range(depth):
        if (valid[i] & 1) == 0:
            continue

        valid_samples_seen += 1

        ori = orientation[i] & 1
        epi_idx = epi_idx_out[i]
        col_idx = col_idx_out[i]

        if epi_idx not in wanted_epi_idxs:
            continue

        if col_idx < 0 or col_idx >= CROP_W:
            continue

        px_u8 = []
        for k in range(CAPTURES_PER_AXIS):
            px_u8.append(q8_7_u15_to_u8(col_out_list[k][i] & 0x7FFF))

        key = (ori, epi_idx)
        if key not in epi_store:
            epi_store[key] = {}

        epi_store[key][col_idx] = px_u8

    epis_saved = 0

    for epi_idx in [first_idx, mid0_idx, mid1_idx, last_idx]:
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

    print("\nAll conversions attempted.")


if __name__ == "__main__":
    main()
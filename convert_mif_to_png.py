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

# Frame size (must match your DUT IMAGE_DIM)
CROP_W = 64
CROP_H = 64

# Pixel fixed-point format in the MIFs:
# Q8.8 stored as unsigned 16-bit (u16)
PIX_WIDTH_BITS = 16

# Capture ordering (kept identical to your generator)
CAPTURE_ORDER = [
    "v_00.png", "v_01.png", "v_02.png", "v_03.png",
    "h_00.png", "h_01.png", "h_02.png", "h_03.png", "h_04.png", "h_05.png", "h_06.png", "h_07.png", "h_08.png",
    "v_05.png", "v_06.png", "v_07.png", "v_08.png",
]


# -----------------------------
# MIF parsing helpers
# -----------------------------

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
    raise ValueError(f"Could not parse DEPTH=...; from MIF header: {path}")


def _parse_content_bits_lines(path: str) -> dict[int, str]:
    """
    Returns {addr: bitstring} for lines like:
      123 : 0101...;
    Ignores anything outside CONTENT BEGIN .. END;
    """
    data: dict[int, str] = {}
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

            if ":" not in line:
                continue
            if not line.endswith(";"):
                continue

            left, right = line[:-1].split(":", 1)  # drop trailing ';'
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
    """
    Loads a BIN-data MIF into a dense list[int] of length DEPTH.
    Missing addresses are treated as 0.
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


# -----------------------------
# Q8.8 (u16) conversion helpers
# -----------------------------

def q8_8_u16_to_u8(word16: int) -> int:
    """
    word16 is unsigned Q8.8:
      [15:8] integer part (0..255)
      [7:0]  fractional part

    For PNG output we just take the integer byte.
    """
    u8 = (word16 >> 8) & 0xFF
    return int(u8)


# -----------------------------
# Reconstruction
# -----------------------------

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

    # Pixel data is now u16 (Q8.8)
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

            r16 = r_q[i] & 0xFFFF
            g16 = g_q[i] & 0xFFFF
            b16 = b_q[i] & 0xFFFF

            r8 = q8_8_u16_to_u8(r16)
            g8 = q8_8_u16_to_u8(g16)
            b8 = q8_8_u16_to_u8(b16)
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


def main() -> None:
    print("=== Converting all kernel folders ===")
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

    print("\nAll conversions attempted.")


if __name__ == "__main__":
    main()
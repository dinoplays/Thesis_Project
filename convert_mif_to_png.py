"""
===============================================================================
LIGHT FIELD OUTPUT RECONSTRUCTOR (7x MIF outputs -> 17x PNG frames)
===============================================================================

Reads ModelSim-generated output MIF streams from your bit_shift_low_pass_filter TB:

  - SIM_PIXEL_OUT_RED.mif   (WIDTH=24)  Q12.12 stored in [23:0]
  - SIM_PIXEL_OUT_GREEN.mif (WIDTH=24)  Q12.12 stored in [23:0]
  - SIM_PIXEL_OUT_BLUE.mif  (WIDTH=24)  Q12.12 stored in [23:0]

And flags:

  - SIM_PIXEL_VALID_OUT.mif (WIDTH=1)
  - SIM_SOC_OUT.mif         (WIDTH=1)
  - SIM_EOC_OUT.mif         (WIDTH=1)
  - SIM_SOLF_OUT.mif        (WIDTH=1)
  - SIM_EOLF_OUT.mif        (WIDTH=1)

It reconstructs the 17 captures (frames) by:
  - Only consuming pixels when pixel_valid_out == 1
  - Starting a new frame on soc_out == 1
  - Ending a frame on eoc_out == 1
  - Stopping when eolf_out == 1 (end of light field)

Each valid pixel is Q12.12; we convert to 8-bit by:
  - unsigned_int12 = (q12_12_word >> 12) & 0xFFF   # 0..4095
  - pixel8 = unsigned_int12 >> 4                   # 0..255

Outputs 17 PNG files in CAPTURE_ORDER (same as your generator):
  v_00.png, v_01.png, v_02.png, v_03.png,
  h_00.png, h_01.png, h_02.png, h_03.png, h_04.png, h_05.png, h_06.png, h_07.png, h_08.png,
  v_05.png, v_06.png, v_07.png, v_08.png

NOTE:
- This script assumes each capture is exactly CROP_W x CROP_H valid pixels.
- Invalid cycles (gaps) are ignored via OUT_VALID_MIF.
- Uses PIL only.

===============================================================================
"""

import os
from PIL import Image


# -----------------------------
# CONFIG (edit in code)
# -----------------------------

# Absolute directory containing the output MIF files from ModelSim
IN_DIR = "SystemVerilog_HDL/Bit_Manipulation/tb/bslpf_output_data/3x3_filter"

# Output directory where reconstructed PNG images will be saved
OUT_DIR = "SystemVerilog_HDL/Bit_Manipulation/tb/bslpf_output_data/3x3_filter"

# Output MIF filenames (read from IN_DIR)
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

            # Expect: <addr> : <bits>;
            # Be robust to extra spaces/tabs
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
            # bits should be exactly width, but we won't assume perfect formatting
            # Take the rightmost 'width' bits if longer, left-pad with zeros if shorter
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
# Q12.12 conversion helpers
# -----------------------------

def q12_12_u24_to_u8(word24: int) -> int:
    """
    DUT outputs are Q12.12 stored in a 24-bit container.
    Treat as unsigned.

    Your SV scaling is effectively:
        pixel8 (0..255) encoded as pixel8 << 16
    So:
        I12 = (word24 >> 12) in range 0..4095
    Convert back to 8-bit by:
        pixel8 = I12 >> 4   (divide by 16)
    """
    i12 = (word24 >> 12) & 0xFFF  # 0..4095
    u8 = i12 >> 4                 # 0..255 (bit-exact for <<16 encoding)
    if u8 > 255:
        u8 = 255
    return int(u8)


# -----------------------------
# Reconstruction
# -----------------------------

def ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def main() -> None:
    ensure_dir(OUT_DIR)

    # Build full paths
    p_valid = os.path.join(IN_DIR, OUT_VALID_MIF)
    p_soc   = os.path.join(IN_DIR, OUT_SOC_MIF)
    p_eoc   = os.path.join(IN_DIR, OUT_EOC_MIF)
    p_solf  = os.path.join(IN_DIR, OUT_SOLF_MIF)
    p_eolf  = os.path.join(IN_DIR, OUT_EOLF_MIF)

    p_r = os.path.join(IN_DIR, OUT_RED_MIF)
    p_g = os.path.join(IN_DIR, OUT_GREEN_MIF)
    p_b = os.path.join(IN_DIR, OUT_BLUE_MIF)

    # Load streams
    valid = load_mif_bits(p_valid, 1)
    soc   = load_mif_bits(p_soc,   1)
    eoc   = load_mif_bits(p_eoc,   1)
    solf  = load_mif_bits(p_solf,  1)
    eolf  = load_mif_bits(p_eolf,  1)

    r_q = load_mif_bits(p_r, 24)
    g_q = load_mif_bits(p_g, 24)
    b_q = load_mif_bits(p_b, 24)

    # Sanity: all depths must match
    depth = len(valid)
    if len(soc) != depth or len(eoc) != depth or len(solf) != depth or len(eolf) != depth:
        raise ValueError("Flag MIF DEPTH mismatch (valid/soc/eoc/solf/eolf).")
    if len(r_q) != depth or len(g_q) != depth or len(b_q) != depth:
        raise ValueError("Pixel MIF DEPTH mismatch (r/g/b vs flags).")

    pixels_per_frame = CROP_W * CROP_H

    frames_saved = 0
    cap_idx = -1

    # Current frame buffers (store tuples (r,g,b) as ints 0..255)
    frame_pixels = []

    seen_solf = False

    for i in range(depth):
        v = valid[i] & 1
        s = soc[i] & 1
        e = eoc[i] & 1
        sf = solf[i] & 1
        ef = eolf[i] & 1

        if v == 1:
            # Detect start of light field (optional informational)
            if sf == 1:
                seen_solf = True

            # Start-of-capture: begin a new frame
            if s == 1:
                # If we were mid-frame (shouldn't happen), finalize it defensively
                if len(frame_pixels) != 0:
                    debug_name = f"debug_partial_{frames_saved:02d}.png"
                    _save_frame_png(frame_pixels, os.path.join(OUT_DIR, debug_name))
                    frame_pixels = []

                cap_idx += 1

            # Append pixel
            r8 = q12_12_u24_to_u8(r_q[i] & 0xFFFFFF)
            g8 = q12_12_u24_to_u8(g_q[i] & 0xFFFFFF)
            b8 = q12_12_u24_to_u8(b_q[i] & 0xFFFFFF)
            frame_pixels.append((r8, g8, b8))

            # End-of-capture: finalize the frame
            if e == 1:
                if len(frame_pixels) != pixels_per_frame:
                    print(
                        f"WARNING: Frame {cap_idx} ended with {len(frame_pixels)} valid pixels "
                        f"(expected {pixels_per_frame}). Saving anyway."
                    )

                if 0 <= cap_idx < len(CAPTURE_ORDER):
                    out_name = CAPTURE_ORDER[cap_idx]
                else:
                    out_name = f"capture_{cap_idx:02d}.png"

                out_path = os.path.join(OUT_DIR, out_name)
                _save_frame_png(frame_pixels, out_path)
                frames_saved += 1
                frame_pixels = []

            # End-of-lightfield: stop after saving the frame containing EOLF
            if ef == 1:
                break

    print("Done.")
    print("Seen SOLF:", seen_solf)
    print("Frames saved:", frames_saved)
    print("PNG output dir:", OUT_DIR)

    if frames_saved != 17:
        print("WARNING: Expected 17 frames but saved:", frames_saved)


def _save_frame_png(frame_pixels: list[tuple[int, int, int]], out_path: str) -> None:
    """
    Saves the current frame_pixels list into a CROP_W x CROP_H PNG.
    If pixel count is short, remaining pixels are black.
    If pixel count is long, extra pixels are dropped.
    """
    img = Image.new("RGB", (CROP_W, CROP_H), (0, 0, 0))
    n = min(len(frame_pixels), CROP_W * CROP_H)

    # Raster scan placement
    idx = 0
    for y in range(CROP_H):
        for x in range(CROP_W):
            if idx < n:
                img.putpixel((x, y), frame_pixels[idx])
            idx += 1

    img.save(out_path)


if __name__ == "__main__":
    main()
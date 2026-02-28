"""
===============================================================================
LIGHT FIELD SIMULATION INPUT GENERATOR (PNG -> 6x MIF streams)
===============================================================================

This script converts a folder of PNG images into SIX Intel/Quartus-style
Memory Initialization Files (.mif). The output emulates a camera/light-field
pixel stream entering hardware, including intentional "invalid" cycles to
replicate real hardware timing gaps.

------------------------------------------------------------------------------
WHAT YOU PROVIDE (INPUT)
------------------------------------------------------------------------------
A folder containing 17 PNG images representing 17 "captures":

    h_00.png ... h_08.png  (9 images)
    v_00.png ... v_08.png  (9 images)

But the streaming order is NOT alphabetical. The required stream ordering is:

    v_00, v_01, v_02, v_03,
    h_00, h_01, h_02, h_03, h_04, h_05, h_06, h_07, h_08,
    v_04, v_05, v_06, v_07, v_08

Total captures = 17.

Each capture contributes its pixels to ONE continuous global stream.

------------------------------------------------------------------------------
HOW PNG PIXELS ARE CONVERTED INTO BIT-DATA (RGB888 / 24-bit words)
------------------------------------------------------------------------------
Each PNG pixel is read as standard 8-bit-per-channel RGB:

    R in [0..255]
    G in [0..255]
    B in [0..255]

We then pack it into one 24-bit word in the format:

    RRRRRRRR GGGGGGGG BBBBBBBB
    [23:16]  [15:8]   [7:0]

So:
    word24 = (R << 16) | (G << 8) | (B)

Finally, we write that 24-bit value as a 24-character binary string:

    format(word24, "024b")

Example:
    R=255, G=128, B=64
    word24 = 0xFF8040
    binary = 111111111000000001000000

This bit-string becomes ONE LINE / ONE WORD in the pixel .mif.

------------------------------------------------------------------------------
CROPPING (CENTER CROP WxH)
------------------------------------------------------------------------------
Each image is converted to RGB (alpha dropped if present), then center-cropped
to CROP_W x CROP_H. If the image is smaller than the crop size:
    - If PAD_IF_SMALL=True, it is centered on a black canvas and padded.
    - If PAD_IF_SMALL=False, the script raises an error.

This ensures every capture yields exactly:
    pixels_per_capture = CROP_W * CROP_H

------------------------------------------------------------------------------
SIMULATING REAL HARDWARE GAPS (INVALID CYCLES)
------------------------------------------------------------------------------
Hardware streams rarely deliver pixels as a perfect uninterrupted sequence.
To replicate this, the script injects invalid "cycles" into the global stream.

An invalid cycle is represented by:
    pixel_data = 24'b0 (all zeros)
    pixel_valid_in = 0
and all other flags = 0.

There are three gap types:

1) PRE-GAP (before each capture):
    Insert PRE_GAP_MIN..PRE_GAP_MAX invalid words.

2) POST-GAP (after each capture):
    Insert POST_GAP_MIN..POST_GAP_MAX invalid words.

3) BETWEEN-CAPTURE GAP (between captures):
    Insert BETWEEN_CAP_GAP_MIN..BETWEEN_CAP_GAP_MAX invalid words
    between the end of capture i and the beginning of capture i+1.
    (This is not applied before the very first capture.)

The gap lengths are pseudo-random but reproducible due to RNG_SEED.

------------------------------------------------------------------------------
SIX OUTPUT FILES (ALL SAME DEPTH, CYCLE-ALIGNED)
------------------------------------------------------------------------------
All six files have identical DEPTH. Index i refers to the same "cycle" in all.

1) SIM_PIXEL_BIT_DATA.mif   (WIDTH=24)
   - 24-bit RGB pixel words for valid pixels
   - 24'b0 for invalid gap cycles

2) SIM_PIXEL_VALID_IN.mif   (WIDTH=1)
   - '1' for valid pixels
   - '0' for invalid gap cycles

3) SIM_SOC_IN.mif  (WIDTH=1)  Start-of-capture
   - '1' on the FIRST VALID pixel of each capture
   - exactly 17 ones total

4) SIM_EOC_IN.mif  (WIDTH=1)  End-of-capture
   - '1' on the LAST VALID pixel of each capture
   - exactly 17 ones total

5) SIM_SOLF_IN.mif (WIDTH=1)  Start-of-lightfield
   - '1' on the FIRST VALID pixel of the entire light-field stream
   - exactly 1 one total

6) SIM_EOLF_IN.mif (WIDTH=1)  End-of-lightfield
   - '1' on the LAST VALID pixel of the entire light-field stream
   - exactly 1 one total

IMPORTANT: SOC/EOC/SOLF/EOLF are asserted ONLY on valid pixels.

------------------------------------------------------------------------------
INTENDED RTL USAGE
------------------------------------------------------------------------------
You can load these in simulation as:

    reg [23:0] pixel_mem [0:DEPTH-1];
    reg        valid_mem [0:DEPTH-1];
    reg        soc_mem   [0:DEPTH-1];
    ...

    initial begin
        $readmemb("SIM_PIXEL_BIT_DATA.mif", pixel_mem);
        $readmemb("SIM_PIXEL_VALID_IN.mif", valid_mem);
        ...
    end

Then each clock cycle i:
    pixel_data_in  <= pixel_mem[i];
    pixel_valid_in <= valid_mem[i];
    soc_in         <= soc_mem[i];
    ...

Note: Need to delete v_04.png temporarily to match the requested capture order and counts.
      v_04 is equivalent to h_04 so it is excluded.
===============================================================================
"""

import os
import random
from PIL import Image


# -----------------------------
# CONFIG (edit in code)
# -----------------------------

INPUT_FOLDER = "Python/Bit_Manipulation/headshot/cross_raw_data_png"
OUTPUT_FOLDER = "SystemVerilog_HDL/Bit_Manipulation/tb_64/input_data"

# Center crop size (W x H).
CROP_W = 64
CROP_H = 64
PAD_IF_SMALL = True

# Fixed capture ordering (MUST match your request exactly)
# v_04 is equivalent to h_04 so it is excluded
CAPTURE_ORDER = [
    "v_00.png", "v_01.png", "v_02.png", "v_03.png",
    "h_00.png", "h_01.png", "h_02.png", "h_03.png", "h_04.png", "h_05.png", "h_06.png", "h_07.png", "h_08.png",
    "v_05.png", "v_06.png", "v_07.png", "v_08.png",
]

# Gap ranges (inclusive)
PRE_GAP_MIN = 0
PRE_GAP_MAX = 4

POST_GAP_MIN = 0
POST_GAP_MAX = 4

BETWEEN_CAP_GAP_MIN = 0
BETWEEN_CAP_GAP_MAX = 16

# Reproducible randomness for gap insertion
RNG_SEED = 12345

# Output filenames (as requested)
PIXEL_MIF = "SIM_PIXEL_BIT_DATA.mif"
VALID_MIF = "SIM_PIXEL_VALID_IN.mif"
SOC_MIF   = "SIM_SOC_IN.mif"
EOC_MIF   = "SIM_EOC_IN.mif"
SOLF_MIF  = "SIM_SOLF_IN.mif"
EOLF_MIF  = "SIM_EOLF_IN.mif"


# -----------------------------
# Helpers
# -----------------------------

def ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def center_crop_or_pad_rgb(img_rgb: Image.Image, out_w: int, out_h: int, pad_if_small: bool) -> Image.Image:
    """
    Returns an RGB image of exactly (out_w, out_h).

    If img is larger: center-crop.
    If img is smaller:
        - pad_if_small True  -> pad with black and center the original image
        - pad_if_small False -> raise error
    """
    in_w, in_h = img_rgb.size

    if in_w >= out_w and in_h >= out_h:
        left = (in_w - out_w) // 2
        top = (in_h - out_h) // 2
        right = left + out_w
        bottom = top + out_h
        return img_rgb.crop((left, top, right, bottom))

    if not pad_if_small:
        raise ValueError(
            f"Image {in_w}x{in_h} smaller than crop {out_w}x{out_h} and PAD_IF_SMALL=False."
        )

    canvas = Image.new("RGB", (out_w, out_h), (0, 0, 0))
    paste_x = (out_w - in_w) // 2
    paste_y = (out_h - in_h) // 2
    canvas.paste(img_rgb, (paste_x, paste_y))
    return canvas


def rgb888_to_word24(r: int, g: int, b: int) -> int:
    """
    Pack 8-bit R,G,B into a single 24-bit RGB888 word:

        [23:16] = R
        [15:8]  = G
        [7:0]   = B
    """
    return ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF)


def write_mif(path: str, width: int, data_bits_list: list[str]) -> None:
    """
    Writes a Quartus-compatible .mif file with:
        ADDRESS_RADIX=DEC
        DATA_RADIX=BIN

    Each entry is a fixed-width binary string.
    """
    depth = len(data_bits_list)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"WIDTH={width};\n")
        f.write(f"DEPTH={depth};\n\n")
        f.write("ADDRESS_RADIX=DEC;\n")
        f.write("DATA_RADIX=BIN;\n\n")
        f.write("CONTENT BEGIN\n")

        addr = 0
        for bits in data_bits_list:
            f.write(f"{addr} : {bits};\n")
            addr += 1

        f.write("END;\n")


# -----------------------------
# Stream builder
# -----------------------------

def main() -> None:
    ensure_dir(OUTPUT_FOLDER)
    random.seed(RNG_SEED)

    # Validate that required files exist (prevents silent wrong ordering)
    missing = []
    for fname in CAPTURE_ORDER:
        fpath = os.path.join(INPUT_FOLDER, fname)
        if not os.path.isfile(fpath):
            missing.append(fname)

    if len(missing) != 0:
        raise FileNotFoundError(
            "Missing required PNG(s) in input folder:\n" + "\n".join(missing)
        )

    # Streams store BIT STRINGS, aligned index-by-index across all 6 files
    pixel_stream = []   # 24-bit "0/1" strings
    valid_stream = []   # 1-bit strings
    soc_stream   = []   # 1-bit strings
    eoc_stream   = []   # 1-bit strings
    solf_stream  = []   # 1-bit strings
    eolf_stream  = []   # 1-bit strings

    # Append one "cycle" across all streams
    def append_cycle(pixel_bits_24: str, valid_bit: str, soc_bit: str, eoc_bit: str, solf_bit: str, eolf_bit: str) -> None:
        pixel_stream.append(pixel_bits_24)
        valid_stream.append(valid_bit)
        soc_stream.append(soc_bit)
        eoc_stream.append(eoc_bit)
        solf_stream.append(solf_bit)
        eolf_stream.append(eolf_bit)

    # Append N invalid cycles (pixel=0, valid=0, flags=0)
    def append_invalid_cycles(n: int) -> None:
        for _ in range(n):
            append_cycle("0" * 24, "0", "0", "0", "0", "0")

    first_valid_global_index = None
    last_valid_global_index = None

    soc_count = 0
    eoc_count = 0

    captures_total = len(CAPTURE_ORDER)

    for cap_idx in range(captures_total):
        fname = CAPTURE_ORDER[cap_idx]
        path_in = os.path.join(INPUT_FOLDER, fname)

        # Between-capture gap (not before first capture)
        if cap_idx != 0:
            between_gap = random.randint(BETWEEN_CAP_GAP_MIN, BETWEEN_CAP_GAP_MAX)
            append_invalid_cycles(between_gap)

        # Pre-gap for this capture
        pre_gap = random.randint(PRE_GAP_MIN, PRE_GAP_MAX)
        append_invalid_cycles(pre_gap)

        # Load and crop image
        img = Image.open(path_in).convert("RGB")
        img = center_crop_or_pad_rgb(img, CROP_W, CROP_H, PAD_IF_SMALL)
        pix = img.load()

        # Stream all pixels for this capture (raster scan)
        for y in range(CROP_H):
            for x in range(CROP_W):
                r, g, b = pix[x, y]
                word24 = rgb888_to_word24(r, g, b)
                bits24 = format(word24, "024b")  # 24-bit binary string

                is_first = (y == 0 and x == 0)
                is_last  = (y == (CROP_H - 1) and x == (CROP_W - 1))

                this_index = len(pixel_stream)

                # SOC/EOC asserted only on valid pixels
                soc_bit = "1" if is_first else "0"
                eoc_bit = "1" if is_last else "0"

                if is_first:
                    soc_count += 1
                if is_last:
                    eoc_count += 1

                # SOLF asserted on the first valid pixel of the entire light field
                solf_bit = "0"
                if first_valid_global_index is None:
                    first_valid_global_index = this_index
                    solf_bit = "1"

                # EOLF set later after we know final valid pixel index
                eolf_bit = "0"

                last_valid_global_index = this_index

                append_cycle(bits24, "1", soc_bit, eoc_bit, solf_bit, eolf_bit)

        # Post-gap for this capture
        post_gap = random.randint(POST_GAP_MIN, POST_GAP_MAX)
        append_invalid_cycles(post_gap)

    # Sanity checks
    if soc_count != 17:
        raise ValueError(f"SOC count expected 17 but got {soc_count}. Check CAPTURE_ORDER length.")
    if eoc_count != 17:
        raise ValueError(f"EOC count expected 17 but got {eoc_count}. Check CAPTURE_ORDER length.")
    if first_valid_global_index is None or last_valid_global_index is None:
        raise ValueError("No valid pixels were written. Something went wrong.")

    # Set EOLF at the last valid pixel
    eolf_stream[last_valid_global_index] = "1"

    # Verify single SOLF/EOLF
    solf_ones = 0
    for b in solf_stream:
        if b == "1":
            solf_ones += 1

    eolf_ones = 0
    for b in eolf_stream:
        if b == "1":
            eolf_ones += 1

    if solf_ones != 1:
        raise ValueError(f"SOLF expected 1 one-bit but got {solf_ones}.")
    if eolf_ones != 1:
        raise ValueError(f"EOLF expected 1 one-bit but got {eolf_ones}.")

    # Write MIFs
    write_mif(os.path.join(OUTPUT_FOLDER, PIXEL_MIF), 24, pixel_stream)
    write_mif(os.path.join(OUTPUT_FOLDER, VALID_MIF), 1,  valid_stream)
    write_mif(os.path.join(OUTPUT_FOLDER, SOC_MIF),   1,  soc_stream)
    write_mif(os.path.join(OUTPUT_FOLDER, EOC_MIF),   1,  eoc_stream)
    write_mif(os.path.join(OUTPUT_FOLDER, SOLF_MIF),  1,  solf_stream)
    write_mif(os.path.join(OUTPUT_FOLDER, EOLF_MIF),  1,  eolf_stream)

    print("Wrote 6 MIF files to:", OUTPUT_FOLDER)
    print("Total stream depth (words):", len(pixel_stream))
    print("SOC ones:", soc_count, "EOC ones:", eoc_count, "SOLF ones:", solf_ones, "EOLF ones:", eolf_ones)
    print("First valid index:", first_valid_global_index, "Last valid index:", last_valid_global_index)


if __name__ == "__main__":
    main()
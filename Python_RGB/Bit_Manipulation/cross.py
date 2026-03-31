# cross.py
# Bit-shift low-pass convolution used prior to EPI construction.
#
# INPUT:  expects cross_raw_data frames as IMGB dtype_code=1 (u8), C=3.
# OUTPUT: writes IMGB dtype_code=4 (u24), C=3, storing biased signed Q12.12 values.
#
# NO numpy, NO imageio. Pure stdlib.
# Operations were converted to direct bit-shift and manipulation where possible

import os
import re

from utils import (
    Q_FRAC,
    BIAS_INT,
    U24_MAX,
    imgb_make,
    imgb_parse_wh_payload,
    save_imgb,
)

# W = H = 512 => multiply/divide by W/H can use << 9 / >> 9 in INDEXING math
WH_SHIFT = 9
WH_SIZE = 512
HW_X3 = 786432 # 512*512*3 = 786,432
WH_X9 = 2359296 # 512*512*9 = 2,359,296


# ---------- filesystem helpers ----------

def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

# ---------- kernels as exponent maps ----------
# W_ij = 2^(E_ij), implemented as (px << E_ij)
# sums are powers-of-two -> normalize by right shift

_KERNELS = {
    3: (
        [
            [0, 1, 0],
            [1, 2, 1],
            [0, 1, 0],
        ],
        4,  # sum=16
    ),
    5: (
        [
            [0, 1, 1, 1, 0],
            [1, 2, 2, 2, 1],
            [1, 2, 2, 2, 1],
            [1, 2, 2, 2, 1],
            [0, 1, 1, 1, 0],
        ],
        6,  # sum=64
    ),
    7: (
        [
            [0, 0, 1, 1, 1, 0, 0],
            [0, 1, 2, 2, 2, 1, 0],
            [1, 2, 2, 2, 2, 2, 1],
            [1, 2, 2, 2, 2, 2, 1],
            [1, 2, 2, 2, 2, 2, 1],
            [0, 1, 2, 2, 2, 1, 0],
            [0, 0, 1, 1, 1, 0, 0],
        ],
        7,  # sum=128
    ),
}

def _reflect_index(i: int, n: int) -> int:
    while i < 0 or i >= n:
        if i < 0:
            i = -i
        else:
            i = ((n << 1) - 2) - i
    return i

def _convolve_u8_rgb(raw: bytes, W: int, H: int, E, norm_shift: int) -> bytes:
    k = len(E)
    p = k >> 1

    taps = []
    for dy in range(k):
        row = E[dy]
        ddy = dy - p
        for dx in range(k):
            taps.append((ddy, dx - p, row[dx]))

    out = bytearray(HW_X3)  # 512*512*3 = 786,432

    for y in range(H):
        for x in range(W):
            acc0 = 0
            acc1 = 0
            acc2 = 0

            for dy, dx, e in taps:
                yy = _reflect_index(y + dy, H)
                xx = _reflect_index(x + dx, W)

                # idx = yy*W + xx  -> (yy<<9) + xx
                idx = (yy << WH_SHIFT) + xx
                base = (idx << 1) + idx

                acc0 += raw[base + 0] << e
                acc1 += raw[base + 1] << e
                acc2 += raw[base + 2] << e

            v0 = acc0 >> norm_shift
            v1 = acc1 >> norm_shift
            v2 = acc2 >> norm_shift

            if v0 > 255: v0 = 255
            if v1 > 255: v1 = 255
            if v2 > 255: v2 = 255

            idx_o = (y << WH_SHIFT) + x
            base_o = (idx_o << 1) + idx_o

            out[base_o + 0] = v0
            out[base_o + 1] = v1
            out[base_o + 2] = v2

    return bytes(out)

def _u8_rgb_to_q12_12_u24_payload(raw_u8_rgb: bytes, W: int, H: int) -> bytes:
    out = bytearray(WH_X9)  # WH_X9 = 512*512*9 = 2,359,296

    o = 0
    for b in raw_u8_rgb:
        v_q = int(b) << Q_FRAC

        u = v_q + BIAS_INT
        if u < 0:
            u = 0
        elif u > U24_MAX:
            u = U24_MAX

        out[o] = u & 0xFF
        out[o + 1] = (u >> 8) & 0xFF
        out[o + 2] = (u >> 16) & 0xFF
        o = o + 3

    return bytes(out)

def bit_shift_low_pass_filter(in_dir: str, kernel_size: int = 5, out_dir: str | None = None) -> str:
    E, norm_shift = _KERNELS[kernel_size]

    names = [n for n in os.listdir(in_dir) if n.lower().endswith(".imgb")]
    names.sort(key=_natural_key)

    for name in names:
        src = os.path.join(in_dir, name)
        dst = os.path.join(out_dir, name)

        with open(src, "rb") as f:
            blob = f.read()

        W, H, payload = imgb_parse_wh_payload(blob)

        blurred_u8 = _convolve_u8_rgb(payload, W, H, E, norm_shift)
        out_payload = _u8_rgb_to_q12_12_u24_payload(blurred_u8, W, H)

        out_blob = imgb_make(W=W, H=H, C=3, dtype_code=4, payload=out_payload)
        save_imgb(out_blob, dst)

    return out_dir
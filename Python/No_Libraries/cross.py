# cross.py
# Low-pass convolution used prior to EPI construction.
#
# INPUT:  expects cross_raw_data frames as IMGB dtype_code=1 (u8), C=3.
# OUTPUT: writes IMGB dtype_code=4 (u24), C=3, storing biased signed Q12.12 values.
#
# NO numpy, NO imageio. Pure stdlib.

import os
import re

from utils import (
    Q_SCALE,
    BIAS_INT,
    U24_MAX,
    imgb_make,
    imgb_parse,
    save_imgb,
)

# ---------- filesystem helpers ----------

def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

# ---------- kernels as integer weights ----------
# W_ij are integer multipliers; normalize by dividing by the sum (kernel_sum)

_KERNELS = {
    3: (
        [
            [1, 2, 1],
            [2, 4, 2],
            [1, 2, 1],
        ],
        16,  # sum
    ),
    5: (
        [
            [1, 2, 2, 2, 1],
            [2, 4, 4, 4, 2],
            [2, 4, 4, 4, 2],
            [2, 4, 4, 4, 2],
            [1, 2, 2, 2, 1],
        ],
        64,  # sum
    ),
    7: (
        [
            [1, 1, 2, 2, 2, 1, 1],
            [1, 2, 4, 4, 4, 2, 1],
            [2, 4, 4, 4, 4, 4, 2],
            [2, 4, 4, 4, 4, 4, 2],
            [2, 4, 4, 4, 4, 4, 2],
            [1, 2, 4, 4, 4, 2, 1],
            [1, 1, 2, 2, 2, 1, 1],
        ],
        128,  # sum
    ),
}

def _reflect_index(i: int, n: int) -> int:
    while i < 0 or i >= n:
        if i < 0:
            i = -i
        else:
            i = (2 * n - 2) - i
    return i

def _convolve_u8_rgb(raw: bytes, W: int, H: int, K, kernel_sum: int) -> bytes:
    k = len(K)
    p = k // 2

    # Precompute tap list: (dy, dx, weight)
    taps = []
    for dy in range(k):
        row = K[dy]
        ddy = dy - p
        for dx in range(k):
            taps.append((ddy, dx - p, row[dx]))

    out = bytearray(H * W * 3)

    # For rounding-to-nearest in integer division:
    #   v = (acc + kernel_sum//2) // kernel_sum
    half = kernel_sum // 2

    for y in range(H):
        for x in range(W):
            acc0 = 0
            acc1 = 0
            acc2 = 0

            for dy, dx, w in taps:
                yy = _reflect_index(y + dy, H)
                xx = _reflect_index(x + dx, W)
                base = (yy * W + xx) * 3

                px0 = raw[base + 0]
                px1 = raw[base + 1]
                px2 = raw[base + 2]

                acc0 += px0 * w
                acc1 += px1 * w
                acc2 += px2 * w

            v0 = (acc0 + half) // kernel_sum
            v1 = (acc1 + half) // kernel_sum
            v2 = (acc2 + half) // kernel_sum

            if v0 > 255: v0 = 255
            if v1 > 255: v1 = 255
            if v2 > 255: v2 = 255
            if v0 < 0: v0 = 0
            if v1 < 0: v1 = 0
            if v2 < 0: v2 = 0

            base_o = (y * W + x) * 3
            out[base_o + 0] = v0
            out[base_o + 1] = v1
            out[base_o + 2] = v2

    return bytes(out)

def _u8_rgb_to_q12_12_u24_payload(raw_u8_rgb: bytes, W: int, H: int) -> bytes:
    # Map u8 integer to signed Q12.12: v_q = v * 4096
    # Then store biased in u24: u = v_q + BIAS_INT
    out = bytearray(W * H * 3 * 3)
    o = 0
    for b in raw_u8_rgb:
        v_q = int(b) * Q_SCALE
        u = v_q + BIAS_INT
        if u < 0:
            u = 0
        elif u > U24_MAX:
            u = U24_MAX

        # u24 little-endian
        out[o] = u & 0xFF
        out[o + 1] = (u >> 8) & 0xFF
        out[o + 2] = (u >> 16) & 0xFF
        o += 3
    return bytes(out)

def multiply_and_accumulate_low_pass_filter(in_dir: str, kernel_size: int = 5, out_dir: str | None = None) -> str:
    K, kernel_sum = _KERNELS[kernel_size]

    names = [n for n in os.listdir(in_dir) if n.lower().endswith(".imgb")]
    names.sort(key=_natural_key)

    for name in names:
        src = os.path.join(in_dir, name)
        dst = os.path.join(out_dir, name)

        with open(src, "rb") as f:
            blob = f.read()

        W, H, C, dtype_code, payload = imgb_parse(blob)

        if dtype_code != 1 or C != 3:
            raise ValueError(f"cross expects input u8 RGB IMGB. Got dtype_code={dtype_code}, C={C} in {src}")

        blurred_u8 = _convolve_u8_rgb(payload, W, H, K, kernel_sum)
        out_payload = _u8_rgb_to_q12_12_u24_payload(blurred_u8, W, H)

        out_blob = imgb_make(W=W, H=H, C=3, dtype_code=4, payload=out_payload)
        save_imgb(out_blob, dst)

    return out_dir
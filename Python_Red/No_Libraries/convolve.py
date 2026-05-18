# convolve.py
# Final post-disparity 2D low-pass convolution.
#
# This module applies a fixed 7x7 weighted low-pass filter to the final fused
# single-channel disparity/depth map after confidence fusion.
#
# INPUT:
#   IMGB dtype_code=4, C=1, biased signed Q12.12
#
# OUTPUT:
#   IMGB dtype_code=4, C=1, biased signed Q12.12
#
# Important:
#   This module preserves signed disparity values.
#   Negative disparity is NOT clamped here.
#   Visual clamping/normalisation should only happen in bin_to_png.py.
#
# NO numpy, NO imageio. Pure stdlib.

from utils import (
    BIAS_INT,
    U24_MAX,
    imgb_make,
    imgb_parse,
)


# ----------------------------------------------------------
# Fixed 7x7 low-pass kernel
# ----------------------------------------------------------

_KERNEL_7 = [
    [1, 1, 2, 2, 2, 1, 1],
    [1, 2, 4, 4, 4, 2, 1],
    [2, 4, 4, 4, 4, 4, 2],
    [2, 4, 4, 4, 4, 4, 2],
    [2, 4, 4, 4, 4, 4, 2],
    [1, 2, 4, 4, 4, 2, 1],
    [1, 1, 2, 2, 2, 1, 1],
]

_KERNEL_SUM = 128


# ----------------------------------------------------------
# u24 helpers
# ----------------------------------------------------------

def _u24_read(payload: bytes, byte_off: int) -> int:
    return (
        payload[byte_off]
        | (payload[byte_off + 1] << 8)
        | (payload[byte_off + 2] << 16)
    )


def _u24_write(out: bytearray, byte_off: int, u: int) -> None:
    u &= 0xFFFFFF

    out[byte_off] = u & 0xFF
    out[byte_off + 1] = (u >> 8) & 0xFF
    out[byte_off + 2] = (u >> 16) & 0xFF


def _bias_q12_12(q: int) -> int:
    """
    Convert signed Q12.12 integer to biased u24.

    This does not clamp negative disparity to zero.
    It only saturates if the signed value exceeds the representable
    biased u24 storage range.
    """

    u = int(q) + BIAS_INT

    if u < 0:
        return 0

    if u > U24_MAX:
        return U24_MAX

    return u


# ----------------------------------------------------------
# Boundary handling
# ----------------------------------------------------------

def _reflect_index(i: int, n: int) -> int:
    """
    Reflect boundary index.

    Example for n = 5:
        -1 -> 1
         5 -> 3

    This avoids introducing zero-padding artefacts at the image boundary.
    """

    if n <= 1:
        return 0

    while i < 0 or i >= n:
        if i < 0:
            i = -i
        else:
            i = (2 * n - 2) - i

    return i


# ----------------------------------------------------------
# Fixed 7x7 final 2D low-pass on single-channel Q12.12 IMGB
# ----------------------------------------------------------

def low_pass_q12_12_single_channel(imgb_blob: bytes) -> bytes:
    """
    Apply a fixed 7x7 low-pass filter to a single-channel biased signed Q12.12 IMGB.

    Intended use:
        Z_conf_raw -> fixed 7x7 low-pass -> Z_conf

    Signed disparity is preserved:
        positive values remain positive
        zero remains zero
        negative values remain negative unless storage saturation is reached

    Time complexity:
        The outer loops visit W * H pixels.
        For every pixel, the fixed tap loop visits 49 values.
        Overall complexity is O(W * H).
    """

    W, H, C, dtype_code, payload = imgb_parse(imgb_blob)

    if dtype_code != 4 or C != 1:
        raise ValueError(
            f"low_pass_q12_12_single_channel expects dtype_code=4, C=1. "
            f"Got dtype_code={dtype_code}, C={C}"
        )

    taps = []

    for dy in range(7):
        row = _KERNEL_7[dy]
        ddy = dy - 3

        for dx in range(7):
            taps.append((ddy, dx - 3, row[dx]))

    out_payload = bytearray(W * H * 3)
    half = _KERNEL_SUM // 2

    for y in range(H):
        for x in range(W):
            acc = 0

            for dy, dx, weight in taps:
                yy = _reflect_index(y + dy, H)
                xx = _reflect_index(x + dx, W)

                src_off = (yy * W + xx) * 3
                sample_q = _u24_read(payload, src_off) - BIAS_INT

                acc += sample_q * weight

            if acc >= 0:
                out_q = (acc + half) // _KERNEL_SUM
            else:
                out_q = -(((-acc) + half) // _KERNEL_SUM)

            dst_off = (y * W + x) * 3
            _u24_write(out_payload, dst_off, _bias_q12_12(out_q))

    return imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(out_payload))
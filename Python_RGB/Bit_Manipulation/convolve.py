# convolve.py
# Final post-disparity 2D low-pass convolution.
#
# Bit-manipulative RGB-compatible version.
#
# This module applies a fixed custom 7x7 weighted low-pass filter to the final
# fused single-channel disparity/depth map after RGB confidence/disparity fusion.
#
# Even in the RGB pipeline, the input here is single-channel:
#   RGB channels -> per-channel disparity/confidence -> RGB confidence fusion
#   -> one fused disparity map -> region filling -> this low-pass filter
#
# Kernel weights:
#   1, 2, and 4 only.
#
# Therefore:
#   multiply by 1 -> unchanged
#   multiply by 2 -> << 1
#   multiply by 4 -> << 2
#   divide by 128 -> >> 7
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
# Fixed 7x7 low-pass kernel as exponent map
# ----------------------------------------------------------
# Original weights:
#   1, 2, 4
#
# Exponent map:
#   0 -> weight 1 -> sample << 0
#   1 -> weight 2 -> sample << 1
#   2 -> weight 4 -> sample << 2
#
# Kernel sum = 128 = 1 << 7

_KERNEL_EXP_7 = [
    [0, 0, 1, 1, 1, 0, 0],
    [0, 1, 2, 2, 2, 1, 0],
    [1, 2, 2, 2, 2, 2, 1],
    [1, 2, 2, 2, 2, 2, 1],
    [1, 2, 2, 2, 2, 2, 1],
    [0, 1, 2, 2, 2, 1, 0],
    [0, 0, 1, 1, 1, 0, 0],
]

_KERNEL_SHIFT = 7


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
    u &= U24_MAX

    out[byte_off] = u & 0xFF
    out[byte_off + 1] = (u >> 8) & 0xFF
    out[byte_off + 2] = (u >> 16) & 0xFF


def _bias_q12_12(q: int) -> int:
    """
    Convert signed Q12.12 integer to biased u24.

    Negative disparity is preserved by the bias representation.
    This function only saturates if the signed value exceeds the representable
    biased u24 storage range.
    """

    u = int(q) + BIAS_INT

    if u < 0:
        return 0

    if u > U24_MAX:
        return U24_MAX

    return u


# ----------------------------------------------------------
# Bit-manipulative helpers
# ----------------------------------------------------------

def _mul3(x: int) -> int:
    """
    Compute x * 3 using shifts/adds:
        x * 3 = (x << 1) + x
    """

    return (x << 1) + x


def _round_shift_right_signed(value: int, shift: int) -> int:
    """
    Rounded signed division by 2^shift.

    Equivalent to:
        round(value / 2^shift)

    but implemented using shifts.

    For this convolution:
        shift = 7
        denominator = 128
    """

    half = 1 << (shift - 1)

    if value >= 0:
        return (value + half) >> shift

    return -(((-value) + half) >> shift)


def _reflect_index(i: int, n: int) -> int:
    """
    Reflect boundary index.

    Uses:
        2*n - 2 -> (n << 1) - 2

    Example for n = 5:
        -1 -> 1
         5 -> 3
    """

    if n <= 1:
        return 0

    high_reflect = (n << 1) - 2

    while i < 0 or i >= n:
        if i < 0:
            i = -i
        else:
            i = high_reflect - i

    return i


def _apply_weight_shift(sample_q: int, weight_exp: int) -> int:
    """
    Apply kernel weight using shifts.

    weight_exp:
        0 -> weight 1
        1 -> weight 2
        2 -> weight 4
    """

    if weight_exp == 0:
        return sample_q

    return sample_q << weight_exp


# ----------------------------------------------------------
# Fixed 7x7 final 2D low-pass on single-channel Q12.12 IMGB
# ----------------------------------------------------------

def low_pass_q12_12_single_channel(imgb_blob: bytes) -> bytes:
    """
    Apply a fixed custom 7x7 low-pass filter to a single-channel biased
    signed Q12.12 IMGB.

    Intended RGB-pipeline use:
        Z_conf_filled -> fixed 7x7 bit-manipulative low-pass -> Z_conf

    Signed disparity is preserved:
        positive values remain positive
        zero remains zero
        negative values remain negative unless storage saturation is reached

    Time complexity:
        The outer loops visit W * H pixels.
        For every pixel, the fixed tap loop visits 49 values.
        Overall complexity is O(W * H), because the 7x7 kernel is fixed.
    """

    W, H, C, dtype_code, payload = imgb_parse(imgb_blob)

    if dtype_code != 4 or C != 1:
        raise ValueError(
            f"low_pass_q12_12_single_channel expects dtype_code=4, C=1. "
            f"Got dtype_code={dtype_code}, C={C}"
        )

    # ------------------------------------------------------
    # Precompute byte row offsets.
    #
    # row byte offset = y * W * 3
    #                 = y * (W * 3)
    #
    # W * 3 is implemented as:
    #   (W << 1) + W
    #
    # Per-row multiplication is avoided by repeated addition.
    # ------------------------------------------------------

    row_stride = _mul3(W)

    row_offsets = [0] * H
    offset = 0

    for y in range(H):
        row_offsets[y] = offset
        offset += row_stride

    # ------------------------------------------------------
    # Precompute x byte offsets.
    #
    # x byte offset = x * 3
    #               = (x << 1) + x
    # ------------------------------------------------------

    x_offsets = [0] * W

    for x in range(W):
        x_offsets[x] = _mul3(x)

    # ------------------------------------------------------
    # Precompute reflected neighbour coordinates.
    #
    # This removes repeated boundary reflection from the inner
    # 7x7 tap loop.
    # ------------------------------------------------------

    y_reflect = [[0] * 7 for _ in range(H)]
    x_reflect = [[0] * 7 for _ in range(W)]

    for y in range(H):
        for ky in range(7):
            y_reflect[y][ky] = _reflect_index(y + ky - 3, H)

    for x in range(W):
        for kx in range(7):
            x_reflect[x][kx] = _reflect_index(x + kx - 3, W)

    out_payload = bytearray(row_stride * H)

    for y in range(H):
        dst_row_base = row_offsets[y]
        y_neighbours = y_reflect[y]

        for x in range(W):
            acc = 0
            x_neighbours = x_reflect[x]

            # 7x7 convolution.
            # Kernel multiply is implemented as left shift by exponent.
            for ky in range(7):
                yy = y_neighbours[ky]
                src_row_base = row_offsets[yy]
                kernel_row = _KERNEL_EXP_7[ky]

                for kx in range(7):
                    xx = x_neighbours[kx]
                    src_off = src_row_base + x_offsets[xx]

                    sample_q = _u24_read(payload, src_off) - BIAS_INT
                    acc += _apply_weight_shift(sample_q, kernel_row[kx])

            # Divide by kernel sum:
            #   kernel sum = 128 = 1 << 7
            # so use rounded signed right shift.
            out_q = _round_shift_right_signed(acc, _KERNEL_SHIFT)

            dst_off = dst_row_base + x_offsets[x]
            _u24_write(out_payload, dst_off, _bias_q12_12(out_q))

    return imgb_make(
        W=W,
        H=H,
        C=1,
        dtype_code=4,
        payload=bytes(out_payload)
    )
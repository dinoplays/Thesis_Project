# region_filling.py
# Iterative confidence-guided region filling for fused disparity maps.
#
# Bit-manipulative version.
#
# INPUTS:
#   Z_conf_raw: IMGB dtype_code=4, C=1, biased signed Q12.12 disparity
#   C_avg:      IMGB dtype_code=4, C=1, biased signed Q12.12 confidence
#
# OUTPUT:
#   Z_conf_filled: IMGB dtype_code=4, C=1, biased signed Q12.12 disparity
#
# Behaviour:
#   - Initial valid pixels are those with confidence >= confidence_threshold.
#   - Invalid pixels are initially treated as empty.
#   - Iteratively scans the image.
#   - An invalid pixel can be filled once at least one left/right/up/down
#     neighbour is already valid.
#   - The fill value is the average of valid disparity pixels in a 5x5 window.
#   - The average divides only by the number of valid pixels in the 5x5 window.
#   - Filled pixels become valid for later iterations.
#
# Bit-manipulative changes:
#   - x * 3 is replaced with (x << 1) + x.
#   - y * W is avoided using precomputed row offsets.
#   - W * H is avoided using accumulated row offsets.
#   - division by 2 is replaced with >> 1.
#   - threshold 0.5 / 1.0 / 1.5 / 2.0 can be generated using shifts.
#   - average division by count 1..25 uses a Q16 reciprocal lookup table.
#   - multiply by reciprocal is implemented using shift-add constant multiply.
#
# RGB note:
#   Even in the RGB pipeline, region filling operates after RGB fusion.
#   Therefore the input/output here is still a single-channel fused disparity map.
#
# NO numpy, NO imageio. Pure stdlib.

from utils import (
    BIAS_INT,
    Q_SCALE,
    U24_MAX,
    imgb_make,
    imgb_parse,
)


# ----------------------------------------------------------
# Reciprocal lookup table for count = 1..25
# ----------------------------------------------------------
# recip[count] = round((1 << 16) / count)
#
# Average:
#   avg ~= round(total / count)
#       ~= round((total * recip[count]) >> 16)
#
# The constant multiply is implemented with shift-add in _mul_const_shift_add.

_RECIP_Q16 = [
    0,
    65536,
    32768,
    21845,
    16384,
    13107,
    10923,
    9362,
    8192,
    7282,
    6554,
    5958,
    5461,
    5041,
    4681,
    4369,
    4096,
    3855,
    3641,
    3449,
    3277,
    3121,
    2979,
    2849,
    2731,
    2621,
]

_RECIP_FRAC_BITS = 16


# ----------------------------------------------------------
# Bit-manipulative helpers
# ----------------------------------------------------------

def _mul3(x: int) -> int:
    """
    x * 3 using shifts/adds:
        x * 3 = (x << 1) + x
    """

    return (x << 1) + x


def _mul_const_shift_add(value: int, const: int) -> int:
    """
    Multiply signed value by a positive integer constant using shift-add.

    This avoids using the '*' operator for the reciprocal multiply.
    """

    if const == 0:
        return 0

    if value == 0:
        return 0

    negative = value < 0

    if negative:
        value = -value

    acc = 0
    shift = 0
    c = const

    while c > 0:
        if c & 1:
            acc += value << shift

        c >>= 1
        shift += 1

    if negative:
        return -acc

    return acc


def _round_shift_right_signed(value: int, shift: int) -> int:
    """
    Rounded signed division by 2^shift using shifts.

    Equivalent to:
        round(value / (1 << shift))
    """

    half = 1 << (shift - 1)

    if value >= 0:
        return (value + half) >> shift

    return -(((-value) + half) >> shift)


def _average_by_count_1_to_25(total: int, count: int) -> int:
    """
    Average total/count for count in [1, 25].

    Uses:
        reciprocal lookup table in Q16
        shift-add multiply by reciprocal
        rounded signed right shift by 16

    This replaces the non-bit-manipulative:
        total // count
    """

    if count <= 0:
        return 0

    if count >= len(_RECIP_Q16):
        raise ValueError("count must be in range 1..25 for 5x5 region filling")

    recip = _RECIP_Q16[count]
    product = _mul_const_shift_add(total, recip)

    return _round_shift_right_signed(product, _RECIP_FRAC_BITS)


def _threshold_to_q12_12(confidence_threshold: float) -> int:
    """
    Convert common confidence thresholds to Q12.12 using shifts.

    Common cases:
        0.5 -> 1 << 11
        1.0 -> 1 << 12
        1.5 -> (1 << 12) + (1 << 11)
        2.0 -> 1 << 13

    Fallback keeps compatibility for unusual thresholds.
    """

    if confidence_threshold == 0.5:
        return Q_SCALE >> 1

    if confidence_threshold == 1.0:
        return Q_SCALE

    if confidence_threshold == 1.5:
        return Q_SCALE + (Q_SCALE >> 1)

    if confidence_threshold == 2.0:
        return Q_SCALE << 1

    # Fallback only for non-standard thresholds.
    return int(float(confidence_threshold) * float(Q_SCALE) + 0.5)


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

    Signed disparity is preserved. Negative values are not clamped to zero.
    Saturation only occurs if the signed value cannot be represented in the
    biased u24 storage range.
    """

    u = int(q) + BIAS_INT

    if u < 0:
        return 0

    if u > U24_MAX:
        return U24_MAX

    return u


# ----------------------------------------------------------
# Offset helpers
# ----------------------------------------------------------

def _make_row_offsets(W: int, H: int) -> list[int]:
    """
    Build row offsets without using y * W inside image loops.

    row_offsets[y] = y * W, generated by repeated addition.
    """

    row_offsets = [0] * H
    offset = 0

    for y in range(H):
        row_offsets[y] = offset
        offset += W

    return row_offsets


def _make_byte_offsets(n: int) -> list[int]:
    """
    Build byte offsets for u24 samples.

    byte_offsets[i] = i * 3 = (i << 1) + i
    """

    byte_offsets = [0] * n

    for i in range(n):
        byte_offsets[i] = _mul3(i)

    return byte_offsets


def _num_samples_from_row_offsets(W: int, H: int, row_offsets: list[int]) -> int:
    """
    Compute n = W * H without using multiplication.

    If H > 0:
        n = row_offsets[H - 1] + W
    """

    if H <= 0:
        return 0

    return row_offsets[H - 1] + W


# ----------------------------------------------------------
# Parsing helpers
# ----------------------------------------------------------

def _decode_single_channel_q12_12(imgb_blob: bytes, label: str):
    W, H, C, dtype_code, payload = imgb_parse(imgb_blob)

    if dtype_code != 4 or C != 1:
        raise ValueError(
            f"{label} expects dtype_code=4, C=1. "
            f"Got dtype_code={dtype_code}, C={C}"
        )

    row_offsets = _make_row_offsets(W, H)
    n = _num_samples_from_row_offsets(W, H, row_offsets)
    byte_offsets = _make_byte_offsets(n)

    out = [0] * n

    for i in range(n):
        out[i] = _u24_read(payload, byte_offsets[i]) - BIAS_INT

    return W, H, out, row_offsets, byte_offsets


def _encode_single_channel_q12_12(
    values_q: list[int],
    W: int,
    H: int,
    row_offsets: list[int],
    byte_offsets: list[int],
) -> bytes:
    n = _num_samples_from_row_offsets(W, H, row_offsets)

    if len(values_q) != n:
        raise ValueError(
            f"values_q length mismatch: got {len(values_q)}, expected {n}"
        )

    payload = bytearray(_mul3(n))

    for i, q in enumerate(values_q):
        _u24_write(payload, byte_offsets[i], _bias_q12_12(q))

    return imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(payload))


# ----------------------------------------------------------
# Region filling helpers
# ----------------------------------------------------------

def _has_valid_lrup(
    valid: list[bool],
    row_offsets: list[int],
    W: int,
    H: int,
    x: int,
    y: int,
) -> bool:
    """
    Check left/right/up/down valid neighbours.
    """

    row_base = row_offsets[y]

    if x > 0:
        if valid[row_base + x - 1]:
            return True

    if x + 1 < W:
        if valid[row_base + x + 1]:
            return True

    if y > 0:
        if valid[row_offsets[y - 1] + x]:
            return True

    if y + 1 < H:
        if valid[row_offsets[y + 1] + x]:
            return True

    return False


def _average_valid_5x5(
    values_q: list[int],
    valid: list[bool],
    row_offsets: list[int],
    W: int,
    H: int,
    x: int,
    y: int,
):
    """
    Average valid disparity values inside a 5x5 window centred on (x, y).

    The divisor is count in [1, 25].
    Since count is not generally a power of two, this uses a Q16 reciprocal
    lookup table and shift-add constant multiply.
    """

    total = 0
    count = 0

    y_start = y - 2
    y_end = y + 2

    if y_start < 0:
        y_start = 0

    if y_end >= H:
        y_end = H - 1

    x_start = x - 2
    x_end = x + 2

    if x_start < 0:
        x_start = 0

    if x_end >= W:
        x_end = W - 1

    yy = y_start

    while yy <= y_end:
        row_base = row_offsets[yy]

        xx = x_start

        while xx <= x_end:
            idx = row_base + xx

            if valid[idx]:
                total += values_q[idx]
                count += 1

            xx += 1

        yy += 1

    if count == 0:
        return False, 0

    return True, _average_by_count_1_to_25(total, count)


# ----------------------------------------------------------
# Public function
# ----------------------------------------------------------

def fill_regions_q12_12_single_channel(
    disparity_imgb: bytes,
    confidence_imgb: bytes,
    confidence_threshold: float = 1.5,
    max_iterations: int | None = None,
) -> bytes:
    """
    Iteratively fill low-confidence disparity regions.

    Initial valid mask:
        confidence >= confidence_threshold

    Filling rule:
        For every invalid pixel, wait until at least one LRUD neighbour is valid.
        Then fill using the average of valid disparity values inside a 5x5 window.
        Filled pixels become valid for the next iteration.

    Output:
        Returns an IMGB byte blob containing the filled disparity map.
        In main.py, save this as:
            Z_conf_filled.imgb

    Notes:
        - Negative disparity values are preserved if they are valid.
        - Invalid pixels that never become fillable remain zero.
        - This function modifies only the disparity output, not the confidence map.

    Time complexity:
        Let image size be W x H and max iterations be I.
        Each iteration scans W * H pixels.
        Each fill candidate checks a fixed 5x5 window.
        Overall complexity is O(I * W * H), since the 5x5 window is fixed.
    """

    W_z, H_z, disparity_q, row_offsets_z, byte_offsets_z = _decode_single_channel_q12_12(
        disparity_imgb,
        "disparity_imgb"
    )

    W_c, H_c, confidence_q, _row_offsets_c, _byte_offsets_c = _decode_single_channel_q12_12(
        confidence_imgb,
        "confidence_imgb"
    )

    if W_z != W_c or H_z != H_c:
        raise ValueError(
            f"Shape mismatch: disparity is {W_z}x{H_z}, confidence is {W_c}x{H_c}"
        )

    W = W_z
    H = H_z
    row_offsets = row_offsets_z
    byte_offsets = byte_offsets_z

    n = _num_samples_from_row_offsets(W, H, row_offsets)
    threshold_q = _threshold_to_q12_12(confidence_threshold)

    valid = [False] * n
    filled_q = [0] * n

    for i in range(n):
        if confidence_q[i] >= threshold_q:
            valid[i] = True
            filled_q[i] = disparity_q[i]

    if max_iterations is None:
        max_iterations = W + H

    for _iteration in range(max_iterations):
        old_valid = valid[:]
        old_values = filled_q[:]

        changed = False

        y = 0

        while y < H:
            row_base = row_offsets[y]
            x = 0

            while x < W:
                idx = row_base + x

                if old_valid[idx]:
                    x += 1
                    continue

                if not _has_valid_lrup(
                    old_valid,
                    row_offsets,
                    W,
                    H,
                    x,
                    y
                ):
                    x += 1
                    continue

                has_average, avg_q = _average_valid_5x5(
                    old_values,
                    old_valid,
                    row_offsets,
                    W,
                    H,
                    x,
                    y
                )

                if not has_average:
                    x += 1
                    continue

                filled_q[idx] = avg_q
                valid[idx] = True
                changed = True

                x += 1

            y += 1

        if not changed:
            break

    return _encode_single_channel_q12_12(
        filled_q,
        W,
        H,
        row_offsets,
        byte_offsets
    )
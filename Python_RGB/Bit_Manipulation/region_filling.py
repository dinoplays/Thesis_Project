# region_filling.py
# Iterative confidence-guided region filling for fused disparity maps.
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
# NO numpy, NO imageio. Pure stdlib.

from utils import (
    BIAS_INT,
    Q_SCALE,
    U24_MAX,
    imgb_make,
    imgb_parse,
)


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


def _round_div_signed(num: int, den: int) -> int:
    """
    Round signed integer division to nearest integer.
    """

    if den <= 0:
        raise ValueError("den must be positive")

    half = den // 2

    if num >= 0:
        return (num + half) // den

    return -(((-num) + half) // den)


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

    n = W * H
    out = [0] * n

    for i in range(n):
        out[i] = _u24_read(payload, i * 3) - BIAS_INT

    return W, H, out


def _encode_single_channel_q12_12(values_q: list[int], W: int, H: int) -> bytes:
    if len(values_q) != W * H:
        raise ValueError(
            f"values_q length mismatch: got {len(values_q)}, expected {W * H}"
        )

    payload = bytearray(W * H * 3)

    for i, q in enumerate(values_q):
        _u24_write(payload, i * 3, _bias_q12_12(q))

    return imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(payload))


# ----------------------------------------------------------
# Region filling helpers
# ----------------------------------------------------------

def _has_valid_lrup(valid: list[bool], W: int, H: int, x: int, y: int) -> bool:
    """
    Check left/right/up/down valid neighbours.
    """

    if x > 0:
        if valid[y * W + (x - 1)]:
            return True

    if x + 1 < W:
        if valid[y * W + (x + 1)]:
            return True

    if y > 0:
        if valid[(y - 1) * W + x]:
            return True

    if y + 1 < H:
        if valid[(y + 1) * W + x]:
            return True

    return False


def _average_valid_5x5(values_q: list[int], valid: list[bool], W: int, H: int, x: int, y: int):
    """
    Average valid disparity values inside a 5x5 window centred on (x, y).

    Returns:
        (has_value, average_q)
    """

    total = 0
    count = 0

    for yy in range(y - 2, y + 3):
        if yy < 0:
            continue

        if yy >= H:
            continue

        row_base = yy * W

        for xx in range(x - 2, x + 3):
            if xx < 0:
                continue

            if xx >= W:
                continue

            idx = row_base + xx

            if valid[idx]:
                total += values_q[idx]
                count += 1

    if count == 0:
        return False, 0

    return True, _round_div_signed(total, count)


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

    W_z, H_z, disparity_q = _decode_single_channel_q12_12(
        disparity_imgb,
        "disparity_imgb"
    )

    W_c, H_c, confidence_q = _decode_single_channel_q12_12(
        confidence_imgb,
        "confidence_imgb"
    )

    if W_z != W_c or H_z != H_c:
        raise ValueError(
            f"Shape mismatch: disparity is {W_z}x{H_z}, confidence is {W_c}x{H_c}"
        )

    W = W_z
    H = H_z
    n = W * H

    threshold_q = int(float(confidence_threshold) * float(Q_SCALE) + 0.5)

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

        for y in range(H):
            row_base = y * W

            for x in range(W):
                idx = row_base + x

                if old_valid[idx]:
                    continue

                if not _has_valid_lrup(old_valid, W, H, x, y):
                    continue

                has_average, avg_q = _average_valid_5x5(
                    old_values,
                    old_valid,
                    W,
                    H,
                    x,
                    y
                )

                if not has_average:
                    continue

                filled_q[idx] = avg_q
                valid[idx] = True
                changed = True

        if not changed:
            break

    return _encode_single_channel_q12_12(filled_q, W, H)
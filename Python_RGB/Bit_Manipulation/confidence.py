# confidence.py
# Confidence from full EPI gradient magnitude approximation using PRECOMPUTED EPIs (IMGB blobs).
# Also returns angular and spatial diffs so disparity does not recompute them.
#
# Bit-manipulative 3x3 Sobel-kernel version:
#   - No sqrt.
#   - Uses hardware-friendly max-min approximation:
#       sqrt(a^2 + b^2) ~= max(|a|, |b|) + (3/8)min(|a|, |b|)
#   - 3/8 is implemented as (min >> 2) + (min >> 3).
#   - Uses 3x3 Sobel-style derivative kernels:
#
#       Spatial derivative L_s / L_t:
#           [ 1  0 -1 ]
#           [ 2  0 -2 ]
#           [ 1  0 -1 ]
#
#       Angular derivative L_u / L_v:
#           [ 1  2  1 ]
#           [ 0  0  0 ]
#           [-1 -2 -1 ]
#
#   - Kernel multiply by 2 is implemented with << 1.
#   - Sobel normalisation by 8 is implemented with signed rounded >> 3.
#   - Confidence average over 7 angular rows uses Q16 reciprocal shift-add.
#   - RGB confidence average over 3 maps uses Q16 reciprocal shift-add.
#
# Assumptions:
#   - Image W = H = WH_SIZE = 512 (= 1<<WH_SHIFT)
#   - Angular A = EPI_UV = 9
#   - epi_h_imgb[y] is IMGB with (W=512, H=A=9, C=3, dtype_code=4)
#   - epi_v_imgb[x] is IMGB with (W=512, H=A=9, C=3, dtype_code=4)
#
# Outputs:
#   C_h_imgb : IMGB (W x H, C=1, dtype_code=4) confidence horizontal
#   C_v_imgb : IMGB (W x H, C=1, dtype_code=4) confidence vertical
#   dL_du_h  : list[bytes] IMGB per-row (A x W, C=1, dtype_code=4)
#   dL_dv_v  : list[bytes] IMGB per-col (A x H, C=1, dtype_code=4)
#   dL_ds_h  : list[bytes] IMGB per-row (A x W, C=1, dtype_code=4)
#   dL_dt_v  : list[bytes] IMGB per-col (A x H, C=1, dtype_code=4)

# image samples: 512*512 = 1<<(9+9) = 262144
N_IMG = 262144

# output payload bytes for C maps: N_IMG samples * 3 bytes
OUT_IMG_BYTES = 786432

# one single-channel derivative row: 512 samples * 3 bytes/sample
DIFF_ROW_BYTES = 1536

# valid central angular samples for A=9 are 1..7
DENOMINATOR = 7

# Sobel kernel normalisation: 8 = 1 << 3
SOBEL_SHIFT = 3

# Q16 reciprocal constants:
#   round((1 << 16) / 7) = 9362
#   round((1 << 16) / 3) = 21845
RECIP_7_Q16 = 9362
RECIP_3_Q16 = 21845
RECIP_FRAC_BITS = 16

from utils import (
    imbg_parse_payload,
    imgb_make,
    BIAS_INT,
    U24_MAX,
    WH_SHIFT,
    WH_SIZE,
    EPI_UV
)

from EPIs import (
    BYTES_PER_SAMPLE,
    BYTES_PER_PIXEL_RGB,
    EPI_ROW_BYTES,
    ROW_BYTES_X3 as DIFF_PAY_BYTES
)


# -------------------------------------------------------------------------
# u24 helpers
# -------------------------------------------------------------------------

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


def _bias_from_q12_12(q: int) -> int:
    u = int(q) + BIAS_INT

    if u < 0:
        return 0

    if u > U24_MAX:
        return U24_MAX

    return u


# -------------------------------------------------------------------------
# Bit-manipulative integer helpers
# -------------------------------------------------------------------------

def _abs_i32(x: int) -> int:
    if x < 0:
        return -x

    return x


def _round_div2(x: int) -> int:
    """
    Round-to-nearest for /2 in signed integer domain.

    Implemented using signed arithmetic right shift.
    """

    if x >= 0:
        return (x + 1) >> 1

    return -(((-x) + 1) >> 1)


def _round_shift_right_signed(value: int, shift: int) -> int:
    """
    Rounded signed division by 2^shift.

    Python >> is arithmetic for negative integers, but this form gives explicit
    round-to-nearest behaviour for both signs.
    """

    half = 1 << (shift - 1)

    if value >= 0:
        return (value + half) >> shift

    return -(((-value) + half) >> shift)


def _mul_const_shift_add(value: int, const: int) -> int:
    """
    Multiply signed value by positive integer const using shift-add.

    This avoids using the '*' operator for reciprocal multiplication.
    """

    if value == 0:
        return 0

    if const == 0:
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


def _round_div7_q16(value: int) -> int:
    """
    Approximate rounded value / 7 using Q16 reciprocal and shift-add multiply.

    Used for confidence averaging across the 7 valid angular rows.
    """

    product = _mul_const_shift_add(value, RECIP_7_Q16)
    return _round_shift_right_signed(product, RECIP_FRAC_BITS)


def _round_div3_q16(value: int) -> int:
    """
    Approximate rounded value / 3 using Q16 reciprocal and shift-add multiply.

    Used for RGB confidence averaging.
    """

    product = _mul_const_shift_add(value, RECIP_3_Q16)
    return _round_shift_right_signed(product, RECIP_FRAC_BITS)


def _gradient_magnitude_approx_q12(a_q12: int, b_q12: int) -> int:
    """
    Hardware-friendly approximation of sqrt(a^2 + b^2).

    approx = max(|a|, |b|) + (3/8)min(|a|, |b|)
           = max_abs + (min_abs >> 2) + (min_abs >> 3)

    Inputs and output are Q12.12 integer magnitudes.
    """

    abs_a = _abs_i32(a_q12)
    abs_b = _abs_i32(b_q12)

    if abs_a >= abs_b:
        max_abs = abs_a
        min_abs = abs_b
    else:
        max_abs = abs_b
        min_abs = abs_a

    return max_abs + (min_abs >> 2) + (min_abs >> 3)


# -------------------------------------------------------------------------
# 3x3 Sobel derivative helpers
# -------------------------------------------------------------------------

def _sobel_spatial_q12(
    pay: bytes,
    row_m: int,
    row_0: int,
    row_p: int,
    pos_m: int,
    pos_0: int,
    pos_p: int,
    ch_off: int,
) -> int:
    """
    3x3 spatial derivative:

        [ 1  0 -1 ]
        [ 2  0 -2 ]
        [ 1  0 -1 ]

    Uses shift for weight 2 and signed rounded >> 3 for divide-by-8.
    """

    tl = _u24_read(pay, row_m + pos_m + ch_off) - BIAS_INT
    tr = _u24_read(pay, row_m + pos_p + ch_off) - BIAS_INT

    ml = _u24_read(pay, row_0 + pos_m + ch_off) - BIAS_INT
    mr = _u24_read(pay, row_0 + pos_p + ch_off) - BIAS_INT

    bl = _u24_read(pay, row_p + pos_m + ch_off) - BIAS_INT
    br = _u24_read(pay, row_p + pos_p + ch_off) - BIAS_INT

    acc = 0
    acc += tl
    acc -= tr
    acc += ml << 1
    acc -= mr << 1
    acc += bl
    acc -= br

    return _round_shift_right_signed(acc, SOBEL_SHIFT)


def _sobel_angular_q12(
    pay: bytes,
    row_m: int,
    row_0: int,
    row_p: int,
    pos_m: int,
    pos_0: int,
    pos_p: int,
    ch_off: int,
) -> int:
    """
    3x3 angular derivative:

        [ 1  2  1 ]
        [ 0  0  0 ]
        [-1 -2 -1 ]

    Uses shift for weight 2 and signed rounded >> 3 for divide-by-8.
    """

    tl = _u24_read(pay, row_m + pos_m + ch_off) - BIAS_INT
    tm = _u24_read(pay, row_m + pos_0 + ch_off) - BIAS_INT
    tr = _u24_read(pay, row_m + pos_p + ch_off) - BIAS_INT

    bl = _u24_read(pay, row_p + pos_m + ch_off) - BIAS_INT
    bm = _u24_read(pay, row_p + pos_0 + ch_off) - BIAS_INT
    br = _u24_read(pay, row_p + pos_p + ch_off) - BIAS_INT

    acc = 0
    acc += tl
    acc += tm << 1
    acc += tr
    acc -= bl
    acc -= bm << 1
    acc -= br

    return _round_shift_right_signed(acc, SOBEL_SHIFT)


# -------------------------------------------------------------------------
# Core
# -------------------------------------------------------------------------

def compute_from_epis_with_diffs(epi_h_imgb, epi_v_imgb, channel=None):
    ch = 0 if channel is None else int(channel)

    # ch*3, using shifts/adds.
    # channel 0 -> red, channel 1 -> green, channel 2 -> blue.
    CH_OFF = (ch << 1) + ch

    # Precompute EPI input row bases and derivative output row bases.
    epi_row_bases = [0] * EPI_UV
    diff_row_bases = [0] * EPI_UV

    epi_row_base = 0
    diff_row_base = 0

    a = 0
    while a < EPI_UV:
        epi_row_bases[a] = epi_row_base
        diff_row_bases[a] = diff_row_base

        epi_row_base += EPI_ROW_BYTES
        diff_row_base += DIFF_ROW_BYTES
        a += 1

    # Precompute spatial byte positions x*9 for RGB EPI payloads.
    x9_offsets = [0] * WH_SIZE
    pos = 0

    x = 0
    while x < WH_SIZE:
        x9_offsets[x] = pos
        pos += BYTES_PER_PIXEL_RGB
        x += 1

    # Precompute output byte positions x*3 for single-channel derivative rows.
    x3_offsets = [0] * WH_SIZE
    pos = 0

    x = 0
    while x < WH_SIZE:
        x3_offsets[x] = pos
        pos += BYTES_PER_SAMPLE
        x += 1

    # ---------------------------------------------------------------------
    # Horizontal diffs + C_h
    # ---------------------------------------------------------------------

    dL_du_h = []
    dL_ds_h = []
    C_h_q = [0 for _ in range(N_IMG)]

    for y in range(WH_SIZE):
        pay = imbg_parse_payload(epi_h_imgb[y])

        out_du = bytearray(DIFF_PAY_BYTES)
        out_ds = bytearray(DIFF_PAY_BYTES)
        sum_mag = [0] * WH_SIZE

        a = 0
        while a < EPI_UV:
            out_row_base = diff_row_bases[a]

            o_du = out_row_base
            o_ds = out_row_base

            # 3x3 Sobel needs one angular neighbour above/below.
            if a == 0 or a == EPI_UV - 1:
                x = 0

                while x < WH_SIZE:
                    _u24_write(out_du, o_du, BIAS_INT)
                    _u24_write(out_ds, o_ds, BIAS_INT)

                    o_du += BYTES_PER_SAMPLE
                    o_ds += BYTES_PER_SAMPLE
                    x += 1

            else:
                row_m = epi_row_bases[a - 1]
                row_0 = epi_row_bases[a]
                row_p = epi_row_bases[a + 1]

                x = 0

                while x < WH_SIZE:
                    # 3x3 Sobel also needs one spatial neighbour left/right.
                    if x == 0 or x == WH_SIZE - 1:
                        dL_du = 0
                        dL_ds = 0
                    else:
                        pos_m = x9_offsets[x - 1]
                        pos_0 = x9_offsets[x]
                        pos_p = x9_offsets[x + 1]

                        dL_du = _sobel_angular_q12(
                            pay,
                            row_m,
                            row_0,
                            row_p,
                            pos_m,
                            pos_0,
                            pos_p,
                            CH_OFF
                        )

                        dL_ds = _sobel_spatial_q12(
                            pay,
                            row_m,
                            row_0,
                            row_p,
                            pos_m,
                            pos_0,
                            pos_p,
                            CH_OFF
                        )

                        sum_mag[x] += _gradient_magnitude_approx_q12(
                            dL_ds,
                            dL_du
                        )

                    _u24_write(
                        out_du,
                        o_du,
                        _bias_from_q12_12(dL_du)
                    )

                    _u24_write(
                        out_ds,
                        o_ds,
                        _bias_from_q12_12(dL_ds)
                    )

                    o_du += BYTES_PER_SAMPLE
                    o_ds += BYTES_PER_SAMPLE
                    x += 1

            a += 1

        row_base = y << WH_SHIFT

        x = 0
        while x < WH_SIZE:
            C_h_q[row_base + x] = _round_div7_q16(sum_mag[x])
            x += 1

        dL_du_h.append(
            imgb_make(
                W=WH_SIZE,
                H=EPI_UV,
                C=1,
                dtype_code=4,
                payload=bytes(out_du)
            )
        )

        dL_ds_h.append(
            imgb_make(
                W=WH_SIZE,
                H=EPI_UV,
                C=1,
                dtype_code=4,
                payload=bytes(out_ds)
            )
        )

    C_h_payload = bytearray(OUT_IMG_BYTES)

    o = 0
    i = 0

    while i < N_IMG:
        _u24_write(C_h_payload, o, _bias_from_q12_12(C_h_q[i]))

        o += BYTES_PER_SAMPLE
        i += 1

    C_h_imgb = imgb_make(
        W=WH_SIZE,
        H=WH_SIZE,
        C=1,
        dtype_code=4,
        payload=bytes(C_h_payload)
    )

    # ---------------------------------------------------------------------
    # Vertical diffs + C_v
    # ---------------------------------------------------------------------

    dL_dv_v = []
    dL_dt_v = []
    C_v_q = [0 for _ in range(N_IMG)]

    for x_img in range(WH_SIZE):
        pay = imbg_parse_payload(epi_v_imgb[x_img])

        out_dv = bytearray(DIFF_PAY_BYTES)
        out_dt = bytearray(DIFF_PAY_BYTES)
        sum_mag = [0] * WH_SIZE

        a = 0
        while a < EPI_UV:
            out_row_base = diff_row_bases[a]

            o_dv = out_row_base
            o_dt = out_row_base

            if a == 0 or a == EPI_UV - 1:
                y = 0

                while y < WH_SIZE:
                    _u24_write(out_dv, o_dv, BIAS_INT)
                    _u24_write(out_dt, o_dt, BIAS_INT)

                    o_dv += BYTES_PER_SAMPLE
                    o_dt += BYTES_PER_SAMPLE
                    y += 1

            else:
                row_m = epi_row_bases[a - 1]
                row_0 = epi_row_bases[a]
                row_p = epi_row_bases[a + 1]

                y = 0

                while y < WH_SIZE:
                    if y == 0 or y == WH_SIZE - 1:
                        dL_dv = 0
                        dL_dt = 0
                    else:
                        pos_m = x9_offsets[y - 1]
                        pos_0 = x9_offsets[y]
                        pos_p = x9_offsets[y + 1]

                        dL_dv = _sobel_angular_q12(
                            pay,
                            row_m,
                            row_0,
                            row_p,
                            pos_m,
                            pos_0,
                            pos_p,
                            CH_OFF
                        )

                        dL_dt = _sobel_spatial_q12(
                            pay,
                            row_m,
                            row_0,
                            row_p,
                            pos_m,
                            pos_0,
                            pos_p,
                            CH_OFF
                        )

                        sum_mag[y] += _gradient_magnitude_approx_q12(
                            dL_dt,
                            dL_dv
                        )

                    _u24_write(
                        out_dv,
                        o_dv,
                        _bias_from_q12_12(dL_dv)
                    )

                    _u24_write(
                        out_dt,
                        o_dt,
                        _bias_from_q12_12(dL_dt)
                    )

                    o_dv += BYTES_PER_SAMPLE
                    o_dt += BYTES_PER_SAMPLE
                    y += 1

            a += 1

        y = 0

        while y < WH_SIZE:
            C_v_q[(y << WH_SHIFT) + x_img] = _round_div7_q16(sum_mag[y])
            y += 1

        dL_dv_v.append(
            imgb_make(
                W=WH_SIZE,
                H=EPI_UV,
                C=1,
                dtype_code=4,
                payload=bytes(out_dv)
            )
        )

        dL_dt_v.append(
            imgb_make(
                W=WH_SIZE,
                H=EPI_UV,
                C=1,
                dtype_code=4,
                payload=bytes(out_dt)
            )
        )

    C_v_payload = bytearray(OUT_IMG_BYTES)

    o = 0
    i = 0

    while i < N_IMG:
        _u24_write(C_v_payload, o, _bias_from_q12_12(C_v_q[i]))

        o += BYTES_PER_SAMPLE
        i += 1

    C_v_imgb = imgb_make(
        W=WH_SIZE,
        H=WH_SIZE,
        C=1,
        dtype_code=4,
        payload=bytes(C_v_payload)
    )

    return C_h_imgb, C_v_imgb, dL_du_h, dL_dv_v, dL_ds_h, dL_dt_v


# -------------------------------------------------------------------------
# Fuse
# -------------------------------------------------------------------------

def fuse_avg(C_h_imgb: bytes, C_v_imgb: bytes) -> bytes:
    p1 = imbg_parse_payload(C_h_imgb)
    p2 = imbg_parse_payload(C_v_imgb)

    out = bytearray(OUT_IMG_BYTES)

    o = 0
    i3 = 0
    k = 0

    while k < N_IMG:
        a = _u24_read(p1, i3) - BIAS_INT
        b = _u24_read(p2, i3) - BIAS_INT

        avg = _round_div2(a + b)

        _u24_write(out, o, _bias_from_q12_12(avg))

        o += BYTES_PER_SAMPLE
        i3 += BYTES_PER_SAMPLE
        k += 1

    return imgb_make(
        W=WH_SIZE,
        H=WH_SIZE,
        C=1,
        dtype_code=4,
        payload=bytes(out)
    )


def fuse_avg_three(C_a_imgb: bytes, C_b_imgb: bytes, C_c_imgb: bytes) -> bytes:
    """
    Average three single-channel confidence maps in Q12.12.

    Used by the RGB architecture to produce a single compatibility/region-fill
    confidence map:
        C_avg_rgb = (C_avg_red + C_avg_green + C_avg_blue) / 3

    This is still bit-manipulative/fixed-point:
        division by 3 uses Q16 reciprocal shift-add.
    """

    p_a = imbg_parse_payload(C_a_imgb)
    p_b = imbg_parse_payload(C_b_imgb)
    p_c = imbg_parse_payload(C_c_imgb)

    out = bytearray(OUT_IMG_BYTES)

    o = 0
    i3 = 0
    k = 0

    while k < N_IMG:
        a = _u24_read(p_a, i3) - BIAS_INT
        b = _u24_read(p_b, i3) - BIAS_INT
        c = _u24_read(p_c, i3) - BIAS_INT

        avg = _round_div3_q16(a + b + c)

        _u24_write(out, o, _bias_from_q12_12(avg))

        o += BYTES_PER_SAMPLE
        i3 += BYTES_PER_SAMPLE
        k += 1

    return imgb_make(
        W=WH_SIZE,
        H=WH_SIZE,
        C=1,
        dtype_code=4,
        payload=bytes(out)
    )
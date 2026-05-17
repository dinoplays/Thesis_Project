# confidence.py
# Confidence from full EPI gradient magnitude approximation using PRECOMPUTED EPIs (IMGB blobs).
# Also returns angular and spatial diffs so disparity does not recompute them.
#
# Bit-manipulative version:
#   - No sqrt.
#   - Uses hardware-friendly max-min approximation:
#       sqrt(a^2 + b^2) ~= max(|a|, |b|) + (3/8)min(|a|, |b|)
#   - 3/8 is implemented as (min >> 2) + (min >> 3).
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
DEMONINATOR = 7
DEMONINATOR_HALF = 3

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
    return payload[byte_off] | (payload[byte_off + 1] << 8) | (payload[byte_off + 2] << 16)


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


def _abs_i32(x: int) -> int:
    if x < 0:
        return -x

    return x


def _round_div2(x: int) -> int:
    # Round-to-nearest for /2 in signed integer domain.
    if x >= 0:
        return (x + 1) >> 1

    return -(((-x) + 1) >> 1)


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
# Core
# -------------------------------------------------------------------------

def compute_from_epis_with_diffs(epi_h_imgb, epi_v_imgb, channel=None):
    ch = 0 if channel is None else int(channel)

    # ch*3, using shifts/adds.
    # channel 0 -> red, channel 1 -> green, channel 2 -> blue.
    CH_OFF = (ch << 1) + ch

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

        out_row_base = 0

        for a in range(EPI_UV):
            # IMPORTANT:
            # out_row_base is for single-channel output rows: 512*3 = 1536 bytes.
            # pay_row_base is for RGB EPI input rows: 512*9 = 4608 bytes.
            pay_row_base = a * EPI_ROW_BYTES

            o_du = out_row_base
            o_ds = out_row_base

            if a == 0 or a == EPI_UV - 1:
                x = 0
                while x < WH_SIZE:
                    dL_du = 0

                    if x == 0 or x == WH_SIZE - 1:
                        dL_ds = 0
                    else:
                        idx_m_s = pay_row_base + ((x - 1) * BYTES_PER_PIXEL_RGB) + CH_OFF
                        idx_p_s = pay_row_base + ((x + 1) * BYTES_PER_PIXEL_RGB) + CH_OFF

                        Lm_s = _u24_read(pay, idx_m_s) - BIAS_INT
                        Lp_s = _u24_read(pay, idx_p_s) - BIAS_INT

                        dL_ds = _round_div2(Lp_s - Lm_s)

                    _u24_write(out_du, o_du, BIAS_INT)
                    _u24_write(out_ds, o_ds, _bias_from_q12_12(dL_ds))

                    o_du += BYTES_PER_SAMPLE
                    o_ds += BYTES_PER_SAMPLE
                    x += 1

            else:
                a_m = a - 1
                a_p = a + 1

                pay_row_base_m = a_m * EPI_ROW_BYTES
                pay_row_base_p = a_p * EPI_ROW_BYTES

                x9 = 0
                x = 0

                while x < WH_SIZE:
                    # Angular derivative L_u = (L[a+1,x] - L[a-1,x]) / 2.
                    idx_m_u = pay_row_base_m + x9 + CH_OFF
                    idx_p_u = pay_row_base_p + x9 + CH_OFF

                    Lm_u = _u24_read(pay, idx_m_u) - BIAS_INT
                    Lp_u = _u24_read(pay, idx_p_u) - BIAS_INT

                    dL_du = _round_div2(Lp_u - Lm_u)

                    # Spatial derivative L_s = (L[a,x+1] - L[a,x-1]) / 2.
                    if x == 0 or x == WH_SIZE - 1:
                        dL_ds = 0
                    else:
                        idx_m_s = pay_row_base + ((x - 1) * BYTES_PER_PIXEL_RGB) + CH_OFF
                        idx_p_s = pay_row_base + ((x + 1) * BYTES_PER_PIXEL_RGB) + CH_OFF

                        Lm_s = _u24_read(pay, idx_m_s) - BIAS_INT
                        Lp_s = _u24_read(pay, idx_p_s) - BIAS_INT

                        dL_ds = _round_div2(Lp_s - Lm_s)

                    _u24_write(out_du, o_du, _bias_from_q12_12(dL_du))
                    _u24_write(out_ds, o_ds, _bias_from_q12_12(dL_ds))

                    sum_mag[x] += _gradient_magnitude_approx_q12(dL_ds, dL_du)

                    x9 += BYTES_PER_PIXEL_RGB
                    o_du += BYTES_PER_SAMPLE
                    o_ds += BYTES_PER_SAMPLE
                    x += 1

            out_row_base += DIFF_ROW_BYTES

        row_base = y << WH_SHIFT

        x = 0
        while x < WH_SIZE:
            C_h_q[row_base + x] = (sum_mag[x] + DEMONINATOR_HALF) // DEMONINATOR
            x += 1

        dL_du_h.append(imgb_make(W=WH_SIZE, H=EPI_UV, C=1, dtype_code=4, payload=bytes(out_du)))
        dL_ds_h.append(imgb_make(W=WH_SIZE, H=EPI_UV, C=1, dtype_code=4, payload=bytes(out_ds)))

    C_h_payload = bytearray(OUT_IMG_BYTES)

    o = 0
    i = 0
    while i < N_IMG:
        _u24_write(C_h_payload, o, _bias_from_q12_12(C_h_q[i]))
        o += BYTES_PER_SAMPLE
        i += 1

    C_h_imgb = imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(C_h_payload))

    # ---------------------------------------------------------------------
    # Vertical diffs + C_v
    # ---------------------------------------------------------------------

    dL_dv_v = []
    dL_dt_v = []
    C_v_q = [0 for _ in range(N_IMG)]

    for x in range(WH_SIZE):
        pay = imbg_parse_payload(epi_v_imgb[x])

        out_dv = bytearray(DIFF_PAY_BYTES)
        out_dt = bytearray(DIFF_PAY_BYTES)
        sum_mag = [0] * WH_SIZE

        out_row_base = 0

        for a in range(EPI_UV):
            # Same distinction:
            # out_row_base is single-channel output row stride.
            # pay_row_base is RGB EPI input row stride.
            pay_row_base = a * EPI_ROW_BYTES

            o_dv = out_row_base
            o_dt = out_row_base

            if a == 0 or a == EPI_UV - 1:
                y = 0
                while y < WH_SIZE:
                    dL_dv = 0

                    if y == 0 or y == WH_SIZE - 1:
                        dL_dt = 0
                    else:
                        idx_m_t = pay_row_base + ((y - 1) * BYTES_PER_PIXEL_RGB) + CH_OFF
                        idx_p_t = pay_row_base + ((y + 1) * BYTES_PER_PIXEL_RGB) + CH_OFF

                        Lm_t = _u24_read(pay, idx_m_t) - BIAS_INT
                        Lp_t = _u24_read(pay, idx_p_t) - BIAS_INT

                        dL_dt = _round_div2(Lp_t - Lm_t)

                    _u24_write(out_dv, o_dv, BIAS_INT)
                    _u24_write(out_dt, o_dt, _bias_from_q12_12(dL_dt))

                    o_dv += BYTES_PER_SAMPLE
                    o_dt += BYTES_PER_SAMPLE
                    y += 1

            else:
                a_m = a - 1
                a_p = a + 1

                pay_row_base_m = a_m * EPI_ROW_BYTES
                pay_row_base_p = a_p * EPI_ROW_BYTES

                y9 = 0
                y = 0

                while y < WH_SIZE:
                    # Angular derivative L_v = (L[a+1,y] - L[a-1,y]) / 2.
                    idx_m_v = pay_row_base_m + y9 + CH_OFF
                    idx_p_v = pay_row_base_p + y9 + CH_OFF

                    Lm_v = _u24_read(pay, idx_m_v) - BIAS_INT
                    Lp_v = _u24_read(pay, idx_p_v) - BIAS_INT

                    dL_dv = _round_div2(Lp_v - Lm_v)

                    # Spatial derivative L_t = (L[a,y+1] - L[a,y-1]) / 2.
                    if y == 0 or y == WH_SIZE - 1:
                        dL_dt = 0
                    else:
                        idx_m_t = pay_row_base + ((y - 1) * BYTES_PER_PIXEL_RGB) + CH_OFF
                        idx_p_t = pay_row_base + ((y + 1) * BYTES_PER_PIXEL_RGB) + CH_OFF

                        Lm_t = _u24_read(pay, idx_m_t) - BIAS_INT
                        Lp_t = _u24_read(pay, idx_p_t) - BIAS_INT

                        dL_dt = _round_div2(Lp_t - Lm_t)

                    _u24_write(out_dv, o_dv, _bias_from_q12_12(dL_dv))
                    _u24_write(out_dt, o_dt, _bias_from_q12_12(dL_dt))

                    sum_mag[y] += _gradient_magnitude_approx_q12(dL_dt, dL_dv)

                    y9 += BYTES_PER_PIXEL_RGB
                    o_dv += BYTES_PER_SAMPLE
                    o_dt += BYTES_PER_SAMPLE
                    y += 1

            out_row_base += DIFF_ROW_BYTES

        y = 0
        while y < WH_SIZE:
            C_v_q[(y << WH_SHIFT) + x] = (sum_mag[y] + DEMONINATOR_HALF) // DEMONINATOR
            y += 1

        dL_dv_v.append(imgb_make(W=WH_SIZE, H=EPI_UV, C=1, dtype_code=4, payload=bytes(out_dv)))
        dL_dt_v.append(imgb_make(W=WH_SIZE, H=EPI_UV, C=1, dtype_code=4, payload=bytes(out_dt)))

    C_v_payload = bytearray(OUT_IMG_BYTES)

    o = 0
    i = 0
    while i < N_IMG:
        _u24_write(C_v_payload, o, _bias_from_q12_12(C_v_q[i]))
        o += BYTES_PER_SAMPLE
        i += 1

    C_v_imgb = imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(C_v_payload))

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

    return imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(out))
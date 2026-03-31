# confidence.py
# Confidence from texture strength using PRECOMPUTED EPIs (IMGB blobs).
# Also returns angular diffs so disparity doesn't recompute them.
#
# Assumptions (guaranteed by your EPIs.py + pipeline):
#   - Image W = H = WH_SIZE = 512 (= 1<<WH_SHIFT)
#   - Angular A = EPI_UV = 9
#   - epi_h_imgb[y] is IMGB with (W=512, H=A=9, C=3, dtype_code=4)
#   - epi_v_imgb[x] is IMGB with (W=512, H=A=9, C=3, dtype_code=4)
#
# Optimisations:
#   - H*W replaced by (1 << (WH_SHIFT+WH_SHIFT))
#   - row_base = y<<WH_SHIFT instead of y*W
#   - bytes sizing uses constants (512*9, 512*3, etc.)

# image samples: 512*512 = 1<<(9+9) = 262144
N_IMG = 262144

# output payload bytes for C maps: N_IMG samples * 3 bytes
OUT_IMG_BYTES = 786432

DIFF_ROW_BYTES = 1536  # 512 samples * 3 bytes/sample

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

# -------- u24 helpers (local; keep tight) --------

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
    return -x if x < 0 else x

def _round_div2(x: int) -> int:
    # round-to-nearest for /2 in signed integer domain
    if x >= 0:
        return (x + 1) >> 1
    return -(((-x) + 1) >> 1)


# ----------------------------------------------------------
# Core
# ----------------------------------------------------------

def compute_from_epis_with_diffs(epi_h_imgb, epi_v_imgb, channel=None):
    ch = 0 if channel is None else int(channel)

    # ch*3
    CH_OFF = (ch << 1) + ch  # ch*3 but using shifts/adds; ch in 0..2 so safe

    # ------------------------------------------------------
    # Horizontal diffs + C_h
    # ------------------------------------------------------

    dL_du_h = []
    C_h_q = [0 for _ in range(N_IMG)]   # no "*" and no broken "<<"

    for y in range(WH_SIZE):
        pay = imbg_parse_payload(epi_h_imgb[y])

        out_diff = bytearray(DIFF_PAY_BYTES)
        sum_abs = [0] * WH_SIZE

        out_row_base = 0
        for a in range(EPI_UV):
            if a == 0 or a == EPI_UV - 1:
                o = out_row_base
                for _x in range(WH_SIZE):
                    _u24_write(out_diff, o, BIAS_INT)
                    o += BYTES_PER_SAMPLE
            else:
                a_m = a - 1
                a_p = a + 1

                # Small multiplies (a in 0..8); acceptable.
                pay_row_base_m = a_m * EPI_ROW_BYTES
                pay_row_base_p = a_p * EPI_ROW_BYTES

                x9 = 0
                o = out_row_base
                xi = 0
                while xi < WH_SIZE:
                    idx_m = pay_row_base_m + x9 + CH_OFF
                    idx_p = pay_row_base_p + x9 + CH_OFF

                    Lm = _u24_read(pay, idx_m) - BIAS_INT
                    Lp = _u24_read(pay, idx_p) - BIAS_INT

                    d = _round_div2(Lp - Lm)
                    _u24_write(out_diff, o, _bias_from_q12_12(d))
                    sum_abs[xi] += _abs_i32(d)

                    x9 += BYTES_PER_PIXEL_RGB  # +9
                    o += BYTES_PER_SAMPLE      # +3
                    xi += 1

            out_row_base += DIFF_ROW_BYTES

        # row_base = y * 512  -> y << 9
        row_base = y << WH_SHIFT
        x = 0
        while x < WH_SIZE:
            C_h_q[row_base + x] = (sum_abs[x] + DEMONINATOR_HALF) // DEMONINATOR
            x += 1

        dL_du_h.append(imgb_make(W=WH_SIZE, H=EPI_UV, C=1, dtype_code=4, payload=bytes(out_diff)))

    # Pack C_h
    C_h_payload = bytearray(OUT_IMG_BYTES)
    o = 0
    i = 0
    while i < N_IMG:
        _u24_write(C_h_payload, o, _bias_from_q12_12(C_h_q[i]))
        o += BYTES_PER_SAMPLE
        i += 1
    C_h_imgb = imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(C_h_payload))

    # ------------------------------------------------------
    # Vertical diffs + C_v
    # ------------------------------------------------------

    dL_dv_v = []
    C_v_q = [0 for _ in range(N_IMG)]   # no "*" and no broken "<<"

    for x in range(WH_SIZE):
        pay = imbg_parse_payload(epi_v_imgb[x])

        out_diff = bytearray(DIFF_PAY_BYTES)
        sum_abs = [0] * WH_SIZE

        out_row_base = 0
        for a in range(EPI_UV):
            if a == 0 or a == EPI_UV - 1:
                o = out_row_base
                for _y in range(WH_SIZE):
                    _u24_write(out_diff, o, BIAS_INT)
                    o += BYTES_PER_SAMPLE
            else:
                a_m = a - 1
                a_p = a + 1

                pay_row_base_m = a_m * EPI_ROW_BYTES
                pay_row_base_p = a_p * EPI_ROW_BYTES

                y9 = 0
                o = out_row_base
                yi = 0
                while yi < WH_SIZE:
                    idx_m = pay_row_base_m + y9 + CH_OFF
                    idx_p = pay_row_base_p + y9 + CH_OFF

                    Lm = _u24_read(pay, idx_m) - BIAS_INT
                    Lp = _u24_read(pay, idx_p) - BIAS_INT

                    d = _round_div2(Lp - Lm)
                    _u24_write(out_diff, o, _bias_from_q12_12(d))
                    sum_abs[yi] += _abs_i32(d)

                    y9 += BYTES_PER_PIXEL_RGB  # +9
                    o += BYTES_PER_SAMPLE      # +3
                    yi += 1

            out_row_base += DIFF_ROW_BYTES

        # Write column x into C_v_q using base=(y<<9)+x (no "*W")
        y = 0
        while y < WH_SIZE:
            C_v_q[(y << WH_SHIFT) + x] = (sum_abs[y] + DEMONINATOR_HALF) // DEMONINATOR
            y += 1

        dL_dv_v.append(imgb_make(W=WH_SIZE, H=EPI_UV, C=1, dtype_code=4, payload=bytes(out_diff)))

    # Pack C_v
    C_v_payload = bytearray(OUT_IMG_BYTES)
    o = 0
    i = 0
    while i < N_IMG:
        _u24_write(C_v_payload, o, _bias_from_q12_12(C_v_q[i]))
        o += BYTES_PER_SAMPLE
        i += 1
    C_v_imgb = imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(C_v_payload))

    return C_h_imgb, C_v_imgb, dL_du_h, dL_dv_v


# ----------------------------------------------------------
# Fuse
# ----------------------------------------------------------

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
        o += 3
        i3 += 3
        k += 1

    return imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(out))
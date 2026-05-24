# confidence.py
# Confidence from full EPI gradient magnitude using PRECOMPUTED EPIs (IMGB blobs).
# Also returns angular and spatial diffs so disparity does not recompute them.
#
# Inputs:
#   epi_h_imgb: list[bytes] IMGB (height=A, width=W, C=3, dtype_code=4 u24 Q12.12 biased) per row y
#   epi_v_imgb: list[bytes] IMGB (height=A, width=H, C=3, dtype_code=4 u24 Q12.12 biased) per col x
#
# Outputs (ALL dtype_code=4 u24 Q12.12 biased):
#   C_h_imgb : IMGB (W x H, C=1, dtype_code=4) confidence horizontal (>=0)
#   C_v_imgb : IMGB (W x H, C=1, dtype_code=4) confidence vertical (>=0)
#   dL_du_h  : list[bytes] IMGB per-row (A x W, C=1, dtype_code=4) angular diffs, can be negative
#   dL_dv_v  : list[bytes] IMGB per-col (A x H, C=1, dtype_code=4) angular diffs, can be negative
#   dL_ds_h  : list[bytes] IMGB per-row (A x W, C=1, dtype_code=4) spatial diffs, can be negative
#   dL_dt_v  : list[bytes] IMGB per-col (A x H, C=1, dtype_code=4) spatial diffs, can be negative
#
# Confidence now follows the canonical EPI gradient magnitude:
#   C_h(y,x) = mean_a sqrt(L_s(a,x)^2 + L_u(a,x)^2)
#   C_v(y,x) = mean_a sqrt(L_t(a,y)^2 + L_v(a,y)^2)
#
# All derivatives are stored as signed Q12.12 integers, biased to u24.

import math

from utils import (
    imgb_parse,
    imbg_parse_payload,
    imgb_make,
    BIAS_INT
)


def _u24_read(payload: bytes, byte_off: int) -> int:
    return payload[byte_off] | (payload[byte_off + 1] << 8) | (payload[byte_off + 2] << 16)


def _u24_write(out: bytearray, byte_off: int, u: int) -> None:
    u &= 0xFFFFFF
    out[byte_off] = u & 0xFF
    out[byte_off + 1] = (u >> 8) & 0xFF
    out[byte_off + 2] = (u >> 16) & 0xFF


def _bias_from_q12_12(q: int) -> int:
    u = int(q) + BIAS_INT

    if u < 0:
        return 0

    if u > 0xFFFFFF:
        return 0xFFFFFF

    return u


def _round_div2(x: int) -> int:
    # Round-to-nearest for /2 in integer domain.
    if x >= 0:
        return (x + 1) >> 1

    return -(((-x) + 1) >> 1)


def _gradient_magnitude_q12(a_q12: int, b_q12: int) -> int:
    """
    Canonical Euclidean gradient magnitude.

    a_q12 and b_q12 are signed Q12.12 derivative values.
    sqrt(a_q12^2 + b_q12^2) remains in Q12.12 units.
    """
    mag = math.sqrt(float(a_q12 * a_q12 + b_q12 * b_q12))
    return int(mag + 0.5)


def compute_from_epis_with_diffs(epi_h_imgb, epi_v_imgb, channel=None):
    if channel is None:
        ch = 0
    else:
        ch = int(channel)

    H_img = len(epi_h_imgb)
    W_img = len(epi_v_imgb)

    if H_img == 0 or W_img == 0:
        raise ValueError("Empty epi lists")

    # Parse one to get dimensions.
    W_h, A_h, C_hc, dt_h, _ = imgb_parse(epi_h_imgb[0])  # width=W, height=A
    W_v, A_v, C_vc, dt_v, _ = imgb_parse(epi_v_imgb[0])  # width=H, height=A

    if dt_h != 4 or dt_v != 4:
        raise ValueError("EPIs must be dtype_code=4 (u24 Q12.12 biased)")

    if C_hc != 3 or C_vc != 3:
        raise ValueError("EPIs must be RGB (C=3)")

    W = int(W_h)
    A = int(A_h)
    H = int(H_img)

    if int(W_img) != W:
        raise ValueError("epi_v_imgb length must equal image width W")

    if int(W_v) != H:
        raise ValueError("vertical EPI width must equal image height H")

    if int(A_v) != A:
        raise ValueError("horizontal/vertical angular counts must match")

    # Each Q12.12 sample is 3 bytes. RGB pixel = 3 samples => 9 bytes.
    BYTES_PER_SAMPLE = 3
    BYTES_PER_PIXEL_RGB = 9

    # ------------------------------------------------------------------
    # Horizontal derivatives + C_h
    # ------------------------------------------------------------------
    # dL_du_h[y]: angular derivative in horizontal EPI, shape A x W.
    # dL_ds_h[y]: spatial derivative in horizontal EPI, shape A x W.
    # C_h(y,x): mean over valid angular rows of sqrt(L_s^2 + L_u^2).

    dL_du_h = []
    dL_ds_h = []
    C_h_q = [0] * (H * W)

    if A < 3:
        for y in range(H):
            out_du = bytearray(A * W * BYTES_PER_SAMPLE)
            out_ds = bytearray(A * W * BYTES_PER_SAMPLE)

            for i in range(A * W):
                _u24_write(out_du, i * 3, BIAS_INT)
                _u24_write(out_ds, i * 3, BIAS_INT)

            dL_du_h.append(imgb_make(W=W, H=A, C=1, dtype_code=4, payload=bytes(out_du)))
            dL_ds_h.append(imgb_make(W=W, H=A, C=1, dtype_code=4, payload=bytes(out_ds)))
    else:
        denom = A - 2
        half = denom // 2

        for y in range(H):
            pay = imbg_parse_payload(epi_h_imgb[y])

            out_du = bytearray(A * W * BYTES_PER_SAMPLE)
            out_ds = bytearray(A * W * BYTES_PER_SAMPLE)
            sum_mag = [0] * W

            for a in range(A):
                base_out = (a * W) * BYTES_PER_SAMPLE

                for x in range(W):
                    # Angular derivative L_u = (L[a+1,x] - L[a-1,x]) / 2.
                    if a == 0 or a == A - 1:
                        dL_du = 0
                    else:
                        idx_m = (((a - 1) * W + x) * BYTES_PER_PIXEL_RGB) + ch * 3
                        idx_p = (((a + 1) * W + x) * BYTES_PER_PIXEL_RGB) + ch * 3

                        Lm = _u24_read(pay, idx_m) - BIAS_INT
                        Lp = _u24_read(pay, idx_p) - BIAS_INT

                        dL_du = _round_div2(Lp - Lm)

                    # Spatial derivative L_s = (L[a,x+1] - L[a,x-1]) / 2.
                    if x == 0 or x == W - 1:
                        dL_ds = 0
                    else:
                        idx_m = ((a * W + (x - 1)) * BYTES_PER_PIXEL_RGB) + ch * 3
                        idx_p = ((a * W + (x + 1)) * BYTES_PER_PIXEL_RGB) + ch * 3

                        Lm = _u24_read(pay, idx_m) - BIAS_INT
                        Lp = _u24_read(pay, idx_p) - BIAS_INT

                        dL_ds = _round_div2(Lp - Lm)

                    _u24_write(out_du, base_out + x * 3, _bias_from_q12_12(dL_du))
                    _u24_write(out_ds, base_out + x * 3, _bias_from_q12_12(dL_ds))

                    # Confidence only averages over valid central angular rows,
                    # matching the previous A-2 angular-difference convention.
                    if a != 0 and a != A - 1:
                        sum_mag[x] += _gradient_magnitude_q12(dL_ds, dL_du)

            row_base = y * W

            for x in range(W):
                C_h_q[row_base + x] = (sum_mag[x] + half) // denom

            dL_du_h.append(imgb_make(W=W, H=A, C=1, dtype_code=4, payload=bytes(out_du)))
            dL_ds_h.append(imgb_make(W=W, H=A, C=1, dtype_code=4, payload=bytes(out_ds)))

    C_h_payload = bytearray(H * W * 3)

    for i in range(H * W):
        _u24_write(C_h_payload, i * 3, _bias_from_q12_12(C_h_q[i]))

    C_h_imgb = imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(C_h_payload))

    # ------------------------------------------------------------------
    # Vertical derivatives + C_v
    # ------------------------------------------------------------------
    # dL_dv_v[x]: angular derivative in vertical EPI, shape A x H.
    # dL_dt_v[x]: spatial derivative in vertical EPI, shape A x H.
    # C_v(y,x): mean over valid angular rows of sqrt(L_t^2 + L_v^2).

    dL_dv_v = []
    dL_dt_v = []
    C_v_q = [0] * (H * W)

    if A < 3:
        for x in range(W):
            out_dv = bytearray(A * H * BYTES_PER_SAMPLE)
            out_dt = bytearray(A * H * BYTES_PER_SAMPLE)

            for i in range(A * H):
                _u24_write(out_dv, i * 3, BIAS_INT)
                _u24_write(out_dt, i * 3, BIAS_INT)

            dL_dv_v.append(imgb_make(W=H, H=A, C=1, dtype_code=4, payload=bytes(out_dv)))
            dL_dt_v.append(imgb_make(W=H, H=A, C=1, dtype_code=4, payload=bytes(out_dt)))
    else:
        denom = A - 2
        half = denom // 2

        for x in range(W):
            pay = imbg_parse_payload(epi_v_imgb[x])

            out_dv = bytearray(A * H * BYTES_PER_SAMPLE)
            out_dt = bytearray(A * H * BYTES_PER_SAMPLE)
            sum_mag = [0] * H

            for a in range(A):
                base_out = (a * H) * BYTES_PER_SAMPLE

                for y in range(H):
                    # Angular derivative L_v = (L[a+1,y] - L[a-1,y]) / 2.
                    if a == 0 or a == A - 1:
                        dL_dv = 0
                    else:
                        idx_m = (((a - 1) * H + y) * BYTES_PER_PIXEL_RGB) + ch * 3
                        idx_p = (((a + 1) * H + y) * BYTES_PER_PIXEL_RGB) + ch * 3

                        Lm = _u24_read(pay, idx_m) - BIAS_INT
                        Lp = _u24_read(pay, idx_p) - BIAS_INT

                        dL_dv = _round_div2(Lp - Lm)

                    # Spatial derivative L_t = (L[a,y+1] - L[a,y-1]) / 2.
                    if y == 0 or y == H - 1:
                        dL_dt = 0
                    else:
                        idx_m = ((a * H + (y - 1)) * BYTES_PER_PIXEL_RGB) + ch * 3
                        idx_p = ((a * H + (y + 1)) * BYTES_PER_PIXEL_RGB) + ch * 3

                        Lm = _u24_read(pay, idx_m) - BIAS_INT
                        Lp = _u24_read(pay, idx_p) - BIAS_INT

                        dL_dt = _round_div2(Lp - Lm)

                    _u24_write(out_dv, base_out + y * 3, _bias_from_q12_12(dL_dv))
                    _u24_write(out_dt, base_out + y * 3, _bias_from_q12_12(dL_dt))

                    if a != 0 and a != A - 1:
                        sum_mag[y] += _gradient_magnitude_q12(dL_dt, dL_dv)

            for y in range(H):
                C_v_q[y * W + x] = (sum_mag[y] + half) // denom

            dL_dv_v.append(imgb_make(W=H, H=A, C=1, dtype_code=4, payload=bytes(out_dv)))
            dL_dt_v.append(imgb_make(W=H, H=A, C=1, dtype_code=4, payload=bytes(out_dt)))

    C_v_payload = bytearray(H * W * 3)

    for i in range(H * W):
        _u24_write(C_v_payload, i * 3, _bias_from_q12_12(C_v_q[i]))

    C_v_imgb = imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(C_v_payload))

    return C_h_imgb, C_v_imgb, dL_du_h, dL_dv_v, dL_ds_h, dL_dt_v


def fuse_avg(C_h_imgb: bytes, C_v_imgb: bytes) -> bytes:
    # Average in Q12.12 integer domain:
    # avg = round((a + b) / 2)
    W1, H1, C1, dt1, p1 = imgb_parse(C_h_imgb)
    W2, H2, C2, dt2, p2 = imgb_parse(C_v_imgb)

    if W1 != W2 or H1 != H2 or C1 != 1 or C2 != 1 or dt1 != 4 or dt2 != 4:
        raise ValueError("fuse_avg expects both inputs as IMGB dtype_code=4, C=1, same dims")

    n = int(W1) * int(H1)
    out = bytearray(n * 3)

    for i in range(n):
        a = _u24_read(p1, i * 3) - BIAS_INT
        b = _u24_read(p2, i * 3) - BIAS_INT
        s = a + b
        avg = _round_div2(s)
        _u24_write(out, i * 3, _bias_from_q12_12(avg))

    return imgb_make(W=int(W1), H=int(H1), C=1, dtype_code=4, payload=bytes(out))

# -----------------------------------------------------------------------------
# RGB confidence helpers
# -----------------------------------------------------------------------------

def fuse_avg_three(C1_imgb: bytes, C2_imgb: bytes, C3_imgb: bytes) -> bytes:
    """
    Average three per-channel confidence maps in Q12.12 integer form.

    This is used by the RGB No_Libraries pipeline to produce one aggregate
    confidence map for visualisation and for the future-work region filling
    stage:
        C_avg_rgb = (C_avg_red + C_avg_green + C_avg_blue) / 3
    """

    W1, H1, Ch1, dt1, p1 = imgb_parse(C1_imgb)
    W2, H2, Ch2, dt2, p2 = imgb_parse(C2_imgb)
    W3, H3, Ch3, dt3, p3 = imgb_parse(C3_imgb)

    if not (W1 == W2 == W3 and H1 == H2 == H3):
        raise ValueError("fuse_avg_three expects same-sized confidence maps")

    if not (Ch1 == Ch2 == Ch3 == 1 and dt1 == dt2 == dt3 == 4):
        raise ValueError("fuse_avg_three expects dtype_code=4, C=1 inputs")

    n = int(W1) * int(H1)
    out = bytearray(n * 3)

    for i in range(n):
        o = i * 3
        a = _u24_read(p1, o) - BIAS_INT
        b = _u24_read(p2, o) - BIAS_INT
        c = _u24_read(p3, o) - BIAS_INT
        total = a + b + c
        if total >= 0:
            avg = (total + 1) // 3
        else:
            avg = -(((-total) + 1) // 3)
        _u24_write(out, o, _bias_from_q12_12(avg))

    return imgb_make(W=int(W1), H=int(H1), C=1, dtype_code=4, payload=bytes(out))

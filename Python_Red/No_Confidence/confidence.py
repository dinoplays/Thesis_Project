# confidence.py
# Confidence from texture strength using PRECOMPUTED EPIs (IMGB blobs).
# Also returns angular diffs so disparity doesn't recompute them.
#
# Inputs:
#   epi_h_imgb: list[bytes] IMGB (height=A, width=W, C=3, dtype_code=4 u24 Q12.12 biased) per row y
#   epi_v_imgb: list[bytes] IMGB (height=A, width=H, C=3, dtype_code=4 u24 Q12.12 biased) per col x
#
# Outputs (ALL dtype_code=4 u24 Q12.12 biased):
#   C_h_imgb : IMGB (W x H, C=1, dtype_code=4)  confidence horizontal (>=0)
#   C_v_imgb : IMGB (W x H, C=1, dtype_code=4)  confidence vertical (>=0)
#   dL_du_h  : list[bytes] IMGB per-row (A x W, C=1, dtype_code=4) diffs can be negative
#   dL_dv_v  : list[bytes] IMGB per-col (A x H, C=1, dtype_code=4) diffs can be negative
#
# All internal arithmetic is done in signed Q12.12 integers, stored biased to u24.

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

def _abs_i32(x: int) -> int:
    return -x if x < 0 else x

def _round_div2(x: int) -> int:
    # round-to-nearest for /2 in integer domain
    if x >= 0:
        return (x + 1) >> 1
    return -(((-x) + 1) >> 1)

def compute_from_epis_with_diffs(epi_h_imgb, epi_v_imgb, channel=None):
    if channel is None:
        ch = 0
    else:
        ch = int(channel)

    H_img = len(epi_h_imgb)
    W_img = len(epi_v_imgb)
    if H_img == 0 or W_img == 0:
        raise ValueError("Empty epi lists")

    # Parse one to get dimensions
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

    # Each sample is 3 bytes. RGB pixel = 3 samples => 9 bytes.
    BYTES_PER_SAMPLE = 3
    BYTES_PER_PIXEL_RGB = 9

    # --------- Horizontal diffs + C_h ----------
    # dL_du_h[y]: (height=A, width=W, C=1) Q12.12
    # C_h(y,x) = mean_{a=1..A-2} abs(dL/du)
    dL_du_h = []
    C_h_q = [0] * (H * W)  # signed Q12.12 ints (but should be >=0)

    if A < 3:
        # No valid central difference: output 0 everywhere
        for y in range(H):
            out_diff = bytearray(A * W * BYTES_PER_SAMPLE)
            # fill with bias (0.0)
            for i in range(A * W):
                _u24_write(out_diff, i * 3, BIAS_INT)
            dL_du_h.append(imgb_make(W=W, H=A, C=1, dtype_code=4, payload=bytes(out_diff)))
    else:
        denom = (A - 2)

        for y in range(H):
            pay = imbg_parse_payload(epi_h_imgb[y])
            out_diff = bytearray(A * W * BYTES_PER_SAMPLE)
            sum_abs = [0] * W  # Q12.12

            # For each angular a, compute central diff along angular axis:
            # d = (L[a+1]-L[a-1]) / 2
            for a in range(A):
                base_out = (a * W) * 3
                if a == 0 or a == A - 1:
                    # borders -> 0.0
                    for x in range(W):
                        _u24_write(out_diff, base_out + x * 3, BIAS_INT)
                else:
                    a_m = a - 1
                    a_p = a + 1

                    # index in pay:
                    # pixel (a,x) starts at ((a*W + x) * 9)
                    for x in range(W):
                        idx_m = ((a_m * W + x) * BYTES_PER_PIXEL_RGB) + ch * 3
                        idx_p = ((a_p * W + x) * BYTES_PER_PIXEL_RGB) + ch * 3

                        Lm = _u24_read(pay, idx_m) - BIAS_INT
                        Lp = _u24_read(pay, idx_p) - BIAS_INT

                        d = _round_div2(Lp - Lm)  # Q12.12
                        _u24_write(out_diff, base_out + x * 3, _bias_from_q12_12(d))
                        sum_abs[x] += _abs_i32(d)

            row_base = y * W
            # mean abs with integer division, keeps Q12.12
            half = denom // 2
            for x in range(W):
                C_h_q[row_base + x] = (sum_abs[x] + half) // denom

            dL_du_h.append(imgb_make(W=W, H=A, C=1, dtype_code=4, payload=bytes(out_diff)))

    # Pack C_h to u24 payload
    C_h_payload = bytearray(H * W * 3)
    for i in range(H * W):
        _u24_write(C_h_payload, i * 3, _bias_from_q12_12(C_h_q[i]))
    C_h_imgb = imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(C_h_payload))

    # --------- Vertical diffs + C_v ----------
    dL_dv_v = []
    C_v_q = [0] * (H * W)

    if A < 3:
        for x in range(W):
            out_diff = bytearray(A * H * 3)
            for i in range(A * H):
                _u24_write(out_diff, i * 3, BIAS_INT)
            dL_dv_v.append(imgb_make(W=H, H=A, C=1, dtype_code=4, payload=bytes(out_diff)))
    else:
        denom = (A - 2)

        for x in range(W):
            pay = imbg_parse_payload(epi_v_imgb[x])
            # vertical EPI: width=H, height=A
            out_diff = bytearray(A * H * 3)
            sum_abs = [0] * H

            for a in range(A):
                base_out = (a * H) * 3
                if a == 0 or a == A - 1:
                    for y in range(H):
                        _u24_write(out_diff, base_out + y * 3, BIAS_INT)
                else:
                    a_m = a - 1
                    a_p = a + 1
                    for y in range(H):
                        idx_m = ((a_m * H + y) * BYTES_PER_PIXEL_RGB) + ch * 3
                        idx_p = ((a_p * H + y) * BYTES_PER_PIXEL_RGB) + ch * 3

                        Lm = _u24_read(pay, idx_m) - BIAS_INT
                        Lp = _u24_read(pay, idx_p) - BIAS_INT

                        d = _round_div2(Lp - Lm)
                        _u24_write(out_diff, base_out + y * 3, _bias_from_q12_12(d))
                        sum_abs[y] += _abs_i32(d)

            half = denom // 2
            for y in range(H):
                C_v_q[y * W + x] = (sum_abs[y] + half) // denom

            dL_dv_v.append(imgb_make(W=H, H=A, C=1, dtype_code=4, payload=bytes(out_diff)))

    C_v_payload = bytearray(H * W * 3)
    for i in range(H * W):
        _u24_write(C_v_payload, i * 3, _bias_from_q12_12(C_v_q[i]))
    C_v_imgb = imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(C_v_payload))

    return C_h_imgb, C_v_imgb, dL_du_h, dL_dv_v

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
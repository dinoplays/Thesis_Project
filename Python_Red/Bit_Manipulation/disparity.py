# disparity.py
# Pure-stdlib disparity from PRECOMPUTED EPIs and PRECOMPUTED angular diffs.
# FULL FIXED-POINT VERSION: NO FLOATS. Everything is signed Q12.12 ints.
#
# Assumptions (guaranteed by EPIs.py + pipeline):
#   - Image W = H = WH_SIZE = 512 (= 1<<WH_SHIFT)
#   - Angular A = EPI_UV = 9
#   - epi_h_imgb[y] is IMGB with (W=512, H=A=9, C=3, dtype_code=4)
#   - epi_v_imgb[x] is IMGB with (W=512, H=A=9, C=3, dtype_code=4)
#   - dL_du_h[y] is IMGB with (W=512, H=A=9, C=1, dtype_code=4)
#   - dL_dv_v[x] is IMGB with (W=512, H=A=9, C=1, dtype_code=4)
#
# Inputs d, ds, du, dt, dv must be Q12.12 ints.
#   Example: 1.0 -> 4096, 0.5 -> 2048
#
# Outputs are Q12.12 IMGB (dtype_code=4 u24 biased).

from utils import (
    imbg_parse_payload,
    imgb_make,
    BIAS_INT,
    Q_SCALE,
    U24_MAX,
    WH_SHIFT,
    WH_SIZE,
    EPI_UV,
)

from EPIs import (
    BYTES_PER_SAMPLE,
    BYTES_PER_PIXEL_RGB,
    EPI_ROW_BYTES
)

from confidence import (
    N_IMG,
    OUT_IMG_BYTES,
    DIFF_ROW_BYTES
)

Q_FRAC = 12
Q_ONE  = 1 << Q_FRAC  # 4096


# ---------------- u24 helpers (local, fast) ----------------

def _u24_read(p: bytes, o: int) -> int:
    return p[o] | (p[o + 1] << 8) | (p[o + 2] << 16)

def _u24_write(out: bytearray, o: int, u: int) -> None:
    u &= U24_MAX
    out[o] = u & 0xFF
    out[o + 1] = (u >> 8) & 0xFF
    out[o + 2] = (u >> 16) & 0xFF

def _bias_q(q: int) -> int:
    u = int(q) + BIAS_INT
    if u < 0:
        return 0
    if u > U24_MAX:
        return U24_MAX
    return u

def _abs_i(x: int) -> int:
    return -x if x < 0 else x

def _round_div2(x: int) -> int:
    if x >= 0:
        return (x + 1) >> 1
    return -(((-x) + 1) >> 1

    )


# ---------------- fixed-point helpers ----------------

def _div_q12(num_q12: int, den_q12: int) -> int:
    # (num/den) in Q12.12: (num<<12)/den with rounding.
    if den_q12 == 0:
        return 0
    if num_q12 >= 0:
        return ((num_q12 << Q_FRAC) + (den_q12 >> 1)) // den_q12
    return -((((-num_q12) << Q_FRAC) + (den_q12 >> 1)) // den_q12)

def _inv_q12(den_q12: int) -> int:
    # inv in Q12.12: (1<<24)/den (since (Q12.12)*(Q12.12) => Q24.24, need Q12.12)
    if den_q12 == 0:
        return 0
    # (Q_ONE<<Q_FRAC) == 1<<24
    num = (Q_ONE << Q_FRAC)
    if den_q12 > 0:
        return (num + (den_q12 >> 1)) // den_q12
    return -((num + ((-den_q12) >> 1)) // (-den_q12))

def _mul_q12(a_q12: int, b_q12: int) -> int:
    # (a*b) in Q12.12 with rounding: (a*b + 2^11)>>12
    prod = a_q12 * b_q12  # Q24.24
    if prod >= 0:
        return (prod + (1 << (Q_FRAC - 1))) >> Q_FRAC
    return -(((-prod) + (1 << (Q_FRAC - 1))) >> Q_FRAC)

def _pow_q12_int(base_q12: int, exp: int) -> int:
    # integer exponent in Q12.12, rescaling after each multiply.
    # exp must be >=0.
    if exp <= 0:
        return Q_ONE
    if exp == 1:
        return base_q12
    # fast pow
    result = Q_ONE
    b = base_q12
    e = exp
    while e > 0:
        if e & 1:
            result = _mul_q12(result, b)
        e >>= 1
        if e:
            b = _mul_q12(b, b)
    return result

def _clamp_q12(x_q12: int, lo_q12: int, hi_q12: int) -> int:
    if x_q12 < lo_q12:
        return lo_q12
    if x_q12 > hi_q12:
        return hi_q12
    return x_q12


# ---------------- box sum over 2D plane (zero padded) ----------------
# plane entries are INTs (here: P_uv/P_uu in Q24.24; W_u in Q12.12).
# integral image is in python int, safe.

def _box_sum_2d_int(plane: list[list[int]], win: int) -> list[list[int]]:
    if win <= 1:
        return plane

    r = win >> 1
    A0 = len(plane)
    if A0 <= 0:
        return plane
    W0 = len(plane[0])

    integ = [[0] * (W0 + 1) for _ in range(A0 + 1)]

    a = 0
    while a < A0:
        row_sum = 0
        ia1 = integ[a + 1]
        ia0 = integ[a]
        prow = plane[a]

        x = 0
        while x < W0:
            row_sum += prow[x]
            ia1[x + 1] = ia0[x + 1] + row_sum
            x += 1
        a += 1

    out = [[0] * W0 for _ in range(A0)]

    a = 0
    while a < A0:
        a0 = a - r
        a1 = a + r
        if a0 < 0:
            a0 = 0
        if a1 >= A0:
            a1 = A0 - 1

        ia0 = integ[a0]
        ia1 = integ[a1 + 1]

        x = 0
        while x < W0:
            x0 = x - r
            x1 = x + r
            if x0 < 0:
                x0 = 0
            if x1 >= W0:
                x1 = W0 - 1

            out[a][x] = ia1[x1 + 1] - ia0[x1 + 1] - ia1[x0] + ia0[x0]
            x += 1

        a += 1

    return out


# ---------------- horizontal disparity (Q12.12 only) ----------------

def compute_horizontal_from_epis(epi_h_imgb, dL_du_h, *, d=Q_ONE, ds=Q_ONE, du=Q_ONE, win=5) -> bytes:
    # du_over_ds in Q12.12
    du_over_ds_q12 = _div_q12(du, ds)

    # inv_d in Q12.12
    inv_d_q12 = _inv_q12(d)

    out_q = [0 for _ in range(N_IMG)]

    y = 0
    while y < WH_SIZE:
        epi_pay = imbg_parse_payload(epi_h_imgb[y])
        d_pay   = imbg_parse_payload(dL_du_h[y])

        # dL_du[a][x] in Q12.12
        dL_du = [[0] * WH_SIZE for _ in range(EPI_UV)]
        # dL_ds[a][x] in Q12.12
        dL_ds = [[0] * WH_SIZE for _ in range(EPI_UV)]

        # ---- fill dL_du ----
        a = 0
        base = 0
        while a < EPI_UV:
            row = dL_du[a]
            o = base
            x = 0
            while x < WH_SIZE:
                row[x] = _u24_read(d_pay, o) - BIAS_INT
                o += BYTES_PER_SAMPLE
                x += 1
            base += DIFF_ROW_BYTES
            a += 1

        # ---- compute dL_ds from epi (central diff along x), channel 0 ----
        a = 0
        epi_row_base = 0
        while a < EPI_UV:
            row = dL_ds[a]
            row[0] = 0
            row[WH_SIZE - 1] = 0

            x = 1
            o_m = epi_row_base
            o_p = epi_row_base + (BYTES_PER_PIXEL_RGB << 1)  # +18
            while x < (WH_SIZE - 1):
                Lm = _u24_read(epi_pay, o_m) - BIAS_INT
                Lp = _u24_read(epi_pay, o_p) - BIAS_INT
                row[x] = _round_div2(Lp - Lm)

                o_m += BYTES_PER_PIXEL_RGB
                o_p += BYTES_PER_PIXEL_RGB
                x += 1

            epi_row_base += EPI_ROW_BYTES
            a += 1

        # ---- build planes ----
        # P_uv, P_uu are Q24.24 (product of Q12.12)
        # W_u is Q12.12 (abs(du))
        P_uv = [[0] * WH_SIZE for _ in range(EPI_UV)]
        P_uu = [[0] * WH_SIZE for _ in range(EPI_UV)]
        W_u  = [[0] * WH_SIZE for _ in range(EPI_UV)]

        a = 0
        while a < EPI_UV:
            row_du = dL_du[a]
            row_ds = dL_ds[a]
            row_uv = P_uv[a]
            row_uu = P_uu[a]
            row_w  = W_u[a]

            x = 0
            while x < WH_SIZE:
                duq = row_du[x]          # Q12.12
                dsq = row_ds[x]          # Q12.12
                row_uv[x] = duq * dsq    # Q24.24
                row_uu[x] = duq * duq    # Q24.24
                row_w[x]  = _abs_i(duq)  # Q12.12
                x += 1
            a += 1

        S_uv = _box_sum_2d_int(P_uv, win)  # Q24.24 sums
        S_uu = _box_sum_2d_int(P_uu, win)  # Q24.24 sums
        W_b  = _box_sum_2d_int(W_u,  win)  # Q12.12 sums

        # write out row y: base = y<<9
        row_base = y << WH_SHIFT

        x = 0
        while x < WH_SIZE:
            num_acc_q24 = 0  # Q24.24
            den_acc_q12 = 0  # Q12.12

            a = 0
            while a < EPI_UV:
                w_q12 = W_b[a][x]
                if w_q12 > 0:
                    suu_q24 = S_uu[a][x]
                    if suu_q24 > 0:
                        # k_hat_q12 = (S_uv/S_uu) in Q12.12
                        # S_uv, S_uu are Q24.24, so (S_uv<<12)/S_uu -> Q12.12
                        suv_q24 = S_uv[a][x]
                        k_hat_q12 = (suv_q24 << Q_FRAC) // suu_q24

                        # ratio_q12 = (du/ds)*k_hat
                        # du_over_ds_q12 * k_hat_q12 -> Q24.24, >>12 -> Q12.12
                        ratio_q12 = (du_over_ds_q12 * k_hat_q12) >> Q_FRAC

                        # accumulate weighted average:
                        # ratio_q12 * w_q12 -> Q24.24
                        num_acc_q24 += ratio_q12 * w_q12
                        den_acc_q12 += w_q12
                a += 1

            if den_acc_q12 <= 0:
                D_q12 = 0
            else:
                # ratio_s_q12 = num/den : (Q24.24)/(Q12.12) => Q12.12
                # rounding: add half den (scaled to Q24.24) => (den<<11)
                if num_acc_q24 >= 0:
                    ratio_s_q12 = (num_acc_q24 + (den_acc_q12 << (Q_FRAC - 1))) // den_acc_q12
                else:
                    ratio_s_q12 = -(((-num_acc_q24) + (den_acc_q12 << (Q_FRAC - 1))) // den_acc_q12)

                # D = (1 + ratio_s) * inv_d
                # (Q12.12 + Q12.12) -> Q12.12, times inv_d_q12 -> Q24.24, >>12 -> Q12.12
                D_q12 = ((Q_ONE + ratio_s_q12) * inv_d_q12) >> Q_FRAC

            out_q[row_base + x] = D_q12
            x += 1

        y += 1

    # pack output
    out_pay = bytearray(OUT_IMG_BYTES)
    o = 0
    i = 0
    while i < N_IMG:
        _u24_write(out_pay, o, _bias_q(out_q[i]))
        o += BYTES_PER_SAMPLE
        i += 1

    return imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(out_pay))


# ---------------- vertical disparity (Q12.12 only) ----------------

def compute_vertical_from_epis(epi_v_imgb, dL_dv_v, *, d=Q_ONE, dt=Q_ONE, dv=Q_ONE, win=5) -> bytes:
    dv_over_dt_q12 = _div_q12(dv, dt)
    inv_d_q12 = _inv_q12(d)

    out_q = [0 for _ in range(N_IMG)]

    x = 0
    while x < WH_SIZE:
        epi_pay = imbg_parse_payload(epi_v_imgb[x])
        d_pay   = imbg_parse_payload(dL_dv_v[x])

        dL_dv = [[0] * WH_SIZE for _ in range(EPI_UV)]
        dL_dt = [[0] * WH_SIZE for _ in range(EPI_UV)]

        # ---- fill dL_dv ----
        a = 0
        base = 0
        while a < EPI_UV:
            row = dL_dv[a]
            o = base
            y = 0
            while y < WH_SIZE:
                row[y] = _u24_read(d_pay, o) - BIAS_INT
                o += BYTES_PER_SAMPLE
                y += 1
            base += DIFF_ROW_BYTES
            a += 1

        # ---- compute dL_dt from epi (central diff along y), channel 0 ----
        a = 0
        epi_row_base = 0
        while a < EPI_UV:
            row = dL_dt[a]
            row[0] = 0
            row[WH_SIZE - 1] = 0

            y = 1
            o_m = epi_row_base
            o_p = epi_row_base + (BYTES_PER_PIXEL_RGB << 1)  # +18
            while y < (WH_SIZE - 1):
                Lm = _u24_read(epi_pay, o_m) - BIAS_INT
                Lp = _u24_read(epi_pay, o_p) - BIAS_INT
                row[y] = _round_div2(Lp - Lm)

                o_m += BYTES_PER_PIXEL_RGB
                o_p += BYTES_PER_PIXEL_RGB
                y += 1

            epi_row_base += EPI_ROW_BYTES
            a += 1

        # ---- build planes ----
        P_vt = [[0] * WH_SIZE for _ in range(EPI_UV)]  # Q24.24
        P_vv = [[0] * WH_SIZE for _ in range(EPI_UV)]  # Q24.24
        W_v  = [[0] * WH_SIZE for _ in range(EPI_UV)]  # Q12.12

        a = 0
        while a < EPI_UV:
            row_dv = dL_dv[a]
            row_dt = dL_dt[a]
            row_vt = P_vt[a]
            row_vv = P_vv[a]
            row_w  = W_v[a]

            y = 0
            while y < WH_SIZE:
                dvq = row_dv[y]
                dtq = row_dt[y]
                row_vt[y] = dvq * dtq
                row_vv[y] = dvq * dvq
                row_w[y]  = _abs_i(dvq)
                y += 1
            a += 1

        S_vt = _box_sum_2d_int(P_vt, win)
        S_vv = _box_sum_2d_int(P_vv, win)
        W_b  = _box_sum_2d_int(W_v,  win)

        y = 0
        while y < WH_SIZE:
            num_acc_q24 = 0
            den_acc_q12 = 0

            a = 0
            while a < EPI_UV:
                w_q12 = W_b[a][y]
                if w_q12 > 0:
                    svv_q24 = S_vv[a][y]
                    if svv_q24 > 0:
                        svt_q24 = S_vt[a][y]
                        k_hat_q12 = (svt_q24 << Q_FRAC) // svv_q24
                        ratio_q12 = (dv_over_dt_q12 * k_hat_q12) >> Q_FRAC

                        num_acc_q24 += ratio_q12 * w_q12
                        den_acc_q12 += w_q12
                a += 1

            if den_acc_q12 <= 0:
                D_q12 = 0
            else:
                if num_acc_q24 >= 0:
                    ratio_t_q12 = (num_acc_q24 + (den_acc_q12 << (Q_FRAC - 1))) // den_acc_q12
                else:
                    ratio_t_q12 = -(((-num_acc_q24) + (den_acc_q12 << (Q_FRAC - 1))) // den_acc_q12)

                D_q12 = ((Q_ONE + ratio_t_q12) * inv_d_q12) >> Q_FRAC

            out_q[(y << WH_SHIFT) + x] = D_q12
            y += 1

        x += 1

    out_pay = bytearray(OUT_IMG_BYTES)
    o = 0
    i = 0
    while i < N_IMG:
        _u24_write(out_pay, o, _bias_q(out_q[i]))
        o += BYTES_PER_SAMPLE
        i += 1

    return imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(out_pay))


# ---------------- fusion (confidence-weighted, Q12.12 only) ----------------
# temperature must be an INT (default 4). floor/cap/eps must be Q12.12 ints.

def fuse_disparity_precision(
    Z_h_imgb: bytes,
    Z_v_imgb: bytes,
    C_h_imgb: bytes,
    C_v_imgb: bytes,
    *,
    temperature=4,
    floor=1,        # Q12.12; default 1 = ~0.000244 (NOT 1/4096). Pass 1 for 1 LSB, or 1<<0. Use 1 for min nonzero.
    cap=Q_ONE,      # Q12.12; 1.0
    eps=1,          # Q12.12; keep at least 1 LSB to avoid div0
) -> bytes:
    pZh = imbg_parse_payload(Z_h_imgb)
    pZv = imbg_parse_payload(Z_v_imgb)
    pCh = imbg_parse_payload(C_h_imgb)
    pCv = imbg_parse_payload(C_v_imgb)

    out_pay = bytearray(OUT_IMG_BYTES)

    o = 0
    i3 = 0
    k = 0
    while k < N_IMG:
        zh_q12 = _u24_read(pZh, i3) - BIAS_INT
        zv_q12 = _u24_read(pZv, i3) - BIAS_INT
        ch_q12 = _u24_read(pCh, i3) - BIAS_INT
        cv_q12 = _u24_read(pCv, i3) - BIAS_INT

        if ch_q12 < 0:
            ch_q12 = 0
        if cv_q12 < 0:
            cv_q12 = 0

        ch_q12 = _clamp_q12(ch_q12, floor, cap)
        cv_q12 = _clamp_q12(cv_q12, floor, cap)

        # p_h = ch^temperature in Q12.12
        p_h_q12 = _pow_q12_int(ch_q12, temperature)
        p_v_q12 = _pow_q12_int(cv_q12, temperature)

        # numerator: p_h*zh + p_v*zv (each Q12.12*Q12.12 => Q24.24)
        num_q24 = (p_h_q12 * zh_q12) + (p_v_q12 * zv_q12)

        # denominator: p_h + p_v + eps (Q12.12)
        den_q12 = p_h_q12 + p_v_q12 + eps
        if den_q12 <= 0:
            z_q12 = 0
        else:
            # z_q12 = num_q24 / den_q12 -> Q12.12
            if num_q24 >= 0:
                z_q12 = (num_q24 + (den_q12 << (Q_FRAC - 1))) // den_q12
            else:
                z_q12 = -(((-num_q24) + (den_q12 << (Q_FRAC - 1))) // den_q12)

        _u24_write(out_pay, o, _bias_q(z_q12))

        o += BYTES_PER_SAMPLE
        i3 += BYTES_PER_SAMPLE
        k += 1

    return imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(out_pay))
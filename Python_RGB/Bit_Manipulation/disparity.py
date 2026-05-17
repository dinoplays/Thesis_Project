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
    return -(((-x) + 1) >> 1)


# ---------------- fixed-point helpers ----------------

def _div_q12(num_q12: int, den_q12: int) -> int:
    if den_q12 == 0:
        return 0
    if num_q12 >= 0:
        return ((num_q12 << Q_FRAC) + (den_q12 >> 1)) // den_q12
    return -((((-num_q12) << Q_FRAC) + (den_q12 >> 1)) // den_q12)

def _inv_q12(den_q12: int) -> int:
    if den_q12 == 0:
        return 0
    num = (Q_ONE << Q_FRAC)
    if den_q12 > 0:
        return (num + (den_q12 >> 1)) // den_q12
    return -((num + ((-den_q12) >> 1)) // (-den_q12))

def _mul_q12(a_q12: int, b_q12: int) -> int:
    prod = a_q12 * b_q12
    if prod >= 0:
        return (prod + (1 << (Q_FRAC - 1))) >> Q_FRAC
    return -(((-prod) + (1 << (Q_FRAC - 1))) >> Q_FRAC)

def _pow_q12_int(base_q12: int, exp: int) -> int:
    if exp <= 0:
        return Q_ONE
    if exp == 1:
        return base_q12

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

def compute_horizontal_from_epis(
    epi_h_imgb,
    dL_du_h,
    *,
    d=Q_ONE,
    ds=Q_ONE,
    du=Q_ONE,
    win=5,
    channel=0
) -> bytes:
    if channel < 0 or channel > 2:
        raise ValueError(f"channel must be 0, 1 or 2, got {channel}")

    ch_off = (channel << 1) + channel  # channel * 3

    du_over_ds_q12 = _div_q12(du, ds)
    inv_d_q12 = _inv_q12(d)

    out_q = [0 for _ in range(N_IMG)]

    y = 0
    while y < WH_SIZE:
        epi_pay = imbg_parse_payload(epi_h_imgb[y])
        d_pay   = imbg_parse_payload(dL_du_h[y])

        dL_du = [[0] * WH_SIZE for _ in range(EPI_UV)]
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

        # ---- compute dL_ds from epi (central diff along x), selected channel ----
        a = 0
        epi_row_base = 0
        while a < EPI_UV:
            row = dL_ds[a]
            row[0] = 0
            row[WH_SIZE - 1] = 0

            x = 1
            o_m = epi_row_base + ch_off
            o_p = epi_row_base + (BYTES_PER_PIXEL_RGB << 1) + ch_off
            while x < (WH_SIZE - 1):
                Lm = _u24_read(epi_pay, o_m) - BIAS_INT
                Lp = _u24_read(epi_pay, o_p) - BIAS_INT
                row[x] = _round_div2(Lp - Lm)

                o_m += BYTES_PER_PIXEL_RGB
                o_p += BYTES_PER_PIXEL_RGB
                x += 1

            epi_row_base += EPI_ROW_BYTES
            a += 1

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
                duq = row_du[x]
                dsq = row_ds[x]
                row_uv[x] = duq * dsq
                row_uu[x] = duq * duq
                row_w[x]  = _abs_i(duq)
                x += 1
            a += 1

        S_uv = _box_sum_2d_int(P_uv, win)
        S_uu = _box_sum_2d_int(P_uu, win)
        W_b  = _box_sum_2d_int(W_u,  win)

        row_base = y << WH_SHIFT

        x = 0
        while x < WH_SIZE:
            num_acc_q24 = 0
            den_acc_q12 = 0

            a = 0
            while a < EPI_UV:
                w_q12 = W_b[a][x]
                if w_q12 > 0:
                    suu_q24 = S_uu[a][x]
                    if suu_q24 > 0:
                        suv_q24 = S_uv[a][x]
                        k_hat_q12 = (suv_q24 << Q_FRAC) // suu_q24
                        ratio_q12 = (du_over_ds_q12 * k_hat_q12) >> Q_FRAC
                        num_acc_q24 += ratio_q12 * w_q12
                        den_acc_q12 += w_q12
                a += 1

            if den_acc_q12 <= 0:
                D_q12 = 0
            else:
                if num_acc_q24 >= 0:
                    ratio_s_q12 = (num_acc_q24 + (den_acc_q12 << (Q_FRAC - 1))) // den_acc_q12
                else:
                    ratio_s_q12 = -(((-num_acc_q24) + (den_acc_q12 << (Q_FRAC - 1))) // den_acc_q12)

                D_q12 = ((Q_ONE + ratio_s_q12) * inv_d_q12) >> Q_FRAC

            out_q[row_base + x] = D_q12
            x += 1

        y += 1

    out_pay = bytearray(OUT_IMG_BYTES)
    o = 0
    i = 0
    while i < N_IMG:
        _u24_write(out_pay, o, _bias_q(out_q[i]))
        o += BYTES_PER_SAMPLE
        i += 1

    return imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(out_pay))


# ---------------- vertical disparity (Q12.12 only) ----------------

def compute_vertical_from_epis(
    epi_v_imgb,
    dL_dv_v,
    *,
    d=Q_ONE,
    dt=Q_ONE,
    dv=Q_ONE,
    win=5,
    channel=0
) -> bytes:
    if channel < 0 or channel > 2:
        raise ValueError(f"channel must be 0, 1 or 2, got {channel}")

    ch_off = (channel << 1) + channel  # channel * 3

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

        # ---- compute dL_dt from epi (central diff along y), selected channel ----
        a = 0
        epi_row_base = 0
        while a < EPI_UV:
            row = dL_dt[a]
            row[0] = 0
            row[WH_SIZE - 1] = 0

            y = 1
            o_m = epi_row_base + ch_off
            o_p = epi_row_base + (BYTES_PER_PIXEL_RGB << 1) + ch_off
            while y < (WH_SIZE - 1):
                Lm = _u24_read(epi_pay, o_m) - BIAS_INT
                Lp = _u24_read(epi_pay, o_p) - BIAS_INT
                row[y] = _round_div2(Lp - Lm)

                o_m += BYTES_PER_PIXEL_RGB
                o_p += BYTES_PER_PIXEL_RGB
                y += 1

            epi_row_base += EPI_ROW_BYTES
            a += 1

        P_vt = [[0] * WH_SIZE for _ in range(EPI_UV)]
        P_vv = [[0] * WH_SIZE for _ in range(EPI_UV)]
        W_v  = [[0] * WH_SIZE for _ in range(EPI_UV)]

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

def fuse_disparity_precision(
    Z_h_red_imgb: bytes,
    Z_v_red_imgb: bytes,
    C_h_red_imgb: bytes,
    C_v_red_imgb: bytes,
    Z_h_green_imgb: bytes,
    Z_v_green_imgb: bytes,
    C_h_green_imgb: bytes,
    C_v_green_imgb: bytes,
    Z_h_blue_imgb: bytes,
    Z_v_blue_imgb: bytes,
    C_h_blue_imgb: bytes,
    C_v_blue_imgb: bytes,
    *,
    temperature=4,
    floor=1,
    cap=Q_ONE,
    eps=1,
) -> bytes:
    pZh_r = imbg_parse_payload(Z_h_red_imgb)
    pZv_r = imbg_parse_payload(Z_v_red_imgb)
    pCh_r = imbg_parse_payload(C_h_red_imgb)
    pCv_r = imbg_parse_payload(C_v_red_imgb)

    pZh_g = imbg_parse_payload(Z_h_green_imgb)
    pZv_g = imbg_parse_payload(Z_v_green_imgb)
    pCh_g = imbg_parse_payload(C_h_green_imgb)
    pCv_g = imbg_parse_payload(C_v_green_imgb)

    pZh_b = imbg_parse_payload(Z_h_blue_imgb)
    pZv_b = imbg_parse_payload(Z_v_blue_imgb)
    pCh_b = imbg_parse_payload(C_h_blue_imgb)
    pCv_b = imbg_parse_payload(C_v_blue_imgb)

    out_pay = bytearray(OUT_IMG_BYTES)

    o = 0
    i3 = 0
    k = 0

    while k < N_IMG:
        # -------- Read all disparities --------
        zh_r = _u24_read(pZh_r, i3) - BIAS_INT
        zv_r = _u24_read(pZv_r, i3) - BIAS_INT

        zh_g = _u24_read(pZh_g, i3) - BIAS_INT
        zv_g = _u24_read(pZv_g, i3) - BIAS_INT

        zh_b = _u24_read(pZh_b, i3) - BIAS_INT
        zv_b = _u24_read(pZv_b, i3) - BIAS_INT

        # -------- Read all confidences --------
        ch_r = _u24_read(pCh_r, i3) - BIAS_INT
        cv_r = _u24_read(pCv_r, i3) - BIAS_INT

        ch_g = _u24_read(pCh_g, i3) - BIAS_INT
        cv_g = _u24_read(pCv_g, i3) - BIAS_INT

        ch_b = _u24_read(pCh_b, i3) - BIAS_INT
        cv_b = _u24_read(pCv_b, i3) - BIAS_INT

        # -------- Clamp confidence (important) --------
        ch_r = _clamp_q12(ch_r, floor, cap)
        cv_r = _clamp_q12(cv_r, floor, cap)

        ch_g = _clamp_q12(ch_g, floor, cap)
        cv_g = _clamp_q12(cv_g, floor, cap)

        ch_b = _clamp_q12(ch_b, floor, cap)
        cv_b = _clamp_q12(cv_b, floor, cap)

        # -------- Apply temperature --------
        ch_r = _pow_q12_int(ch_r, temperature)
        cv_r = _pow_q12_int(cv_r, temperature)

        ch_g = _pow_q12_int(ch_g, temperature)
        cv_g = _pow_q12_int(cv_g, temperature)

        ch_b = _pow_q12_int(ch_b, temperature)
        cv_b = _pow_q12_int(cv_b, temperature)

        # -------- Numerator (Q24.24) --------
        num = (
            zh_r * ch_r + zv_r * cv_r +
            zh_g * ch_g + zv_g * cv_g +
            zh_b * ch_b + zv_b * cv_b
        )

        # -------- Denominator (Q12.12) --------
        den = (
            ch_r + cv_r +
            ch_g + cv_g +
            ch_b + cv_b
        )

        if den <= eps:
            D_q12 = 0
        else:
            # (Q24.24)/(Q12.12) -> Q12.12
            if num >= 0:
                D_q12 = (num + (den << (Q_FRAC - 1))) // den
            else:
                D_q12 = -(((-num) + (den << (Q_FRAC - 1))) // den)

        _u24_write(out_pay, o, _bias_q(D_q12))

        o += BYTES_PER_SAMPLE
        i3 += BYTES_PER_SAMPLE
        k += 1

    return imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(out_pay))
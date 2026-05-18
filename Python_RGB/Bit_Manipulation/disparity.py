# disparity.py
# Pure-stdlib disparity from PRECOMPUTED EPIs and PRECOMPUTED angular/spatial diffs.
# FULL FIXED-POINT VERSION: NO FLOATS. Everything is signed Q12.12 ints.
#
# RGB bit-manipulative version:
#   - Each channel has its own angular and spatial derivatives from confidence.py.
#   - Per-channel horizontal/vertical disparity is computed using those derivatives.
#   - Final RGB disparity is fused using confidence-weighted RGB fusion.
#
# Assumptions (guaranteed by EPIs.py + pipeline):
#   - Image W = H = WH_SIZE = 512 (= 1<<WH_SHIFT)
#   - Angular A = EPI_UV = 9
#   - dL_du_h[y] is IMGB with (W=512, H=A=9, C=1, dtype_code=4)
#   - dL_dv_v[x] is IMGB with (W=512, H=A=9, C=1, dtype_code=4)
#   - dL_ds_h[y] is IMGB with (W=512, H=A=9, C=1, dtype_code=4)
#   - dL_dt_v[x] is IMGB with (W=512, H=A=9, C=1, dtype_code=4)
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
    if x < 0:
        return -x

    return x


# ---------------- fixed-point helpers ----------------

def _div_q12(num_q12: int, den_q12: int) -> int:
    # (num/den) in Q12.12: (num<<12)/den with rounding.
    if den_q12 == 0:
        return 0

    if num_q12 >= 0:
        return ((num_q12 << Q_FRAC) + (den_q12 >> 1)) // den_q12

    return -((((-num_q12) << Q_FRAC) + (den_q12 >> 1)) // den_q12)


def _inv_q12(den_q12: int) -> int:
    # inv in Q12.12: (1<<24)/den because Q12.12 * Q12.12 => Q24.24.
    if den_q12 == 0:
        return 0

    num = Q_ONE << Q_FRAC

    if den_q12 > 0:
        return (num + (den_q12 >> 1)) // den_q12

    return -((num + ((-den_q12) >> 1)) // (-den_q12))


def _mul_q12(a_q12: int, b_q12: int) -> int:
    # (a*b) in Q12.12 with rounding.
    prod = a_q12 * b_q12

    if prod >= 0:
        return (prod + (1 << (Q_FRAC - 1))) >> Q_FRAC

    return -(((-prod) + (1 << (Q_FRAC - 1))) >> Q_FRAC)


def _pow_q12_int(base_q12: int, exp: int) -> int:
    # Integer exponent in Q12.12, rescaling after each multiply.
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
    if x_q12 < 0:
        x_q12 = 0

    if x_q12 < lo_q12:
        return lo_q12

    if x_q12 > hi_q12:
        return hi_q12

    return x_q12


# ---------------- box sum over 2D plane (zero padded) ----------------
# plane entries are INTs.
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

def compute_horizontal_from_epis(
    epi_h_imgb,
    dL_du_h,
    dL_ds_h,
    *,
    d=Q_ONE,
    ds=Q_ONE,
    du=Q_ONE,
    win=5
) -> bytes:
    # epi_h_imgb is kept in the signature for API consistency with the pipeline.
    # This function now uses precomputed dL_du_h and dL_ds_h only.

    du_over_ds_q12 = _div_q12(du, ds)
    inv_d_q12 = _inv_q12(d)

    out_q = [0 for _ in range(N_IMG)]

    y = 0
    while y < WH_SIZE:
        d_pay = imbg_parse_payload(dL_du_h[y])
        s_pay = imbg_parse_payload(dL_ds_h[y])

        dL_du = [[0] * WH_SIZE for _ in range(EPI_UV)]
        dL_ds = [[0] * WH_SIZE for _ in range(EPI_UV)]

        # ---- fill dL_du and dL_ds ----
        a = 0
        base = 0

        while a < EPI_UV:
            row_du = dL_du[a]
            row_ds = dL_ds[a]

            o = base
            x = 0

            while x < WH_SIZE:
                row_du[x] = _u24_read(d_pay, o) - BIAS_INT
                row_ds[x] = _u24_read(s_pay, o) - BIAS_INT

                o += BYTES_PER_SAMPLE
                x += 1

            base += DIFF_ROW_BYTES
            a += 1

        # ---- build planes ----
        # P_uv, P_uu are Q24.24.
        # W_u is Q12.12.
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

                        # k_hat_q12 = (S_uv/S_uu) in Q12.12.
                        k_hat_q12 = (suv_q24 << Q_FRAC) // suu_q24

                        # ratio_q12 = (du/ds)*k_hat.
                        ratio_q12 = (du_over_ds_q12 * k_hat_q12) >> Q_FRAC

                        # weighted average numerator:
                        # ratio_q12 * w_q12 -> Q24.24
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

                # D = (1 + ratio_s) * inv_d.
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
    dL_dt_v,
    *,
    d=Q_ONE,
    dt=Q_ONE,
    dv=Q_ONE,
    win=5
) -> bytes:
    # epi_v_imgb is kept in the signature for API consistency with the pipeline.
    # This function now uses precomputed dL_dv_v and dL_dt_v only.

    dv_over_dt_q12 = _div_q12(dv, dt)
    inv_d_q12 = _inv_q12(d)

    out_q = [0 for _ in range(N_IMG)]

    x = 0
    while x < WH_SIZE:
        d_pay = imbg_parse_payload(dL_dv_v[x])
        t_pay = imbg_parse_payload(dL_dt_v[x])

        dL_dv = [[0] * WH_SIZE for _ in range(EPI_UV)]
        dL_dt = [[0] * WH_SIZE for _ in range(EPI_UV)]

        # ---- fill dL_dv and dL_dt ----
        a = 0
        base = 0

        while a < EPI_UV:
            row_dv = dL_dv[a]
            row_dt = dL_dt[a]

            o = base
            y = 0

            while y < WH_SIZE:
                row_dv[y] = _u24_read(d_pay, o) - BIAS_INT
                row_dt[y] = _u24_read(t_pay, o) - BIAS_INT

                o += BYTES_PER_SAMPLE
                y += 1

            base += DIFF_ROW_BYTES
            a += 1

        # ---- build planes ----
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


# ---------------- fusion (confidence-weighted RGB, Q12.12 only) ----------------

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

        # -------- Clamp confidences --------
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

        # -------- Numerator: weighted disparity sum --------
        # Each disparity/confidence product is Q24.24.
        num_q24 = (
            zh_r * ch_r + zv_r * cv_r +
            zh_g * ch_g + zv_g * cv_g +
            zh_b * ch_b + zv_b * cv_b
        )

        # -------- Denominator: confidence sum in Q12.12 --------
        den_q12 = (
            ch_r + cv_r +
            ch_g + cv_g +
            ch_b + cv_b +
            eps
        )

        if den_q12 <= 0:
            D_q12 = 0
        else:
            # Q24.24 / Q12.12 -> Q12.12.
            if num_q24 >= 0:
                D_q12 = (num_q24 + (den_q12 << (Q_FRAC - 1))) // den_q12
            else:
                D_q12 = -(((-num_q24) + (den_q12 << (Q_FRAC - 1))) // den_q12)

        _u24_write(out_pay, o, _bias_q(D_q12))

        o += BYTES_PER_SAMPLE
        i3 += BYTES_PER_SAMPLE
        k += 1

    return imgb_make(W=WH_SIZE, H=WH_SIZE, C=1, dtype_code=4, payload=bytes(out_pay))


def fuse_rgb_disparity_precision(
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
    """
    Compatibility wrapper using the RGB confidence-weighted fusion function.
    """
    return fuse_disparity_precision(
        Z_h_red_imgb,
        Z_v_red_imgb,
        C_h_red_imgb,
        C_v_red_imgb,
        Z_h_green_imgb,
        Z_v_green_imgb,
        C_h_green_imgb,
        C_v_green_imgb,
        Z_h_blue_imgb,
        Z_v_blue_imgb,
        C_h_blue_imgb,
        C_v_blue_imgb,
        temperature=temperature,
        floor=floor,
        cap=cap,
        eps=eps,
    )

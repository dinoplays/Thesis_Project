# disparity.py
# Pure-stdlib disparity from PRECOMPUTED EPIs and PRECOMPUTED derivatives.
#
# RGB / Standard No-Libraries version.
#
# NOTE:
# - No robust percentiles here. Visualisation is handled in bin_to_png.py.
# - Fusion uses confidence directly as weights after floor/cap/temperature.
# - Spatial derivatives are supplied by confidence.py to avoid recomputing them.
# - Powered confidence weights are quantised to Q12.12-like precision before
#   fusion. This prevents tiny floating-point background weights from surviving
#   when the fixed-point bit-manipulative version would quantise them to zero.
# - Small positive disparity values are forced to exactly zero so that weak
#   far/background values do not survive as valid positive disparity.
#
# All output IMGB values are dtype_code=4, C=1, biased signed Q12.12.

from utils import (
    imgb_parse,
    imgb_make,
    BIAS_INT,
    Q_SCALE,
    U24_MAX,
)


# ------------------------------------------------------------
# Small positive disparity suppression
# ------------------------------------------------------------
#
# The bit-manipulative version often collapses weak/far/background disparity
# to exactly zero through fixed-point truncation and repeated Q12.12 rescaling.
#
# The standard float version can preserve small positive values. Since your
# bin_to_png.py treats positive disparity as valid and then inverts the display,
# those small positive values become white.
#
# This threshold is applied to the STORED disparity output, not only to PNGs.

SMALL_POSITIVE_ZERO_THRESHOLD = 0.5
SMALL_POSITIVE_ZERO_THRESHOLD_Q12 = int(SMALL_POSITIVE_ZERO_THRESHOLD * Q_SCALE + 0.5)


# ------------------------------------------------------------
# u24 helpers
# ------------------------------------------------------------

def _u24_read(p: bytes, o: int) -> int:
    return p[o] | (p[o + 1] << 8) | (p[o + 2] << 16)


def _u24_write(out: bytearray, o: int, u: int) -> None:
    u &= 0xFFFFFF

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


# ------------------------------------------------------------
# Rounding / quantisation helpers
# ------------------------------------------------------------

def _round_float_to_q12(x: float) -> int:
    """
    Convert float to signed Q12.12 integer with symmetric rounding.

    This replaces:
        int(x * Q_SCALE + 0.5)

    because that expression is wrong for negative values.
    """

    scaled = x * float(Q_SCALE)

    if scaled >= 0.0:
        return int(scaled + 0.5)

    return -int((-scaled) + 0.5)


def _force_small_positive_to_zero_q12(q: int) -> int:
    """
    Force small positive disparity to exactly zero.

    Rule:
        q <= 0                    -> keep as-is
        0 < q <= threshold        -> force to 0
        q > threshold             -> keep as-is

    This intentionally changes the stored disparity output, because the goal is
    to make the standard compute path behave closer to the bit-manipulative path.
    """

    if q > 0 and q <= SMALL_POSITIVE_ZERO_THRESHOLD_Q12:
        return 0

    return q


def _quantise_float_to_q12_float(x: float) -> float:
    """
    Quantise a positive floating-point value to Q12.12 resolution,
    then convert back to float.

    Example:
        if x * 4096 rounds to 0, this returns 0.0.
    """

    q = _round_float_to_q12(x)

    if q <= 0:
        return 0.0

    return float(q) / float(Q_SCALE)


def _confidence_to_weight(
    c: float,
    *,
    floor_f: float,
    cap_f: float,
    temp_f: float,
) -> float:
    """
    Convert confidence into a fusion weight.

    Steps:
        1. Clamp confidence to non-negative.
        2. Apply floor/cap in linear confidence domain.
        3. Apply temperature sharpening.
        4. Quantise powered weight to Q12.12-like precision.

    The quantisation is important for standard-vs-bit alignment.
    Without it, tiny float weights such as (1/4096)^4 survive in the
    standard version, while the fixed-point bit-manipulative version
    effectively rounds them to zero.
    """

    if c < 0.0:
        c = 0.0

    if c < floor_f:
        c = floor_f

    if c > cap_f:
        c = cap_f

    w = c ** temp_f

    return _quantise_float_to_q12_float(w)


# ------------------------------------------------------------
# Box sum over 2D plane
# ------------------------------------------------------------
# Plane shape is (A rows) x (W cols). Returns same shape.

def _box_sum_2d_int(plane: list[list[int]], win: int) -> list[list[int]]:
    if win <= 1:
        return plane

    r = win // 2
    A = len(plane)

    if A <= 0:
        return plane

    W = len(plane[0])

    # Integral image: (A + 1) x (W + 1)
    integ = [[0] * (W + 1) for _ in range(A + 1)]

    for a in range(A):
        row_sum = 0
        ia1 = integ[a + 1]
        ia0 = integ[a]
        prow = plane[a]

        for x in range(W):
            row_sum += prow[x]
            ia1[x + 1] = ia0[x + 1] + row_sum

    out = [[0] * W for _ in range(A)]

    for a in range(A):
        a0 = a - r
        a1 = a + r

        if a0 < 0:
            a0 = 0

        if a1 >= A:
            a1 = A - 1

        ia0 = integ[a0]
        ia1 = integ[a1 + 1]

        for x in range(W):
            x0 = x - r
            x1 = x + r

            if x0 < 0:
                x0 = 0

            if x1 >= W:
                x1 = W - 1

            out[a][x] = (
                ia1[x1 + 1]
                - ia0[x1 + 1]
                - ia1[x0]
                + ia0[x0]
            )

    return out


# ------------------------------------------------------------
# Horizontal disparity
# ------------------------------------------------------------

def compute_horizontal_from_epis(
    epi_h_imgb,
    dL_du_h,
    dL_ds_h,
    *,
    d=1.0,
    ds=1.0,
    du=1.0,
    win=5,
) -> bytes:
    """
    Compute horizontal disparity from precomputed horizontal EPI derivatives.

    Uses:
        dL_du_h: angular derivative
        dL_ds_h: spatial derivative

    Output:
        IMGB dtype_code=4, C=1, biased signed Q12.12

    Small positive disparity values are forced to zero before writing.
    """

    H = len(epi_h_imgb)

    if H == 0:
        raise ValueError("Empty epi_h_imgb")

    W0, A0, C0, dt0, _payload0 = imgb_parse(epi_h_imgb[0])

    if dt0 != 4 or C0 != 3:
        raise ValueError("epi_h_imgb must be dtype_code=4, C=3")

    W = int(W0)
    A = int(A0)

    if len(dL_du_h) != H or len(dL_ds_h) != H:
        raise ValueError("Derivative list length mismatch for horizontal disparity")

    out_q = [0] * (H * W)

    du_over_ds = float(du) / float(ds)
    inv_d = 1.0 / float(d)

    for y in range(H):
        Wd, Ad, Cd, dtd, d_pay = imgb_parse(dL_du_h[y])
        Ws, As, Cs, dts, s_pay = imgb_parse(dL_ds_h[y])

        if int(Wd) != W or int(Ad) != A or Cd != 1 or dtd != 4:
            raise ValueError("dL_du_h blob shape mismatch")

        if int(Ws) != W or int(As) != A or Cs != 1 or dts != 4:
            raise ValueError("dL_ds_h blob shape mismatch")

        dL_du = [[0] * W for _ in range(A)]
        dL_ds = [[0] * W for _ in range(A)]

        for a in range(A):
            base = (a * W) * 3

            row_du = dL_du[a]
            row_ds = dL_ds[a]

            for x in range(W):
                off = base + x * 3
                row_du[x] = _u24_read(d_pay, off) - BIAS_INT
                row_ds[x] = _u24_read(s_pay, off) - BIAS_INT

        P_uv = [[0] * W for _ in range(A)]
        P_uu = [[0] * W for _ in range(A)]
        W_u = [[0] * W for _ in range(A)]

        for a in range(A):
            row_du = dL_du[a]
            row_ds = dL_ds[a]
            row_uv = P_uv[a]
            row_uu = P_uu[a]
            row_w = W_u[a]

            for x in range(W):
                duq = row_du[x]
                dsq = row_ds[x]

                row_uv[x] = duq * dsq
                row_uu[x] = duq * duq
                row_w[x] = _abs_i(duq)

        S_uv = _box_sum_2d_int(P_uv, win)
        S_uu = _box_sum_2d_int(P_uu, win)
        W_b = _box_sum_2d_int(W_u, win)

        row_base = y * W

        for x in range(W):
            num = 0.0
            den = 0.0

            for a in range(A):
                w = float(W_b[a][x])

                if w <= 0.0:
                    continue

                suu = S_uu[a][x]

                if suu <= 0:
                    continue

                k_hat = float(S_uv[a][x]) / float(suu)
                ratio = du_over_ds * k_hat

                num += ratio * w
                den += w

            if den <= 0.0:
                D = 0.0
            else:
                ratio_s = num / den
                D = (1.0 + ratio_s) * inv_d

            D_q12 = _round_float_to_q12(D)
            D_q12 = _force_small_positive_to_zero_q12(D_q12)

            out_q[row_base + x] = D_q12

    out_pay = bytearray(H * W * 3)

    for i in range(H * W):
        _u24_write(out_pay, i * 3, _bias_q(out_q[i]))

    return imgb_make(
        W=W,
        H=H,
        C=1,
        dtype_code=4,
        payload=bytes(out_pay),
    )


# ------------------------------------------------------------
# Vertical disparity
# ------------------------------------------------------------

def compute_vertical_from_epis(
    epi_v_imgb,
    dL_dv_v,
    dL_dt_v,
    *,
    d=1.0,
    dt=1.0,
    dv=1.0,
    win=5,
) -> bytes:
    """
    Compute vertical disparity from precomputed vertical EPI derivatives.

    Uses:
        dL_dv_v: angular derivative
        dL_dt_v: spatial derivative

    Output:
        IMGB dtype_code=4, C=1, biased signed Q12.12

    Small positive disparity values are forced to zero before writing.
    """

    W = len(epi_v_imgb)

    if W == 0:
        raise ValueError("Empty epi_v_imgb")

    H0, A0, C0, dt0, _payload0 = imgb_parse(epi_v_imgb[0])

    if dt0 != 4 or C0 != 3:
        raise ValueError("epi_v_imgb must be dtype_code=4, C=3")

    H = int(H0)
    A = int(A0)

    if len(dL_dv_v) != W or len(dL_dt_v) != W:
        raise ValueError("Derivative list length mismatch for vertical disparity")

    out_q = [0] * (H * W)

    dv_over_dt = float(dv) / float(dt)
    inv_d = 1.0 / float(d)

    for x in range(W):
        Hd, Ad, Cd, dtd, d_pay = imgb_parse(dL_dv_v[x])
        Hs, As, Cs, dts, t_pay = imgb_parse(dL_dt_v[x])

        if int(Hd) != H or int(Ad) != A or Cd != 1 or dtd != 4:
            raise ValueError("dL_dv_v blob shape mismatch")

        if int(Hs) != H or int(As) != A or Cs != 1 or dts != 4:
            raise ValueError("dL_dt_v blob shape mismatch")

        dL_dv = [[0] * H for _ in range(A)]
        dL_dt = [[0] * H for _ in range(A)]

        for a in range(A):
            base = (a * H) * 3

            row_dv = dL_dv[a]
            row_dt = dL_dt[a]

            for y in range(H):
                off = base + y * 3
                row_dv[y] = _u24_read(d_pay, off) - BIAS_INT
                row_dt[y] = _u24_read(t_pay, off) - BIAS_INT

        P_vt = [[0] * H for _ in range(A)]
        P_vv = [[0] * H for _ in range(A)]
        W_v = [[0] * H for _ in range(A)]

        for a in range(A):
            row_dv = dL_dv[a]
            row_dt = dL_dt[a]
            row_vt = P_vt[a]
            row_vv = P_vv[a]
            row_w = W_v[a]

            for y in range(H):
                dvq = row_dv[y]
                dtq = row_dt[y]

                row_vt[y] = dvq * dtq
                row_vv[y] = dvq * dvq
                row_w[y] = _abs_i(dvq)

        S_vt = _box_sum_2d_int(P_vt, win)
        S_vv = _box_sum_2d_int(P_vv, win)
        W_b = _box_sum_2d_int(W_v, win)

        for y in range(H):
            num = 0.0
            den = 0.0

            for a in range(A):
                w = float(W_b[a][y])

                if w <= 0.0:
                    continue

                svv = S_vv[a][y]

                if svv <= 0:
                    continue

                k_hat = float(S_vt[a][y]) / float(svv)
                ratio = dv_over_dt * k_hat

                num += ratio * w
                den += w

            if den <= 0.0:
                D = 0.0
            else:
                ratio_t = num / den
                D = (1.0 + ratio_t) * inv_d

            D_q12 = _round_float_to_q12(D)
            D_q12 = _force_small_positive_to_zero_q12(D_q12)

            out_q[y * W + x] = D_q12

    out_pay = bytearray(H * W * 3)

    for i in range(H * W):
        _u24_write(out_pay, i * 3, _bias_q(out_q[i]))

    return imgb_make(
        W=W,
        H=H,
        C=1,
        dtype_code=4,
        payload=bytes(out_pay),
    )


# ------------------------------------------------------------
# Two-map confidence-weighted fusion
# ------------------------------------------------------------

def fuse_disparity_precision(
    Z_h_imgb: bytes,
    Z_v_imgb: bytes,
    C_h_imgb: bytes,
    C_v_imgb: bytes,
    *,
    temperature=4.0,
    floor=1.0 / 4096.0,
    cap=1.0,
    eps=1.0 / 4096.0,
) -> bytes:
    """
    Confidence-weighted horizontal/vertical fusion.

    The weight is:

        w = quantise_Q12_12(clamp(confidence, floor, cap) ** temperature)

    The fused output also applies the small-positive-to-zero rule.
    """

    W1, H1, C1, dt1, pZh = imgb_parse(Z_h_imgb)
    W2, H2, C2, dt2, pZv = imgb_parse(Z_v_imgb)
    W3, H3, C3, dt3, pCh = imgb_parse(C_h_imgb)
    W4, H4, C4, dt4, pCv = imgb_parse(C_v_imgb)

    if not (W1 == W2 == W3 == W4 and H1 == H2 == H3 == H4):
        raise ValueError("fusion: dimension mismatch")

    if not (C1 == C2 == C3 == C4 == 1 and dt1 == dt2 == dt3 == dt4 == 4):
        raise ValueError("fusion: expects dtype_code=4, C=1")

    W = int(W1)
    H = int(H1)
    n = W * H

    floor_f = float(floor)
    cap_f = float(cap)
    temp_f = float(temperature)
    eps_f = float(eps)

    out_pay = bytearray(n * 3)

    for i in range(n):
        o = i * 3

        zh = float(_u24_read(pZh, o) - BIAS_INT) / float(Q_SCALE)
        zv = float(_u24_read(pZv, o) - BIAS_INT) / float(Q_SCALE)
        ch = float(_u24_read(pCh, o) - BIAS_INT) / float(Q_SCALE)
        cv = float(_u24_read(pCv, o) - BIAS_INT) / float(Q_SCALE)

        p_h = _confidence_to_weight(
            ch,
            floor_f=floor_f,
            cap_f=cap_f,
            temp_f=temp_f,
        )

        p_v = _confidence_to_weight(
            cv,
            floor_f=floor_f,
            cap_f=cap_f,
            temp_f=temp_f,
        )

        num = (p_h * zh) + (p_v * zv)
        den = p_h + p_v + eps_f

        if den <= 0.0:
            z = 0.0
        else:
            z = num / den

        q = _round_float_to_q12(z)
        q = _force_small_positive_to_zero_q12(q)

        _u24_write(out_pay, o, _bias_q(q))

    return imgb_make(
        W=W,
        H=H,
        C=1,
        dtype_code=4,
        payload=bytes(out_pay),
    )


# ------------------------------------------------------------
# RGB confidence-weighted fusion
# ------------------------------------------------------------

def fuse_rgb_disparity_precision(
    Z_h_red: bytes,
    Z_v_red: bytes,
    C_h_red: bytes,
    C_v_red: bytes,
    Z_h_green: bytes,
    Z_v_green: bytes,
    C_h_green: bytes,
    C_v_green: bytes,
    Z_h_blue: bytes,
    Z_v_blue: bytes,
    C_h_blue: bytes,
    C_v_blue: bytes,
    *,
    temperature=4.0,
    floor=1.0 / 4096.0,
    cap=1.0,
    eps=1.0 / 4096.0,
) -> bytes:
    """
    Confidence-weighted RGB disparity fusion.

    Per channel, horizontal and vertical estimates are weighted by their
    corresponding confidence. The final fused output is:

        Z = (
              Z_hr*w(C_hr) + Z_vr*w(C_vr)
            + Z_hg*w(C_hg) + Z_vg*w(C_vg)
            + Z_hb*w(C_hb) + Z_vb*w(C_vb)
        ) / (
              w(C_hr) + w(C_vr)
            + w(C_hg) + w(C_vg)
            + w(C_hb) + w(C_vb)
            + eps
        )

    where:

        w(C) = quantise_Q12_12(clamp(C, floor, cap) ** temperature)

    The final fused output also applies the small-positive-to-zero rule.
    """

    blobs = [
        Z_h_red,
        Z_v_red,
        C_h_red,
        C_v_red,
        Z_h_green,
        Z_v_green,
        C_h_green,
        C_v_green,
        Z_h_blue,
        Z_v_blue,
        C_h_blue,
        C_v_blue,
    ]

    parsed = [imgb_parse(b) for b in blobs]
    W0, H0, C0, dt0, _payload0 = parsed[0]

    for W, H, C, dt, _payload in parsed:
        if W != W0 or H != H0:
            raise ValueError("RGB fusion: dimension mismatch")

        if C != 1 or dt != 4:
            raise ValueError("RGB fusion expects dtype_code=4, C=1 for all inputs")

    payloads = [p for _W, _H, _C, _dt, p in parsed]

    W = int(W0)
    H = int(H0)
    n = W * H

    floor_f = float(floor)
    cap_f = float(cap)
    temp_f = float(temperature)
    eps_f = float(eps)

    out_pay = bytearray(n * 3)

    for i in range(n):
        o = i * 3

        zh_r = float(_u24_read(payloads[0], o) - BIAS_INT) / float(Q_SCALE)
        zv_r = float(_u24_read(payloads[1], o) - BIAS_INT) / float(Q_SCALE)
        ch_r = float(_u24_read(payloads[2], o) - BIAS_INT) / float(Q_SCALE)
        cv_r = float(_u24_read(payloads[3], o) - BIAS_INT) / float(Q_SCALE)

        zh_g = float(_u24_read(payloads[4], o) - BIAS_INT) / float(Q_SCALE)
        zv_g = float(_u24_read(payloads[5], o) - BIAS_INT) / float(Q_SCALE)
        ch_g = float(_u24_read(payloads[6], o) - BIAS_INT) / float(Q_SCALE)
        cv_g = float(_u24_read(payloads[7], o) - BIAS_INT) / float(Q_SCALE)

        zh_b = float(_u24_read(payloads[8], o) - BIAS_INT) / float(Q_SCALE)
        zv_b = float(_u24_read(payloads[9], o) - BIAS_INT) / float(Q_SCALE)
        ch_b = float(_u24_read(payloads[10], o) - BIAS_INT) / float(Q_SCALE)
        cv_b = float(_u24_read(payloads[11], o) - BIAS_INT) / float(Q_SCALE)

        values_and_confidences = [
            (zh_r, ch_r),
            (zv_r, cv_r),
            (zh_g, ch_g),
            (zv_g, cv_g),
            (zh_b, ch_b),
            (zv_b, cv_b),
        ]

        num = 0.0
        den = eps_f

        for z, c in values_and_confidences:
            w = _confidence_to_weight(
                c,
                floor_f=floor_f,
                cap_f=cap_f,
                temp_f=temp_f,
            )

            if w <= 0.0:
                continue

            num += w * z
            den += w

        if den <= 0.0:
            z_out = 0.0
        else:
            z_out = num / den

        q = _round_float_to_q12(z_out)
        q = _force_small_positive_to_zero_q12(q)

        _u24_write(out_pay, o, _bias_q(q))

    return imgb_make(
        W=W,
        H=H,
        C=1,
        dtype_code=4,
        payload=bytes(out_pay),
    )
# disparity.py
# Pure-stdlib disparity from PRECOMPUTED EPIs and PRECOMPUTED angular diffs.
#
# NOTE:
# - No robust percentiles here. Visualization is handled in bin_to_png.py.
# - Fusion uses confidence directly as weights (after floor/cap), no percentile normalization.

from utils import (
    imgb_parse,
    imbg_parse_payload,
    imgb_make,
    BIAS_INT,
    Q_SCALE,
    U24_MAX,
)

# ---------------- u24 helpers (local, fast) ----------------

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
    return -x if x < 0 else x

def _round_div2(x: int) -> int:
    if x >= 0:
        return (x + 1) >> 1
    return -(((-x) + 1) >> 1)


# ---------------- box sum over 2D plane (zero padded) ----------------
# Plane shape is (A rows) x (W cols). Returns same shape.

def _box_sum_2d_int(plane: list[list[int]], win: int) -> list[list[int]]:
    if win <= 1:
        return plane

    r = win // 2
    A = len(plane)
    W = len(plane[0]) if A > 0 else 0

    # integral image: (A+1)x(W+1)
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

            s = ia1[x1 + 1] - ia0[x1 + 1] - ia1[x0] + ia0[x0]
            out[a][x] = s

    return out


# ---------------- horizontal disparity ----------------

def compute_horizontal_from_epis(epi_h_imgb, dL_du_h, *, d=1.0, ds=1.0, du=1.0, win=5) -> bytes:
    H = len(epi_h_imgb)
    if H == 0:
        raise ValueError("Empty epi_h_imgb")

    W0, A0, C0, dt0, _ = imgb_parse(epi_h_imgb[0])
    if dt0 != 4 or C0 != 3:
        raise ValueError("epi_h_imgb must be dtype_code=4, C=3")

    W = int(W0)
    A = int(A0)

    out_q = [0] * (H * W)

    BPP = 9  # 3 channels * 3 bytes
    du_over_ds = float(du) / float(ds)
    inv_d = 1.0 / float(d)

    for y in range(H):
        epi_pay = imbg_parse_payload(epi_h_imgb[y])
        Wd, Ad, Cd, dtd, d_pay = imgb_parse(dL_du_h[y])
        if int(Wd) != W or int(Ad) != A or Cd != 1 or dtd != 4:
            raise ValueError("dL_du_h blob shape mismatch")

        dL_du = [[0] * W for _ in range(A)]
        dL_ds = [[0] * W for _ in range(A)]

        # fill dL_du
        for a in range(A):
            base = (a * W) * 3
            row = dL_du[a]
            for x in range(W):
                row[x] = _u24_read(d_pay, base + x * 3) - BIAS_INT

        # compute dL_ds from epi (central diff along x) using channel 0
        for a in range(A):
            for x in range(W):
                if x == 0 or x == W - 1:
                    dL_ds[a][x] = 0
                else:
                    o_m = ((a * W + (x - 1)) * BPP)
                    o_p = ((a * W + (x + 1)) * BPP)
                    Lm = _u24_read(epi_pay, o_m) - BIAS_INT
                    Lp = _u24_read(epi_pay, o_p) - BIAS_INT
                    dL_ds[a][x] = _round_div2(Lp - Lm)

        P_uv = [[0] * W for _ in range(A)]
        P_uu = [[0] * W for _ in range(A)]
        W_u  = [[0] * W for _ in range(A)]

        for a in range(A):
            row_du = dL_du[a]
            row_ds = dL_ds[a]
            row_uv = P_uv[a]
            row_uu = P_uu[a]
            row_w  = W_u[a]
            for x in range(W):
                duq = row_du[x]
                dsq = row_ds[x]
                row_uv[x] = duq * dsq
                row_uu[x] = duq * duq
                row_w[x]  = _abs_i(duq)

        S_uv = _box_sum_2d_int(P_uv, win)
        S_uu = _box_sum_2d_int(P_uu, win)
        W_b  = _box_sum_2d_int(W_u,  win)

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

            out_q[row_base + x] = int(D * float(Q_SCALE) + 0.5)

    out_pay = bytearray(H * W * 3)
    for i in range(H * W):
        _u24_write(out_pay, i * 3, _bias_q(out_q[i]))

    return imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(out_pay))


# ---------------- vertical disparity ----------------

def compute_vertical_from_epis(epi_v_imgb, dL_dv_v, *, d=1.0, dt=1.0, dv=1.0, win=5) -> bytes:
    W = len(epi_v_imgb)
    if W == 0:
        raise ValueError("Empty epi_v_imgb")

    H0, A0, C0, dt0, _ = imgb_parse(epi_v_imgb[0])
    if dt0 != 4 or C0 != 3:
        raise ValueError("epi_v_imgb must be dtype_code=4, C=3")

    H = int(H0)
    A = int(A0)

    out_q = [0] * (H * W)

    BPP = 9
    dv_over_dt = float(dv) / float(dt)
    inv_d = 1.0 / float(d)

    for x in range(W):
        epi_pay = imbg_parse_payload(epi_v_imgb[x])
        Hd, Ad, Cd, dtd, d_pay = imgb_parse(dL_dv_v[x])
        if int(Hd) != H or int(Ad) != A or Cd != 1 or dtd != 4:
            raise ValueError("dL_dv_v blob shape mismatch")

        dL_dv = [[0] * H for _ in range(A)]
        dL_dt = [[0] * H for _ in range(A)]

        for a in range(A):
            base = (a * H) * 3
            row = dL_dv[a]
            for y in range(H):
                row[y] = _u24_read(d_pay, base + y * 3) - BIAS_INT

        for a in range(A):
            for y in range(H):
                if y == 0 or y == H - 1:
                    dL_dt[a][y] = 0
                else:
                    o_m = ((a * H + (y - 1)) * BPP)
                    o_p = ((a * H + (y + 1)) * BPP)
                    Lm = _u24_read(epi_pay, o_m) - BIAS_INT
                    Lp = _u24_read(epi_pay, o_p) - BIAS_INT
                    dL_dt[a][y] = _round_div2(Lp - Lm)

        P_vt = [[0] * H for _ in range(A)]
        P_vv = [[0] * H for _ in range(A)]
        W_v  = [[0] * H for _ in range(A)]

        for a in range(A):
            row_dv = dL_dv[a]
            row_dt = dL_dt[a]
            row_vt = P_vt[a]
            row_vv = P_vv[a]
            row_w  = W_v[a]
            for y in range(H):
                dvq = row_dv[y]
                dtq = row_dt[y]
                row_vt[y] = dvq * dtq
                row_vv[y] = dvq * dvq
                row_w[y]  = _abs_i(dvq)

        S_vt = _box_sum_2d_int(P_vt, win)
        S_vv = _box_sum_2d_int(P_vv, win)
        W_b  = _box_sum_2d_int(W_v,  win)

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

            out_q[y * W + x] = int(D * float(Q_SCALE) + 0.5)

    out_pay = bytearray(H * W * 3)
    for i in range(H * W):
        _u24_write(out_pay, i * 3, _bias_q(out_q[i]))

    return imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(out_pay))


# ---------------- fusion (confidence-weighted, no percentile) ----------------

def fuse_disparity_precision(
    Z_h_imgb: bytes,
    Z_v_imgb: bytes,
    C_h_imgb: bytes,
    C_v_imgb: bytes,
    *,
    temperature=4.0,
    floor=1.0 / 4096.0,
    cap=1.0,
    eps=1e-6,
) -> bytes:
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

    out_pay = bytearray(n * 3)

    for i in range(n):
        zh = float((_u24_read(pZh, i * 3) - BIAS_INT)) / float(Q_SCALE)
        zv = float((_u24_read(pZv, i * 3) - BIAS_INT)) / float(Q_SCALE)
        ch = float((_u24_read(pCh, i * 3) - BIAS_INT)) / float(Q_SCALE)
        cv = float((_u24_read(pCv, i * 3) - BIAS_INT)) / float(Q_SCALE)

        # Confidence should be >=0; still guard:
        if ch < 0.0:
            ch = 0.0
        if cv < 0.0:
            cv = 0.0

        # floor/cap in linear domain
        if ch < floor_f:
            ch = floor_f
        if cv < floor_f:
            cv = floor_f
        if ch > cap_f:
            ch = cap_f
        if cv > cap_f:
            cv = cap_f

        p_h = ch ** temp_f
        p_v = cv ** temp_f

        num = p_h * zh + p_v * zv
        den = p_h + p_v + float(eps)
        z = num / den

        q = int(z * float(Q_SCALE) + 0.5)
        _u24_write(out_pay, i * 3, _bias_q(q))

    return imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(out_pay))
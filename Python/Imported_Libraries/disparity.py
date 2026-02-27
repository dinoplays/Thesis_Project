# disparity.py
# Gradient-based disparity computed from PRECOMPUTED EPIs.
# Reuses angular diffs computed in confidence.py (no recompute).
#
# Inputs:
#   epi_h_rgb: (H, A, W, 3)
#   dL_du_h  : (H, A, W)  from confidence
#
#   epi_v_rgb: (W, A, H, 3)
#   dL_dv_v  : (W, A, H)  from confidence

import os
import numpy as np
import matplotlib.pyplot as plt

from utils import _central_diff_valid, save_png_robust, save_npy

EPS = 1 / 4096


def _box_sum_2d(A: np.ndarray, wy=5, wx=5):
    A = A.astype(np.float32)
    m = np.isfinite(A).astype(np.float32)
    A = np.nan_to_num(A, nan=0.0)

    cA = np.cumsum(A, axis=1)
    cm = np.cumsum(m, axis=1)

    def box1d(c, w):
        left = np.pad(c, ((0, 0), (w, 0), (0, 0)), mode="constant")[:, :-w, :]
        right = np.pad(c, ((0, 0), (0, w), (0, 0)), mode="constant")[:, w:, :]
        return right - left

    A_h = box1d(cA, wx // 2)
    m_h = box1d(cm, wx // 2)

    cA2 = np.cumsum(A_h, axis=0)
    cm2 = np.cumsum(m_h, axis=0)

    def box1d0(c, w):
        top = np.pad(c, ((w, 0), (0, 0), (0, 0)), mode="constant")[:-w, :, :]
        bot = np.pad(c, ((0, w), (0, 0), (0, 0)), mode="constant")[w:, :, :]
        return bot - top

    A_box = box1d0(cA2, wy // 2)
    m_box = box1d0(cm2, wy // 2)

    out = np.where(m_box > 0, A_box, np.nan)
    return out, m_box


def _nanmean_weighted(values: np.ndarray, weights: np.ndarray, axis=0) -> np.ndarray:
    v = np.where(np.isfinite(values), values, 0.0)
    w = np.where(np.isfinite(values), weights, 0.0)

    num = np.sum(v * w, axis=axis)
    den = np.sum(w, axis=axis)

    out = np.full_like(num, np.nan, dtype=np.float32)
    ok = den > 0
    out[ok] = num[ok] / den[ok]
    return out


def compute_horizontal_from_epis(
    epi_h_rgb: np.ndarray,
    dL_du_h: np.ndarray,
    *,
    d=1.0,
    ds=1.0,
    du=1.0,
    win=5,
) -> np.ndarray:
    L = epi_h_rgb[..., 0].astype(np.float32)          # (H, A, W)
    dL_ds = _central_diff_valid(L, axis=2)            # (H, A, W)  spatial along W
    # dL_du_h is already (H, A, W)

    # Rearrange to (A, H, W) to match the original math layout
    dL_du_all = np.transpose(dL_du_h, (1, 0, 2))      # (A, H, W)
    dL_ds_all = np.transpose(dL_ds,   (1, 0, 2))      # (A, H, W)

    P_uv = dL_du_all * dL_ds_all
    P_uu = dL_du_all * dL_du_all
    W_u = np.abs(dL_du_all)

    # box sum expects (A, W, H)
    P_uv2 = np.transpose(P_uv, (0, 2, 1))
    P_uu2 = np.transpose(P_uu, (0, 2, 1))
    W_u2  = np.transpose(W_u,  (0, 2, 1))

    S_uv, _ = _box_sum_2d(P_uv2, wy=win, wx=win)
    S_uu, _ = _box_sum_2d(P_uu2, wy=win, wx=win)
    W_u_b, _ = _box_sum_2d(W_u2, wy=win, wx=win)

    k_hat = S_uv / np.maximum(S_uu, EPS)
    ratio = (du / ds) * k_hat

    # back to (A, H, W)
    ratio = np.transpose(ratio, (0, 2, 1))
    W_u_b = np.transpose(W_u_b, (0, 2, 1))

    ratio_s = _nanmean_weighted(ratio, W_u_b, axis=0)  # (H, W)
    D_s = (1.0 + ratio_s) / d
    return D_s.astype(np.float32)


def compute_vertical_from_epis(
    epi_v_rgb: np.ndarray,
    dL_dv_v: np.ndarray,
    *,
    d=1.0,
    dt=1.0,
    dv=1.0,
    win=5,
) -> np.ndarray:
    L = epi_v_rgb[..., 0].astype(np.float32)          # (W, A, H)
    dL_dt = _central_diff_valid(L, axis=2)            # (W, A, H)  spatial along H
    # dL_dv_v is already (W, A, H)

    # Rearrange to (A, H, W)
    dL_dv_all = np.transpose(dL_dv_v, (1, 2, 0))      # (A, H, W)
    dL_dt_all = np.transpose(dL_dt,   (1, 2, 0))      # (A, H, W)

    P_vt = dL_dv_all * dL_dt_all
    P_vv = dL_dv_all * dL_dv_all
    W_v  = np.abs(dL_dv_all)

    S_vt, _ = _box_sum_2d(P_vt, wy=win, wx=win)
    S_vv, _ = _box_sum_2d(P_vv, wy=win, wx=win)
    W_v_b, _ = _box_sum_2d(W_v,  wy=win, wx=win)

    k_hat = S_vt / np.maximum(S_vv, EPS)
    ratio = (dv / dt) * k_hat

    ratio_t = _nanmean_weighted(ratio, W_v_b, axis=0)  # (H, W)
    D_t = (1.0 + ratio_t) / d
    return D_t.astype(np.float32)


def save(Z: np.ndarray, out_png: str) -> None:
    save_png_robust(Z, out_png)


def _robust_limits(Z, p_lo=2, p_hi=98):
    Z = np.asarray(Z, dtype=np.float32)
    finite = np.isfinite(Z)
    if not finite.any():
        return 0.0, 1.0
    v = Z[finite]
    lo, hi = np.percentile(v, [p_lo, p_hi])
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def _robust_percentile_norm(C, lo=1, hi=99):
    C = C.astype(np.float32, copy=False)
    finite = np.isfinite(C)
    if not finite.any():
        return np.zeros_like(C, np.float32)

    v = C[finite]
    p_lo, p_hi = np.percentile(v, [lo, hi])
    if p_hi <= p_lo:
        p_hi = p_lo + 1e-6

    X = (C - p_lo) / (p_hi - p_lo)
    X = np.clip(X, 0.0, 1.0)
    X[~finite] = np.nan
    return X


def fuse_disparity_precision(
    Ds,
    Dt,
    C_h,
    C_v,
    *,
    temperature=4.0,
    lo=1,
    hi=99,
    floor=1e-3,
    cap=1.0,
    eps=1e-6,
    clip=None,
):
    Ch = _robust_percentile_norm(C_h, lo, hi)
    Cv = _robust_percentile_norm(C_v, lo, hi)

    Ch = np.clip(Ch, floor, cap)
    Cv = np.clip(Cv, floor, cap)
    p_h = np.power(Ch, temperature)
    p_v = np.power(Cv, temperature)

    num = p_h * Ds + p_v * Dt
    den = p_h + p_v + eps
    Z = num / den

    valid = np.isfinite(Ds) & np.isfinite(Dt) & np.isfinite(C_h) & np.isfinite(C_v)
    Z = np.where(valid, Z, np.nan).astype(np.float32)

    if clip is not None:
        Z = np.clip(Z, clip[0], clip[1])

    return Z


def _plot_gray_with_pink_mask(Z, out_png):
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    vmin, vmax = _robust_limits(Z, 2, 98)

    Zm = np.ma.masked_invalid(Z)
    cmap = plt.cm.gray.copy()
    cmap.set_bad(color=(1.0, 0.4, 0.7, 1.0))

    plt.figure(figsize=(6, 6))
    plt.imshow(Zm, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    plt.axis("off")
    plt.tight_layout(pad=0)
    plt.savefig(out_png, dpi=150, bbox_inches="tight", pad_inches=0)
    plt.close()


def save_reliable(Z, C, thresh, out_png):
    mask = np.isfinite(Z) & np.isfinite(C) & (C >= thresh)
    Zm = np.where(mask, Z, np.nan)
    _plot_gray_with_pink_mask(Zm, out_png)
# confidence.py
# Confidence from texture strength using PRECOMPUTED EPIs.
# Also returns angular diffs so disparity doesn't recompute them.
#
# Inputs:
#   epi_h_rgb: (H, A, W, 3)  where epi_h_rgb[y] is (A, W, 3)
#   epi_v_rgb: (W, A, H, 3)  where epi_v_rgb[x] is (A, H, 3)

import numpy as np

from utils import _central_diff_valid, save_png_robust, save_npy


def compute_from_epis_with_diffs(epi_h_rgb: np.ndarray, epi_v_rgb: np.ndarray, channel=None):
    """
    Returns:
      C_h    : (H, W)
      C_v    : (H, W)
      dL_du_h: (H, A, W)  angular diff for horizontal EPIs
      dL_dv_v: (W, A, H)  angular diff for vertical EPIs
    """
    if channel is None:
        Lh = epi_h_rgb[..., 0].astype(np.float32)  # (H, A, W)
        Lv = epi_v_rgb[..., 0].astype(np.float32)  # (W, A, H)
    else:
        Lh = epi_h_rgb[..., channel].astype(np.float32)
        Lv = epi_v_rgb[..., channel].astype(np.float32)

    # Angular diffs (computed ONCE)
    dL_du_h = _central_diff_valid(Lh, axis=1)  # (H, A, W)
    dL_dv_v = _central_diff_valid(Lv, axis=1)  # (W, A, H)

    # Confidence = mean over angular axis of abs angular gradient
    C_h = np.nanmean(np.abs(dL_du_h), axis=1).astype(np.float32)      # (H, W)
    C_v_wh = np.nanmean(np.abs(dL_dv_v), axis=1).astype(np.float32)   # (W, H)
    C_v = np.transpose(C_v_wh, (1, 0)).astype(np.float32)             # (H, W)

    return C_h, C_v, dL_du_h, dL_dv_v


def fuse_avg(C_h: np.ndarray, C_v: np.ndarray) -> np.ndarray:
    return (0.5 * (C_h + C_v)).astype(np.float32)


def save(arr2d: np.ndarray, out_png: str) -> None:
    save_png_robust(arr2d, out_png)
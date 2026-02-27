# utils.py
# Shared utilities used by both confidence.py and disparity.py
# (moved here only when code was exactly identical)

import os
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import imageio.v3 as iio


def _central_diff_valid(arr: np.ndarray, axis: int) -> np.ndarray:
    """
    Central difference with NaN borders (valid only where a 3-sample window exists).
    Matches the exact implementation previously duplicated in confidence.py and disparity.py.
    """
    arr = arr.astype(np.float32, copy=False)
    arr = np.moveaxis(arr, axis, -1)
    L = arr.shape[-1]

    out = np.full_like(arr, np.nan, dtype=np.float32)
    if L >= 3:
        win = sliding_window_view(arr, 3, axis=-1)
        out[..., 1 : L - 1] = 0.5 * (win[..., 2] - win[..., 0])

    return np.moveaxis(out, -1, axis)


def _robust_norm(Z: np.ndarray) -> np.ndarray:
    """
    Robust 2–98 percentile normalization to uint8 [0..255].
    Matches the exact implementation previously duplicated in confidence.py and disparity.py.
    """
    Z = np.asarray(Z, dtype=np.float32)
    finite = np.isfinite(Z)
    if not finite.any():
        return np.zeros_like(Z, np.uint8)

    v = Z[finite]
    lo, hi = np.percentile(v, 2), np.percentile(v, 98)
    if not np.isfinite(lo) or not np.isfinite(hi):
        lo, hi = 0.0, 1.0
    if hi <= lo:
        hi = lo + 1.0

    N = (Z - lo) / (hi - lo)
    N = np.clip(N, 0.0, 1.0)
    N = np.nan_to_num(N, nan=0.0, posinf=1.0, neginf=0.0)
    return (N * 255.0 + 0.5).astype(np.uint8)


def save_png_robust(arr2d: np.ndarray, out_png: str) -> None:
    """
    Save a 2D array as a PNG using _robust_norm.
    Matches the exact behavior previously duplicated in confidence.save() and disparity.save().
    """
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    iio.imwrite(out_png, _robust_norm(arr2d))


def save_npy(arr: np.ndarray, out_npy: str) -> None:
    """
    Save an array as .npy (creating dirs as needed).
    Matches the exact behavior previously duplicated in confidence.save_raw() and disparity.save_raw().
    """
    os.makedirs(os.path.dirname(out_npy), exist_ok=True)
    np.save(out_npy, arr)
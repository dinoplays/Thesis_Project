# EPIs.py
# Loads crops and explicitly builds EPIs ONCE (for reuse in confidence/disparity).

import os, re
import numpy as np
import imageio.v3 as iio

def natkey(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

def to_rgb(img):
    img = img[..., :3]
    return np.clip(img, 0, 255).astype(np.uint8)

def load_cross_crops(cross_dir="cross_data"):
    h_files = sorted([f for f in os.listdir(cross_dir)
                      if f.startswith("h_") and f.lower().endswith(".png")], key=natkey)
    v_files = sorted([f for f in os.listdir(cross_dir)
                      if f.startswith("v_") and f.lower().endswith(".png")], key=natkey)

    h_imgs = [to_rgb(iio.imread(os.path.join(cross_dir, f))) for f in h_files]
    v_imgs = [to_rgb(iio.imread(os.path.join(cross_dir, f))) for f in v_files]

    h_stack = np.stack(h_imgs, axis=0)  # (U,H,W,3)
    v_stack = np.stack(v_imgs, axis=0)  # (V,H,W,3)
    return h_stack, v_stack

# -------------------------------------------------------------------------
# NEW: Build EPIs ONCE and return them for later modules
#
# epi_h_rgb: shape (H, U, W, 3)  where epi_h_rgb[y] = h_stack[:, y, :, :]
# epi_v_rgb: shape (W, V, H, 3)  where epi_v_rgb[x] = v_stack[:, :, x, :]
# -------------------------------------------------------------------------
def build_epis(h_stack: np.ndarray, v_stack: np.ndarray):
    # Horizontal EPIs per row y: (H, U, W, 3)
    epi_h_rgb = np.transpose(h_stack, (1, 0, 2, 3)).copy()

    # Vertical EPIs per col x: (W, V, H, 3)
    # v_stack is (V,H,W,3) -> (W,V,H,3)
    epi_v_rgb = np.transpose(v_stack, (2, 0, 1, 3)).copy()

    return epi_h_rgb, epi_v_rgb

def load_cross_crops_and_build_epis(cross_dir="cross_data"):
    h_stack, v_stack = load_cross_crops(cross_dir)
    epi_h_rgb, epi_v_rgb = build_epis(h_stack, v_stack)
    return epi_h_rgb, epi_v_rgb
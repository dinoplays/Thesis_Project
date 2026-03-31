# cross.py
# Provides a low-pass convolution used prior to EPI construction.

import os
import cv2

# --- Library low-pass -------------------------------

def cv2_low_pass_filter(in_dir: str, kernel_size: int = 5, sigma: float = 0.0, out_dir: str | None = None) -> str:
    """
    Apply a centrally-weighted Gaussian blur to all images in `in_dir`.
    - kernel_size must be odd (3,5,7,...)
    - sigma=0 lets OpenCV choose a good sigma for the kernel size
    """
    names = [n for n in os.listdir(in_dir) if n.lower().endswith(".png")]
    names.sort()

    for name in names:
        src = os.path.join(in_dir, name)
        dst = os.path.join(out_dir, name)

        img = cv2.imread(src, cv2.IMREAD_UNCHANGED)

        blurred = cv2.GaussianBlur(img, (kernel_size, kernel_size), sigmaX=sigma, sigmaY=sigma)

        cv2.imwrite(dst, blurred)

    return out_dir
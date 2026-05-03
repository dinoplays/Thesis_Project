from pathlib import Path
import numpy as np
from PIL import Image


DATASETS = [
    "dino",
    "head",
    "town",
]

OUTPUT_DIR = Path('')


def normalize(arr):
    arr = arr.astype(np.float32)

    valid = np.isfinite(arr)
    if not np.any(valid):
        return np.zeros_like(arr, dtype=np.uint8)

    min_val = np.min(arr[valid])
    max_val = np.max(arr[valid])

    if max_val == min_val:
        return np.zeros_like(arr, dtype=np.uint8)

    norm = (arr - min_val) / (max_val - min_val)
    norm[~valid] = 0

    return np.clip(norm * 255, 0, 255).astype(np.uint8)


def save_npy_as_png(npy_path, png_path):
    arr = np.load(npy_path)
    img_u8 = normalize(arr)

    Image.fromarray(img_u8, mode="L").save(png_path)

    print(f"Saved: {png_path}")
    print(f"  shape: {arr.shape}")
    print(f"  min/max: {np.nanmin(arr)} / {np.nanmax(arr)}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for dataset in DATASETS:
        npy_path = Path(f"disparity_{dataset}_px.npy")
        png_path = OUTPUT_DIR / f"disparity_{dataset}_px.png"

        if not npy_path.exists():
            print(f"Skipping missing file: {npy_path}")
            continue

        save_npy_as_png(npy_path, png_path)


if __name__ == "__main__":
    main()
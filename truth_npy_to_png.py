from pathlib import Path
import numpy as np
from PIL import Image


DATASETS = [
    "dino",
    "head",
    "town",
]


def normalize(arr):
    """
    Normalise an array to uint8 [0, 255].

    The minimum finite value becomes 0.
    The maximum finite value becomes 255.
    Non-finite values are set to 0.
    """
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


def central_crop(arr, crop_size):
    """
    Return the central crop_size x crop_size region of arr.
    """
    height = arr.shape[0]
    width = arr.shape[1]

    if crop_size > height or crop_size > width:
        raise ValueError(
            f"Cannot crop {crop_size}x{crop_size} from array with shape {arr.shape}"
        )

    start_y = (height - crop_size) // 2
    start_x = (width - crop_size) // 2

    end_y = start_y + crop_size
    end_x = start_x + crop_size

    return arr[start_y:end_y, start_x:end_x]


def save_normalised_array_outputs(arr, png_path, npy_path):
    """
    Normalise arr to uint8 [0, 255], then save both PNG and NPY versions.
    """
    img_u8 = normalize(arr)

    Image.fromarray(img_u8, mode="L").save(png_path)
    np.save(npy_path, img_u8)

    print(f"Saved PNG: {png_path}")
    print(f"Saved NPY: {npy_path}")
    print(f"  shape: {arr.shape}")
    print(f"  raw min/max: {np.nanmin(arr)} / {np.nanmax(arr)}")
    print(f"  normalised min/max: {np.min(img_u8)} / {np.max(img_u8)}")


def save_npy_as_png_and_crops(npy_path, output_dir):
    """
    Load the full disparity NPY file and save into output_dir:
    - full-size normalised PNG and NPY
    - central 128x128 normalised PNG and NPY
    - central 64x64 normalised PNG and NPY
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    arr = np.load(npy_path)
    base = npy_path.stem

    # Full-size normalised output
    save_normalised_array_outputs(
        arr,
        output_dir / f"{base}.png",
        output_dir / f"{base}_norm.npy",
    )

    # Central 128x128 normalised output
    crop_128 = central_crop(arr, 128)
    save_normalised_array_outputs(
        crop_128,
        output_dir / f"{base}_center_128.png",
        output_dir / f"{base}_center_128_norm.npy",
    )

    # Central 64x64 normalised output
    crop_64 = central_crop(arr, 64)
    save_normalised_array_outputs(
        crop_64,
        output_dir / f"{base}_center_64.png",
        output_dir / f"{base}_center_64_norm.npy",
    )


def main():
    for dataset in DATASETS:
        npy_path = Path(f"truth/{dataset}/disparity_{dataset}_px.npy")

        if not npy_path.exists():
            print(f"Skipping missing file: {npy_path}")
            continue

        output_dir = Path("truth") / dataset

        save_npy_as_png_and_crops(
            npy_path=npy_path,
            output_dir=output_dir,
        )


if __name__ == "__main__":
    main()
from pathlib import Path
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

OVERALL_FOLDERS = [
    "SystemVerilog_HDL_Red",
    "SystemVerilog_HDL_Red_Small",
    "SystemVerilog_HDL_RGB",
]

MODES = [
    "Bit_Manipulation",
    "Standard",
]

DATASETS = [
    "dino",
    "head",
    "town",
]

OUTPUT_ROOT = Path("truth_comparisons")
EDGE_CROP = 4


# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------

def load_png_grayscale(path):
    img = Image.open(path).convert("L")
    return np.asarray(img).astype(np.float32)


def load_truth_npy(path):
    return np.load(path).astype(np.float32)


def central_crop(arr, crop_size):
    h, w = arr.shape[:2]

    if crop_size > h or crop_size > w:
        raise ValueError(
            f"Cannot crop {crop_size}x{crop_size} from array with shape {arr.shape}"
        )

    y0 = (h - crop_size) // 2
    x0 = (w - crop_size) // 2

    return arr[y0:y0 + crop_size, x0:x0 + crop_size]


def remove_outer_edges(arr, edge_crop):
    if edge_crop <= 0:
        return arr

    h, w = arr.shape[:2]

    if 2 * edge_crop >= h or 2 * edge_crop >= w:
        raise ValueError(
            f"Cannot remove {edge_crop} pixels from each edge of array with shape {arr.shape}"
        )

    return arr[edge_crop:-edge_crop, edge_crop:-edge_crop]


def normalize(arr):
    arr = arr.astype(np.float32)

    valid = np.isfinite(arr)
    if not np.any(valid):
        return np.zeros_like(arr, dtype=np.float32)

    min_val = np.min(arr[valid])
    max_val = np.max(arr[valid])

    if max_val == min_val:
        return np.zeros_like(arr, dtype=np.float32)

    out = (arr - min_val) / (max_val - min_val)
    out[~valid] = 0

    return out


def save_png(arr, path):
    arr = np.clip(arr, 0, 1)
    img = Image.fromarray((arr * 255).astype(np.uint8))
    img.save(path)


def save_raw_grayscale_png(arr, path):
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr, mode="L")
    img.save(path)


def make_error_image(estimated, truth):
    return np.abs(estimated - truth)


def safe_divide_disparity_by_confidence(disparity, confidence):
    out = np.zeros_like(disparity, dtype=np.float32)

    valid = confidence > 0
    out[valid] = disparity[valid] / confidence[valid]

    return out


def save_visual_comparison(
    original_display,
    truth,
    disparity,
    disparity_over_confidence,
    error_disparity,
    error_disparity_over_confidence,
    path
):
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))

    images = [
        (original_display, "Original"),
        (disparity_over_confidence, "Disparity"),
        (disparity, "Weighted Disparity"),
        (truth, "Truth"),
        (error_disparity_over_confidence, "Difference: Truth vs Disparity"),
        (error_disparity, "Difference: Truth vs Weighted Disparity"),
    ]

    for ax, (img, title) in zip(axes.flat, images):
        im = ax.imshow(img, cmap="gray", vmin=0, vmax=1)
        ax.set_title(title)
        ax.axis("off")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    plt.tight_layout()
    plt.savefig(path, dpi=200)
    plt.close(fig)


# ------------------------------------------------------------
# Main comparison logic
# ------------------------------------------------------------

def compare_one(
    disparity_png_path,
    confidence_png_path,
    truth_npy_path,
    original_png_path,
    output_dir,
    crop_size
):
    output_dir.mkdir(parents=True, exist_ok=True)

    disparity = load_png_grayscale(disparity_png_path)
    confidence = load_png_grayscale(confidence_png_path)
    truth = load_truth_npy(truth_npy_path)
    original = load_png_grayscale(original_png_path)

    disparity_crop = central_crop(disparity, crop_size)
    confidence_crop = central_crop(confidence, crop_size)
    truth_crop = central_crop(truth, crop_size)
    original_crop = central_crop(original, crop_size)

    disparity_crop = remove_outer_edges(disparity_crop, EDGE_CROP)
    confidence_crop = remove_outer_edges(confidence_crop, EDGE_CROP)
    truth_crop = remove_outer_edges(truth_crop, EDGE_CROP)
    original_crop = remove_outer_edges(original_crop, EDGE_CROP)

    disparity_over_confidence = safe_divide_disparity_by_confidence(
        disparity_crop,
        confidence_crop
    )

    disparity_norm = normalize(disparity_crop)
    disparity_over_confidence_norm = normalize(disparity_over_confidence)
    truth_norm = normalize(truth_crop)

    # Do NOT normalise the original h_04 image.
    # For saved PNG, keep raw 0..255 values.
    # For matplotlib display, only scale to 0..1 because imshow uses vmin=0, vmax=1.
    original_raw_u8 = np.clip(original_crop, 0, 255).astype(np.uint8)
    original_display = original_raw_u8.astype(np.float32) / 255.0

    error_disparity = make_error_image(disparity_norm, truth_norm)
    error_disparity_over_confidence = make_error_image(
        disparity_over_confidence_norm,
        truth_norm
    )

    print(f"{disparity_png_path}")
    print("Disparity min/max:              ", np.min(disparity_crop), np.max(disparity_crop))
    print("Confidence min/max:             ", np.min(confidence_crop), np.max(confidence_crop))
    print("Disparity/confidence min/max:   ", np.min(disparity_over_confidence), np.max(disparity_over_confidence))
    print("Truth min/max:                  ", np.min(truth_crop), np.max(truth_crop))
    print("Original min/max:               ", np.min(original_crop), np.max(original_crop))
    print("Final shape:                    ", disparity_crop.shape)
    print("-----")

    save_raw_grayscale_png(original_raw_u8, output_dir / "original.png")
    save_png(disparity_norm, output_dir / "disparity_normalised.png")
    save_png(disparity_over_confidence_norm, output_dir / "disparity_over_confidence_normalised.png")
    save_png(truth_norm, output_dir / "truth_normalised.png")
    save_png(error_disparity, output_dir / "difference_truth_vs_disparity.png")
    save_png(error_disparity_over_confidence, output_dir / "difference_truth_vs_disparity_over_confidence.png")

    save_visual_comparison(
        original_display,
        truth_norm,
        disparity_norm,
        disparity_over_confidence_norm,
        error_disparity,
        error_disparity_over_confidence,
        output_dir / "visual_comparison.png"
    )

    mae_disparity = np.mean(error_disparity)
    mse_disparity = np.mean(error_disparity ** 2)
    rmse_disparity = np.sqrt(mse_disparity)

    mae_div_conf = np.mean(error_disparity_over_confidence)
    mse_div_conf = np.mean(error_disparity_over_confidence ** 2)
    rmse_div_conf = np.sqrt(mse_div_conf)

    with open(output_dir / "metrics.txt", "w") as f:
        f.write(f"Disparity file:   {disparity_png_path}\n")
        f.write(f"Confidence file:  {confidence_png_path}\n")
        f.write(f"Truth file:       {truth_npy_path}\n")
        f.write(f"Original file:    {original_png_path}\n")
        f.write(f"Initial crop:     {crop_size}x{crop_size}\n")
        f.write(f"Edge removed:     {EDGE_CROP} pixels from each side\n")
        f.write(f"Final size:       {disparity_crop.shape[0]}x{disparity_crop.shape[1]}\n\n")

        f.write("Truth vs Disparity\n")
        f.write(f"MAE:  {mae_disparity:.6f}\n")
        f.write(f"MSE:  {mse_disparity:.6f}\n")
        f.write(f"RMSE: {rmse_disparity:.6f}\n\n")

        f.write("Truth vs Disparity / Confidence\n")
        f.write(f"MAE:  {mae_div_conf:.6f}\n")
        f.write(f"MSE:  {mse_div_conf:.6f}\n")
        f.write(f"RMSE: {rmse_div_conf:.6f}\n")

    print(f"Saved comparison to: {output_dir}")


def main():
    for dataset in DATASETS:
        truth_path = Path(f"disparity_{dataset}_px.npy")

        original_png_path = (
            Path("Python_Red")
            / "Bit_Manipulation"
            / dataset
            / "cross_raw_data_png"
            / "h_04.png"
        )

        if not truth_path.exists():
            print(f"Skipping {dataset}: missing truth file {truth_path}")
            continue

        if not original_png_path.exists():
            print(f"Skipping {dataset}: missing original image {original_png_path}")
            continue

        for overall_folder in OVERALL_FOLDERS:
            for mode in MODES:
                output_data_dir = (
                    Path(overall_folder)
                    / mode
                    / "tb"
                    / dataset
                    / "output_data"
                )

                disparity_png_path = output_data_dir / "fused_weighted_disparity.png"
                confidence_png_path = output_data_dir / "fused_confidence.png"

                if not disparity_png_path.exists():
                    print(f"Skipping missing file: {disparity_png_path}")
                    continue

                if not confidence_png_path.exists():
                    print(f"Skipping missing file: {confidence_png_path}")
                    continue

                if "RGB" in overall_folder or "Small" in overall_folder:
                    crop_size = 64
                else:
                    crop_size = 128

                output_dir = (
                    OUTPUT_ROOT
                    / dataset
                    / overall_folder
                    / mode
                )

                compare_one(
                    disparity_png_path=disparity_png_path,
                    confidence_png_path=confidence_png_path,
                    truth_npy_path=truth_path,
                    original_png_path=original_png_path,
                    output_dir=output_dir,
                    crop_size=crop_size,
                )


if __name__ == "__main__":
    main()
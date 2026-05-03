from pathlib import Path
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm


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
EDGE_CROP = 5

VALID_MIF = "SIM_PIXEL_VALID_OUT.mif"
ROW_MIF = "SIM_ROW_IDX_OUT.mif"
COL_MIF = "SIM_COLUMN_IDX_OUT.mif"
CONF_MIF = "SIM_CONFIDENCE_PIXEL_BIT_DATA.mif"
WDISP_MIF = "SIM_WEIGHTED_DISPARITY_PIXEL_BIT_DATA.mif"

CONF_WIDTH_BITS = 15
CONF_FRAC_BITS = 7

WDISP_WIDTH_BITS = 24
WDISP_FRAC_BITS = 12

ORIGINAL_MAX = 255
TRUTH_MAX = (1 << 16) - 1
Q12_12_MAX = (1 << 24) - 1
DIFF_MAX = 1


# ------------------------------------------------------------
# MIF helpers
# ------------------------------------------------------------

def read_depth_from_mif_header(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("DEPTH=") and stripped.endswith(";"):
                return int(stripped[len("DEPTH="):-1])

    raise ValueError(f"Could not parse DEPTH from {path}")


def parse_content_bits_lines(path):
    addr_to_bits = {}
    in_content = False

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            stripped = raw_line.strip()

            if not in_content:
                if stripped == "CONTENT BEGIN":
                    in_content = True
                continue

            if stripped == "END;":
                break

            if ":" not in stripped or not stripped.endswith(";"):
                continue

            left, right = stripped[:-1].split(":", 1)

            try:
                addr = int(left.strip())
            except ValueError:
                continue

            bits = right.strip().replace(" ", "").lower()
            bits = bits.replace("x", "0")
            bits = bits.replace("z", "0")

            addr_to_bits[addr] = bits

    return addr_to_bits


def load_mif_bits(path, width):
    depth = read_depth_from_mif_header(path)
    addr_to_bits = parse_content_bits_lines(path)

    out = [0] * depth

    for addr, bits in addr_to_bits.items():
        if 0 <= addr < depth:
            if len(bits) > width:
                bits = bits[-width:]
            elif len(bits) < width:
                bits = ("0" * (width - len(bits))) + bits

            try:
                out[addr] = int(bits, 2)
            except ValueError:
                out[addr] = 0

    return out


def twos_complement_to_int(word, width):
    sign_bit = 1 << (width - 1)
    full_mod = 1 << width

    if word & sign_bit:
        return word - full_mod

    return word


def load_mif_bits_signed(path, width):
    raw = load_mif_bits(path, width)
    return [twos_complement_to_int(v, width) for v in raw]


# ------------------------------------------------------------
# General helpers
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

    return arr[edge_crop:-edge_crop, edge_crop:-edge_crop]


def robust_2p_normalise(arr, p_lo=2.0, p_hi=98.0):
    arr = arr.astype(np.float32)

    valid = np.isfinite(arr) & (arr > 0)

    if not np.any(valid):
        return np.zeros_like(arr, dtype=np.float32)

    vals = arr[valid]

    lo = np.percentile(vals, p_lo)
    hi = np.percentile(vals, p_hi)

    if not np.isfinite(lo):
        lo = 0.0
    if not np.isfinite(hi):
        hi = lo + 1.0
    if hi <= lo:
        hi = lo + 1.0

    out = np.zeros_like(arr, dtype=np.float32)

    out[valid] = (arr[valid] - lo) / (hi - lo)
    out[valid] = np.clip(out[valid], 0.0, 1.0)

    return out


def save_png(arr, path):
    arr = np.clip(arr, 0, 1)
    Image.fromarray((arr * 255).astype(np.uint8), mode="L").save(path)


def save_raw_grayscale_png(arr, path):
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    Image.fromarray(arr, mode="L").save(path)


def make_signed_error_image(estimated, truth):
    return estimated - truth


def save_signed_error_rgb(error, path):
    error = np.clip(error, -1.0, 1.0)

    rgb = np.ones((error.shape[0], error.shape[1], 3), dtype=np.float32)

    under = error < 0
    over = error > 0

    # Underestimation: red
    rgb[under, 1] = 1.0 + error[under]
    rgb[under, 2] = 1.0 + error[under]

    # Overestimation: green
    rgb[over, 0] = 1.0 - error[over]
    rgb[over, 2] = 1.0 - error[over]

    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), mode="RGB").save(path)


# ------------------------------------------------------------
# MIF reconstruction
# ------------------------------------------------------------

def reconstruct_fused_from_mif(output_data_dir, image_size):
    valid_path = output_data_dir / VALID_MIF
    row_path = output_data_dir / ROW_MIF
    col_path = output_data_dir / COL_MIF
    conf_path = output_data_dir / CONF_MIF
    wdisp_path = output_data_dir / WDISP_MIF

    required = [
        valid_path,
        row_path,
        col_path,
        conf_path,
        wdisp_path,
    ]

    for path in required:
        if not path.exists():
            raise FileNotFoundError(f"Missing required MIF file: {path}")

    valid = load_mif_bits(valid_path, 1)
    row_idx = load_mif_bits(row_path, 8)
    col_idx = load_mif_bits(col_path, 8)
    conf_q = load_mif_bits(conf_path, CONF_WIDTH_BITS)
    wdisp_q = load_mif_bits_signed(wdisp_path, WDISP_WIDTH_BITS)

    depth = len(valid)

    if (
        len(row_idx) != depth
        or len(col_idx) != depth
        or len(conf_q) != depth
        or len(wdisp_q) != depth
    ):
        raise ValueError(f"MIF DEPTH mismatch in {output_data_dir}")

    confidence = np.full((image_size, image_size), np.nan, dtype=np.float32)
    weighted_disparity = np.full((image_size, image_size), np.nan, dtype=np.float32)

    written = 0

    for i in range(depth):
        if (valid[i] & 1) == 0:
            continue

        y = row_idx[i] & 0xFF
        x = col_idx[i] & 0xFF

        if 0 <= y < image_size and 0 <= x < image_size:
            confidence[y, x] = float(conf_q[i] & 0x7FFF) / float(1 << CONF_FRAC_BITS)
            weighted_disparity[y, x] = float(wdisp_q[i]) / float(1 << WDISP_FRAC_BITS)
            written += 1

    return weighted_disparity, confidence, written


# ------------------------------------------------------------
# Visualisation
# ------------------------------------------------------------

def add_scaled_colourbar(fig, im, ax, label_min, label_max, label):
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    ticks = np.linspace(0.0, 1.0, 5)
    tick_labels = np.linspace(label_min, label_max, 5)

    cbar.set_ticks(ticks)
    cbar.set_ticklabels([f"{int(v)}" for v in tick_labels])
    cbar.set_label(label)

    return cbar

def add_black_border(ax, linewidth=2):
    """
    Adds a visible black border around an axes.

    O(1) operation.
    """
    for spine in ax.spines.values():
        spine.set_edgecolor("black")
        spine.set_linewidth(linewidth)
        spine.set_visible(True)

def save_visual_comparison(
    original_display,
    truth,
    weighted_disparity,
    error_weighted_disparity,
    path
):
    fig, axes = plt.subplots(1, 4, figsize=(18, 5))

    error_cmap = LinearSegmentedColormap.from_list(
        "red_white_green",
        [
            (0.0, "red"),
            (0.5, "white"),
            (1.0, "green"),
        ],
    )

    error_norm = TwoSlopeNorm(vmin=-1.0, vcenter=0.0, vmax=1.0)

    panels = [
        {
            "data": original_display,
            "title": "Original",
            "cmap": "gray",
            "vmin": 0.0,
            "vmax": 1.0,
            "bar_min": 0,
            "bar_max": ORIGINAL_MAX,
            "label": "Pixel value",
            "type": "gray",
        },
        {
            "data": truth,
            "title": "Truth",
            "cmap": "gray",
            "vmin": 0.0,
            "vmax": 1.0,
            "bar_min": 0,
            "bar_max": TRUTH_MAX,
            "label": "Truth value",
            "type": "gray",
        },
        {
            "data": weighted_disparity,
            "title": "Weighted Disparity",
            "cmap": "gray",
            "vmin": 0.0,
            "vmax": 1.0,
            "bar_min": 0,
            "bar_max": Q12_12_MAX,
            "label": "Q12.12 raw value",
            "type": "gray",
        },
        {
            "data": error_weighted_disparity,
            "title": "Scaled Difference",
            "cmap": error_cmap,
            "norm": error_norm,
            "label": "Estimated - Truth",
            "type": "error",
        },
    ]

    for ax, panel in zip(axes, panels):
        if panel["type"] == "gray":
            im = ax.imshow(
                panel["data"],
                cmap=panel["cmap"],
                vmin=panel["vmin"],
                vmax=panel["vmax"],
                interpolation="nearest",
            )

            add_scaled_colourbar(
                fig,
                im,
                ax,
                panel["bar_min"],
                panel["bar_max"],
                panel["label"],
            )

        else:
            im = ax.imshow(
                panel["data"],
                cmap=panel["cmap"],
                norm=panel["norm"],
                interpolation="nearest",
            )

            cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            cbar.set_ticks([-1.0, 0.0, 1.0])
            cbar.set_ticklabels([
                f"-{DIFF_MAX}",
                "0",
                f"{DIFF_MAX}",
            ])
            cbar.set_label(panel["label"])

        ax.set_title(panel["title"])

        # Hide ticks but keep axes frame visible
        ax.set_xticks([])
        ax.set_yticks([])

        # Force visible black image border
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_edgecolor("black")
            spine.set_linewidth(2)

    plt.subplots_adjust(
        left=0.04,
        right=0.98,
        top=0.90,
        bottom=0.08,
        wspace=0.4
    )
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------
# Main comparison
# ------------------------------------------------------------

def compare_one(output_data_dir, truth_npy_path, original_png_path, output_dir, image_size):
    output_dir.mkdir(parents=True, exist_ok=True)

    weighted_disparity, confidence, written = reconstruct_fused_from_mif(
        output_data_dir,
        image_size
    )

    truth = load_truth_npy(truth_npy_path)
    original = load_png_grayscale(original_png_path)

    truth_crop = central_crop(truth, image_size)
    original_crop = central_crop(original, image_size)

    weighted_disparity = remove_outer_edges(weighted_disparity, EDGE_CROP)
    confidence = remove_outer_edges(confidence, EDGE_CROP)
    truth_crop = remove_outer_edges(truth_crop, EDGE_CROP)
    original_crop = remove_outer_edges(original_crop, EDGE_CROP)

    weighted_disparity_norm = robust_2p_normalise(weighted_disparity)
    truth_norm = robust_2p_normalise(truth_crop)

    original_raw_u8 = np.clip(original_crop, 0, 255).astype(np.uint8)
    original_display = original_raw_u8.astype(np.float32) / 255.0

    error_weighted_disparity = make_signed_error_image(weighted_disparity_norm, truth_norm)

    print(output_data_dir)
    print("MIF pixels written:              ", written)
    print("Weighted disparity min/max:      ", np.nanmin(weighted_disparity), np.nanmax(weighted_disparity))
    print("Confidence min/max:              ", np.nanmin(confidence), np.nanmax(confidence))
    print("Truth min/max:                   ", np.nanmin(truth_crop), np.nanmax(truth_crop))
    print("Original min/max:                ", np.nanmin(original_crop), np.nanmax(original_crop))
    print("Final shape:                     ", weighted_disparity.shape)
    print("-----")

    save_raw_grayscale_png(original_raw_u8, output_dir / "original.png")
    save_png(weighted_disparity_norm, output_dir / "weighted_disparity_normalised.png")
    save_png(truth_norm, output_dir / "truth_normalised.png")

    save_signed_error_rgb(
        error_weighted_disparity,
        output_dir / "difference_truth_vs_weighted_disparity.png"
    )

    save_visual_comparison(
        original_display,
        truth_norm,
        weighted_disparity_norm,
        error_weighted_disparity,
        output_dir / "visual_comparison.png"
    )

    mae_weighted = np.mean(np.abs(error_weighted_disparity))
    mse_weighted = np.mean(error_weighted_disparity ** 2)
    rmse_weighted = np.sqrt(mse_weighted)

    with open(output_dir / "metrics.txt", "w") as f:
        f.write(f"Output data dir: {output_data_dir}\n")
        f.write(f"Truth file:      {truth_npy_path}\n")
        f.write(f"Original file:   {original_png_path}\n")
        f.write(f"Image size:      {image_size}x{image_size}\n")
        f.write(f"Edge removed:    {EDGE_CROP} pixels from each side\n")
        f.write(f"Final size:      {weighted_disparity.shape[0]}x{weighted_disparity.shape[1]}\n")
        f.write(f"MIF pixels written: {written}\n\n")

        f.write("Display scales\n")
        f.write(f"Original colourbar: 0 to {ORIGINAL_MAX}\n")
        f.write(f"Truth colourbar: 0 to {TRUTH_MAX}\n")
        f.write(f"Weighted disparity colourbar: 0 to {Q12_12_MAX}\n")
        f.write(f"Difference colourbar: -{DIFF_MAX} to {DIFF_MAX}\n\n")

        f.write("Difference sign convention\n")
        f.write("Difference = estimated - truth\n")
        f.write("Red = underestimation\n")
        f.write("White = zero difference\n")
        f.write("Green = overestimation\n\n")

        f.write("Truth vs Weighted Disparity\n")
        f.write(f"MAE:  {mae_weighted:.6f}\n")
        f.write(f"MSE:  {mse_weighted:.6f}\n")
        f.write(f"RMSE: {rmse_weighted:.6f}\n")

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

                if not output_data_dir.exists():
                    print(f"Skipping missing directory: {output_data_dir}")
                    continue

                if "RGB" in overall_folder or "Small" in overall_folder:
                    image_size = 64
                else:
                    image_size = 128

                output_dir = (
                    OUTPUT_ROOT
                    / dataset
                    / overall_folder
                    / mode
                )

                compare_one(
                    output_data_dir=output_data_dir,
                    truth_npy_path=truth_path,
                    original_png_path=original_png_path,
                    output_dir=output_dir,
                    image_size=image_size,
                )


if __name__ == "__main__":
    main()
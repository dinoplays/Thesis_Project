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
TRUTH_ROOT = Path("truth")

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
TRUTH_MAX = 255
Q12_12_MAX = (1 << 24) - 1
DIFF_MAX = 1

IMGB_BIAS_INT = 8388608
IMGB_Q_FRAC = 12

CONFIDENCE_MASK_THRESHOLD = 1.25
MASK_COLOUR = (1.0, 0.4, 0.7, 1.0)  # pink

# All truth/disparity/comparison displays are now normalised [0, 1].
NORMALISED_MIN = 0.0
NORMALISED_MAX = 1.0


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
# IMGB helpers
# ------------------------------------------------------------

def read_u32_le(buf, offset):
    return int.from_bytes(buf[offset:offset + 4], "little", signed=False)


def parse_imgb(blob):
    if len(blob) < 16:
        raise ValueError("IMGB file too short")

    if blob[0:4] != b"IMGB":
        raise ValueError("Invalid IMGB magic header")

    width = read_u32_le(blob, 4)
    height = read_u32_le(blob, 8)
    channels = blob[12]
    dtype_code = blob[13]
    payload = blob[16:]

    return width, height, channels, dtype_code, payload


def decode_u24_q12_12(payload, n_samples):
    if len(payload) != n_samples * 3:
        raise ValueError(
            f"u24 payload length mismatch: got {len(payload)}, expected {n_samples * 3}"
        )

    b = np.frombuffer(payload, dtype=np.uint8).reshape((-1, 3))

    u24 = (
        b[:, 0].astype(np.uint32)
        | (b[:, 1].astype(np.uint32) << 8)
        | (b[:, 2].astype(np.uint32) << 16)
    )

    signed_q12_12 = u24.astype(np.int32) - np.int32(IMGB_BIAS_INT)

    return signed_q12_12.astype(np.float32) / float(1 << IMGB_Q_FRAC)


def load_imgb_float(path):
    with open(path, "rb") as f:
        blob = f.read()

    width, height, channels, dtype_code, payload = parse_imgb(blob)
    n_samples = width * height * channels

    if dtype_code == 1:
        if len(payload) != n_samples:
            raise ValueError(
                f"Payload length mismatch in {path}: got {len(payload)}, expected {n_samples}"
            )

        arr = np.frombuffer(payload, dtype=np.uint8).astype(np.float32)

    elif dtype_code == 4:
        arr = decode_u24_q12_12(payload, n_samples)

    else:
        raise ValueError(f"Unsupported IMGB dtype_code={dtype_code} in {path}")

    if channels == 1:
        return arr.reshape((height, width))

    return arr.reshape((height, width, channels))


# ------------------------------------------------------------
# General helpers
# ------------------------------------------------------------

def load_png_grayscale(path):
    img = Image.open(path).convert("L")
    return np.asarray(img).astype(np.float32)


def load_truth_normalised_npy(path):
    """
    Loads already centre-cropped and already normalised truth disparity.

    Expected input:
      uint8 or float values in [0, 255], saved from:
        truth/<dataset>/disparity_<dataset>_px_center_<size>_norm.npy

    Output:
      float32 values in [0, 1].
    """
    arr = np.load(path).astype(np.float32)

    if arr.ndim != 2:
        raise ValueError(f"Truth file should be 2D, got shape {arr.shape}: {path}")

    max_val = np.nanmax(arr)
    min_val = np.nanmin(arr)

    if max_val > 1.0:
        arr = arr / 255.0

    arr = np.clip(arr, 0.0, 1.0)

    print(f"Loaded truth: {path}")
    print(f"  raw stored min/max before [0,1] clip: {min_val} / {max_val}")
    print(f"  final min/max: {np.nanmin(arr)} / {np.nanmax(arr)}")

    return arr


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


def normalise_0_100_positive(arr):
    """
    Full-range normalisation using 0-100 percentile range.

    For disparity/depth comparison:
      - only positive finite values define the scale
      - values <= 0 become 0
      - output is in [0, 1]

    Display convention matches bin_to_png.py:
      - smallest positive disparity -> white
      - largest positive disparity  -> black
      - zero/negative disparity     -> black
    """
    arr = arr.astype(np.float32)

    valid = np.isfinite(arr) & (arr > 0.0)

    out = np.zeros_like(arr, dtype=np.float32)

    if not np.any(valid):
        return out

    vals = arr[valid]

    lo = np.percentile(vals, 0.0)
    hi = np.percentile(vals, 100.0)

    if not np.isfinite(lo):
        lo = 0.0

    if not np.isfinite(hi):
        hi = lo + 1.0

    if hi <= lo:
        hi = lo + 1.0

    norm = (arr[valid] - lo) / (hi - lo)
    norm = np.clip(norm, 0.0, 1.0)

    # Match bin_to_png display convention:
    # larger positive disparity becomes darker,
    # smaller positive disparity becomes whiter.
    out[valid] = 1.0 - norm

    return out

def ensure_parent_dir(path):
    """
    Ensure the parent folder for a file path exists.

    This allows saving images/metrics even when the comparison output folders
    do not already exist.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)


def save_png(arr, path):
    ensure_parent_dir(path)

    arr = np.clip(arr, 0, 1)
    Image.fromarray((arr * 255).astype(np.uint8), mode="L").save(path)


def save_raw_grayscale_png(arr, path):
    ensure_parent_dir(path)

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    Image.fromarray(arr, mode="L").save(path)


def make_signed_error_image(estimated, truth):
    return estimated - truth


def save_signed_error_rgb(error, path):
    ensure_parent_dir(path)

    error = np.clip(error, -1.0, 1.0)

    rgb = np.ones((error.shape[0], error.shape[1], 3), dtype=np.float32)

    under = error < 0
    over = error > 0

    rgb[under, 1] = 1.0 + error[under]
    rgb[under, 2] = 1.0 + error[under]

    rgb[over, 0] = 1.0 - error[over]
    rgb[over, 2] = 1.0 - error[over]

    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), mode="RGB").save(path)


def save_fpga_python_visual_comparison(
    original_display,
    python_estimate,
    python_filled_estimate,
    fpga_estimate,
    error_fpga_vs_python,
    error_fpga_vs_python_filled,
    path
):
    ensure_parent_dir(path)

    fig, axes = plt.subplots(2, 3, figsize=(18, 11))

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
            "show_colourbar": False,
        },
        {
            "data": python_estimate,
            "title": "Python Final",
            "cmap": "gray",
            "vmin": 0.0,
            "vmax": 1.0,
            "bar_min": NORMALISED_MIN,
            "bar_max": NORMALISED_MAX,
            "label": "Normalised disparity",
            "type": "gray",
            "show_colourbar": True,
        },
        {
            "data": python_filled_estimate,
            "title": "Python Region Filled",
            "cmap": "gray",
            "vmin": 0.0,
            "vmax": 1.0,
            "bar_min": NORMALISED_MIN,
            "bar_max": NORMALISED_MAX,
            "label": "Normalised disparity",
            "type": "gray",
            "show_colourbar": True,
        },
        {
            "data": fpga_estimate,
            "title": "FPGA",
            "cmap": "gray",
            "vmin": 0.0,
            "vmax": 1.0,
            "bar_min": NORMALISED_MIN,
            "bar_max": NORMALISED_MAX,
            "label": "Normalised disparity",
            "type": "gray",
            "show_colourbar": True,
        },
        {
            "data": error_fpga_vs_python,
            "title": "FPGA - Python Final",
            "cmap": error_cmap,
            "norm": error_norm,
            "label": "FPGA - Python Final",
            "type": "error",
            "show_colourbar": True,
        },
        {
            "data": error_fpga_vs_python_filled,
            "title": "FPGA - Python Filled",
            "cmap": error_cmap,
            "norm": error_norm,
            "label": "FPGA - Python Filled",
            "type": "error",
            "show_colourbar": True,
        },
    ]

    for ax, panel in zip(axes.flatten(), panels):
        if panel["type"] == "gray":
            im = ax.imshow(
                panel["data"],
                cmap=panel["cmap"],
                vmin=panel["vmin"],
                vmax=panel["vmax"],
                interpolation="nearest",
            )

            if panel["show_colourbar"]:
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

            if panel["show_colourbar"]:
                cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
                cbar.set_ticks([-1.0, 0.0, 1.0])
                cbar.set_ticklabels([
                    f"-{DIFF_MAX}",
                    "0",
                    f"{DIFF_MAX}",
                ])
                cbar.set_label(panel["label"])

        ax.set_title(panel["title"])
        ax.set_xticks([])
        ax.set_yticks([])

        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_edgecolor("black")
            spine.set_linewidth(2)

    plt.subplots_adjust(
        left=0.04,
        right=0.98,
        top=0.92,
        bottom=0.06,
        wspace=0.35,
        hspace=0.25,
    )

    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


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

    if float(label_max) <= 1.0:
        cbar.set_ticklabels([f"{v:.2f}" for v in tick_labels])
    else:
        cbar.set_ticklabels([f"{int(v)}" for v in tick_labels])

    cbar.set_label(label)

    return cbar


def save_visual_comparison(
    original_display,
    truth,
    python_estimate,
    python_filled_estimate,
    fpga_estimate,
    error_python,
    error_python_filled,
    error_fpga,
    path
):
    ensure_parent_dir(path)

    fig, axes = plt.subplots(2, 4, figsize=(24, 11))

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
            "show_colourbar": False,
        },
        {
            "data": truth,
            "title": "Truth",
            "cmap": "gray",
            "vmin": 0.0,
            "vmax": 1.0,
            "bar_min": NORMALISED_MIN,
            "bar_max": NORMALISED_MAX,
            "label": "Normalised truth",
            "type": "gray",
            "show_colourbar": True,
        },
        {
            "data": python_estimate,
            "title": "Python Final",
            "cmap": "gray",
            "vmin": 0.0,
            "vmax": 1.0,
            "bar_min": NORMALISED_MIN,
            "bar_max": NORMALISED_MAX,
            "label": "Normalised disparity",
            "type": "gray",
            "show_colourbar": True,
        },
        {
            "data": python_filled_estimate,
            "title": "Python Region Filled",
            "cmap": "gray",
            "vmin": 0.0,
            "vmax": 1.0,
            "bar_min": NORMALISED_MIN,
            "bar_max": NORMALISED_MAX,
            "label": "Normalised disparity",
            "type": "gray",
            "show_colourbar": True,
        },
        {
            "data": fpga_estimate,
            "title": "FPGA",
            "cmap": "gray",
            "vmin": 0.0,
            "vmax": 1.0,
            "bar_min": NORMALISED_MIN,
            "bar_max": NORMALISED_MAX,
            "label": "Normalised disparity",
            "type": "gray",
            "show_colourbar": True,
        },
        {
            "data": error_python,
            "title": "Python Final - Truth",
            "cmap": error_cmap,
            "norm": error_norm,
            "label": "Python Final - Truth",
            "type": "error",
            "show_colourbar": True,
        },
        {
            "data": error_python_filled,
            "title": "Python Filled - Truth",
            "cmap": error_cmap,
            "norm": error_norm,
            "label": "Python Filled - Truth",
            "type": "error",
            "show_colourbar": True,
        },
        {
            "data": error_fpga,
            "title": "FPGA - Truth",
            "cmap": error_cmap,
            "norm": error_norm,
            "label": "FPGA - Truth",
            "type": "error",
            "show_colourbar": True,
        },
    ]

    for ax, panel in zip(axes.flatten(), panels):
        if panel["type"] == "gray":
            im = ax.imshow(
                panel["data"],
                cmap=panel["cmap"],
                vmin=panel["vmin"],
                vmax=panel["vmax"],
                interpolation="nearest",
            )

            if panel["show_colourbar"]:
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

            if panel["show_colourbar"]:
                cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
                cbar.set_ticks([-1.0, 0.0, 1.0])
                cbar.set_ticklabels([
                    f"-{DIFF_MAX}",
                    "0",
                    f"{DIFF_MAX}",
                ])
                cbar.set_label(panel["label"])

        ax.set_title(panel["title"])
        ax.set_xticks([])
        ax.set_yticks([])

        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_edgecolor("black")
            spine.set_linewidth(2)

    plt.subplots_adjust(
        left=0.03,
        right=0.99,
        top=0.92,
        bottom=0.06,
        wspace=0.45,
        hspace=0.25,
    )

    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------
# Metrics helpers
# ------------------------------------------------------------

def normalised_to_uint_bits(arr, bits):
    arr = np.clip(arr, 0.0, 1.0)
    max_val = (1 << bits) - 1
    return np.round(arr * max_val).astype(np.uint32)


def leading_bit_correctness_16(truth_norm, estimate_norm):
    truth_u16 = normalised_to_uint_bits(truth_norm, 16)
    estimate_u24 = normalised_to_uint_bits(estimate_norm, 24)

    estimate_u16 = estimate_u24 >> 8

    correct_counts = np.zeros(truth_u16.shape, dtype=np.uint8)

    for bit_idx in range(15, -1, -1):
        truth_bit = (truth_u16 >> bit_idx) & 1
        estimate_bit = (estimate_u16 >> bit_idx) & 1

        still_matching = correct_counts == (15 - bit_idx)
        bit_matches = truth_bit == estimate_bit

        correct_counts[still_matching & bit_matches] += 1

    return correct_counts, truth_u16, estimate_u16


def summarise_leading_bit_correctness(truth_norm, estimate_norm):
    bit_correctness, truth_u16, estimate_u16 = leading_bit_correctness_16(
        truth_norm,
        estimate_norm
    )

    exact_16bit_match_pixels = int(np.count_nonzero(bit_correctness == 16))
    total_bit_pixels = int(bit_correctness.size)

    return {
        "mean": float(np.mean(bit_correctness)),
        "median": float(np.median(bit_correctness)),
        "best": int(np.max(bit_correctness)),
        "worst": int(np.min(bit_correctness)),
        "exact_pixels": exact_16bit_match_pixels,
        "total_pixels": total_bit_pixels,
        "exact_fraction": exact_16bit_match_pixels / total_bit_pixels,
    }


def compute_error_metrics(estimate_norm, truth_norm):
    error = make_signed_error_image(estimate_norm, truth_norm)

    mae = float(np.mean(np.abs(error)))
    mse = float(np.mean(error ** 2))
    rmse = float(np.sqrt(mse))

    return error, mae, mse, rmse


def write_metric_block(f, title, mae, mse, rmse, bit_summary):
    f.write(f"{title}\n")
    f.write(f"MAE:  {mae:.6f}\n")
    f.write(f"MSE:  {mse:.6f}\n")
    f.write(f"RMSE: {rmse:.6f}\n")

    f.write("\nLeading Bit-Correctness after [0, 1] Normalisation\n")
    f.write("Truth: normalised to [0, 1]\n")
    f.write("Estimate: normalised to [0, 1], converted to 24-bit unsigned, then lower 8 bits dropped\n")
    f.write("Comparison: MSB-first until first incorrect bit\n")
    f.write(f"Mean leading bit-correctness: {bit_summary['mean']:.6f} / 16\n")
    f.write(f"Median leading bit-correctness: {bit_summary['median']:.6f} / 16\n")
    f.write(f"Best leading bit-correctness: {bit_summary['best']} / 16\n")
    f.write(f"Worst leading bit-correctness: {bit_summary['worst']} / 16\n")
    f.write(f"Exact 16-bit match pixels: {bit_summary['exact_pixels']} / {bit_summary['total_pixels']}\n")
    f.write(f"Exact 16-bit match fraction: {bit_summary['exact_fraction']:.6%}\n")

def normalise_0_100_positive_masked(arr, mask):
    """
    Full-range masked normalisation using 0-100 percentile range.

    For masked disparity/depth comparison:
      - only pixels inside mask are considered
      - only positive finite disparity values define the scale
      - values <= 0 are invalid/masked
      - invalid pixels are returned as NaN

    Display convention matches bin_to_png.py:
      - smallest valid positive disparity -> white
      - largest valid positive disparity  -> black
      - invalid/non-positive pixels       -> NaN/pink in masked plots
    """
    arr = arr.astype(np.float32)
    mask = mask.astype(bool)

    valid = np.isfinite(arr) & mask & (arr > 0.0)

    out = np.full(arr.shape, np.nan, dtype=np.float32)

    if not np.any(valid):
        return out

    vals = arr[valid]

    lo = np.percentile(vals, 0.0)
    hi = np.percentile(vals, 100.0)

    if not np.isfinite(lo):
        lo = 0.0

    if not np.isfinite(hi):
        hi = lo + 1.0

    if hi <= lo:
        hi = lo + 1.0

    norm = (arr[valid] - lo) / (hi - lo)
    norm = np.clip(norm, 0.0, 1.0)

    # Match bin_to_png display convention.
    out[valid] = 1.0 - norm

    return out


def compute_error_metrics_masked(estimate_norm, truth_norm, mask):
    valid = (
        np.isfinite(estimate_norm)
        & np.isfinite(truth_norm)
        & mask.astype(bool)
    )

    error = np.full(truth_norm.shape, np.nan, dtype=np.float32)

    if not np.any(valid):
        return error, float("nan"), float("nan"), float("nan"), 0

    error[valid] = estimate_norm[valid] - truth_norm[valid]

    mae = float(np.mean(np.abs(error[valid])))
    mse = float(np.mean(error[valid] ** 2))
    rmse = float(np.sqrt(mse))

    return error, mae, mse, rmse, int(np.count_nonzero(valid))


def save_masked_gray_png(arr_norm, path):
    ensure_parent_dir(path)

    arr = np.asarray(arr_norm, dtype=np.float32)

    cmap = plt.cm.gray.copy()
    cmap.set_bad(color=MASK_COLOUR)

    masked = np.ma.masked_invalid(arr)

    plt.figure(figsize=(6, 6))
    plt.imshow(masked, cmap=cmap, vmin=0.0, vmax=1.0, interpolation="nearest")
    plt.axis("off")
    plt.tight_layout(pad=0)
    plt.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0)
    plt.close()


def save_masked_signed_error_rgb(error, path):
    ensure_parent_dir(path)

    error = np.asarray(error, dtype=np.float32)

    rgb = np.ones((error.shape[0], error.shape[1], 3), dtype=np.float32)

    invalid = ~np.isfinite(error)
    valid = np.isfinite(error)

    err = np.zeros_like(error, dtype=np.float32)
    err[valid] = np.clip(error[valid], -1.0, 1.0)

    under = valid & (err < 0)
    over = valid & (err > 0)

    rgb[under, 1] = 1.0 + err[under]
    rgb[under, 2] = 1.0 + err[under]

    rgb[over, 0] = 1.0 - err[over]
    rgb[over, 2] = 1.0 - err[over]

    rgb[invalid, 0] = MASK_COLOUR[0]
    rgb[invalid, 1] = MASK_COLOUR[1]
    rgb[invalid, 2] = MASK_COLOUR[2]

    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), mode="RGB").save(path)


def save_thresholded_visual_comparison(
    original_display,
    truth,
    python_masked,
    python_filled_unmasked,
    fpga_masked,
    error_python_masked,
    error_python_filled_unmasked,
    error_fpga_masked,
    path,
    threshold
):
    ensure_parent_dir(path)

    fig, axes = plt.subplots(2, 4, figsize=(24, 11))

    error_cmap = LinearSegmentedColormap.from_list(
        "red_white_green",
        [
            (0.0, "red"),
            (0.5, "white"),
            (1.0, "green"),
        ],
    )
    error_cmap.set_bad(color=MASK_COLOUR)

    gray_cmap = plt.cm.gray.copy()
    gray_cmap.set_bad(color=MASK_COLOUR)

    error_norm = TwoSlopeNorm(vmin=-1.0, vcenter=0.0, vmax=1.0)

    panels = [
        {
            "data": original_display,
            "title": "Original",
            "cmap": gray_cmap,
            "norm": None,
            "vmin": 0.0,
            "vmax": 1.0,
            "show_colourbar": False,
        },
        {
            "data": truth,
            "title": "Ground Truth",
            "cmap": gray_cmap,
            "norm": None,
            "vmin": 0.0,
            "vmax": 1.0,
            "show_colourbar": True,
        },
        {
            "data": python_masked,
            "title": f"Python Final Masked, C ≥ {threshold}",
            "cmap": gray_cmap,
            "norm": None,
            "vmin": 0.0,
            "vmax": 1.0,
            "show_colourbar": True,
        },
        {
            "data": python_filled_unmasked,
            "title": "Python Region Filled, Unmasked",
            "cmap": gray_cmap,
            "norm": None,
            "vmin": 0.0,
            "vmax": 1.0,
            "show_colourbar": True,
        },
        {
            "data": fpga_masked,
            "title": f"FPGA Masked, C ≥ {threshold}",
            "cmap": gray_cmap,
            "norm": None,
            "vmin": 0.0,
            "vmax": 1.0,
            "show_colourbar": True,
        },
        {
            "data": error_python_masked,
            "title": "Python Final Masked - Truth",
            "cmap": error_cmap,
            "norm": error_norm,
            "vmin": None,
            "vmax": None,
            "show_colourbar": True,
        },
        {
            "data": error_python_filled_unmasked,
            "title": "Python Filled Unmasked - Truth",
            "cmap": error_cmap,
            "norm": error_norm,
            "vmin": None,
            "vmax": None,
            "show_colourbar": True,
        },
        {
            "data": error_fpga_masked,
            "title": "FPGA Masked - Truth",
            "cmap": error_cmap,
            "norm": error_norm,
            "vmin": None,
            "vmax": None,
            "show_colourbar": True,
        },
    ]

    for ax, panel in zip(axes.flatten(), panels):
        if panel["norm"] is None:
            im = ax.imshow(
                np.ma.masked_invalid(panel["data"]),
                cmap=panel["cmap"],
                vmin=panel["vmin"],
                vmax=panel["vmax"],
                interpolation="nearest",
            )
        else:
            im = ax.imshow(
                np.ma.masked_invalid(panel["data"]),
                cmap=panel["cmap"],
                norm=panel["norm"],
                interpolation="nearest",
            )

        if panel["show_colourbar"]:
            fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

        ax.set_title(panel["title"])
        ax.set_xticks([])
        ax.set_yticks([])

        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_edgecolor("black")
            spine.set_linewidth(2)

    plt.subplots_adjust(
        left=0.04,
        right=0.98,
        top=0.92,
        bottom=0.06,
        wspace=0.35,
        hspace=0.25,
    )

    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------
# Path helpers
# ------------------------------------------------------------

def get_python_root_for_overall_folder(overall_folder):
    if "RGB" in overall_folder:
        return Path("Python_RGB")

    return Path("Python_Red")


def get_python_disparity_path(overall_folder, dataset, mode):
    python_root = get_python_root_for_overall_folder(overall_folder)
    python_mode = get_python_mode_folder(mode)

    return (
        python_root
        / python_mode
        / dataset
        / "disparity"
        / "Z_conf.imgb"
    )


def get_python_region_filled_disparity_path(overall_folder, dataset, mode):
    python_root = get_python_root_for_overall_folder(overall_folder)
    python_mode = get_python_mode_folder(mode)

    return (
        python_root
        / python_mode
        / dataset
        / "disparity"
        / "Z_conf_filled.imgb"
    )


def get_python_confidence_path(overall_folder, dataset, mode):
    python_root = get_python_root_for_overall_folder(overall_folder)
    python_mode = get_python_mode_folder(mode)

    return (
        python_root
        / python_mode
        / dataset
        / "confidence"
        / "C_avg.imgb"
    )


def get_original_png_path(overall_folder, dataset, mode):
    """
    Original image is NOT the truth disparity.
    Use the matching Python pipeline folder where possible.
    """
    python_root = get_python_root_for_overall_folder(overall_folder)
    python_mode = get_python_mode_folder(mode)

    candidate = (
        python_root
        / python_mode
        / dataset
        / "cross_raw_data_png"
        / "h_04.png"
    )

    if candidate.exists():
        return candidate

    return (
        Path("Python_Red")
        / python_mode
        / dataset
        / "cross_raw_data_png"
        / "h_04.png"
    )


def get_truth_npy_path(dataset, image_size):
    """
    Truth disparity is already:
      - central cropped to image_size x image_size
      - normalised to [0, 255]
      - stored under truth/<dataset>/
    """
    return (
        TRUTH_ROOT
        / dataset
        / f"disparity_{dataset}_px_center_{image_size}_norm.npy"
    )


def should_compare_to_truth(overall_folder):
    """
    Truth comparisons should only be performed for RGB outputs.
    Red and Red_Small are still compared FPGA-vs-Python, but not against truth.
    """
    return "RGB" in overall_folder


def get_python_mode_folder(mode):
    """
    Match the Python implementation folder to the FPGA mode.
    """
    if mode == "Bit_Manipulation":
        return "Bit_Manipulation"

    return "No_Libraries"


def write_error_metrics_block(f, title, mae, mse, rmse):
    f.write(f"{title}\n")
    f.write(f"MAE:  {mae:.6f}\n")
    f.write(f"MSE:  {mse:.6f}\n")
    f.write(f"RMSE: {rmse:.6f}\n")


# ------------------------------------------------------------
# Main comparison
# ------------------------------------------------------------

def compare_one(
    output_data_dir,
    truth_npy_path,
    original_png_path,
    python_imgb_path,
    python_region_filled_imgb_path,
    python_confidence_path,
    output_dir,
    image_size,
    compare_to_truth
):
    output_dir.mkdir(parents=True, exist_ok=True)

    weighted_disparity, confidence, written = reconstruct_fused_from_mif(
        output_data_dir,
        image_size
    )

    python_disparity = load_imgb_float(python_imgb_path)
    python_confidence = load_imgb_float(python_confidence_path)
    python_region_filled_disparity = load_imgb_float(python_region_filled_imgb_path)

    original = load_png_grayscale(original_png_path)

    python_crop = central_crop(python_disparity, image_size)
    original_crop = central_crop(original, image_size)
    python_confidence_crop = central_crop(python_confidence, image_size)
    python_region_filled_crop = central_crop(python_region_filled_disparity, image_size)

    weighted_disparity = remove_outer_edges(weighted_disparity, EDGE_CROP)
    confidence = remove_outer_edges(confidence, EDGE_CROP)
    original_crop = remove_outer_edges(original_crop, EDGE_CROP)
    python_crop = remove_outer_edges(python_crop, EDGE_CROP)
    python_confidence_crop = remove_outer_edges(python_confidence_crop, EDGE_CROP)
    python_region_filled_crop = remove_outer_edges(python_region_filled_crop, EDGE_CROP)

    weighted_disparity_norm = normalise_0_100_positive(weighted_disparity)
    python_norm = normalise_0_100_positive(python_crop)

    # Region-filled Python output is intentionally NOT masked.
    # It has already filled the low-confidence/invalid regions.
    python_region_filled_norm = normalise_0_100_positive(
        python_region_filled_crop
    )

    python_mask = np.isfinite(python_confidence_crop) & (
        python_confidence_crop >= CONFIDENCE_MASK_THRESHOLD
    )

    fpga_mask = np.isfinite(confidence) & (
        confidence >= CONFIDENCE_MASK_THRESHOLD
    )

    combined_mask = python_mask & fpga_mask

    python_masked_norm = normalise_0_100_positive_masked(
        python_crop,
        combined_mask
    )

    fpga_masked_norm = normalise_0_100_positive_masked(
        weighted_disparity,
        combined_mask
    )

    original_raw_u8 = np.clip(original_crop, 0, 255).astype(np.uint8)
    original_display = original_raw_u8.astype(np.float32) / 255.0

    # ------------------------------------------------------------
    # Always do FPGA vs Python comparisons for Red, Red_Small, and RGB
    # ------------------------------------------------------------

    error_fpga_vs_python, mae_fpga_vs_python, mse_fpga_vs_python, rmse_fpga_vs_python = (
        compute_error_metrics(
            weighted_disparity_norm,
            python_norm
        )
    )

    error_fpga_vs_python_filled, mae_fpga_vs_python_filled, mse_fpga_vs_python_filled, rmse_fpga_vs_python_filled = (
        compute_error_metrics(
            weighted_disparity_norm,
            python_region_filled_norm
        )
    )

    error_fpga_vs_python_masked, mae_fpga_vs_python_masked, mse_fpga_vs_python_masked, rmse_fpga_vs_python_masked, valid_fpga_vs_python_masked = (
        compute_error_metrics_masked(
            fpga_masked_norm,
            python_masked_norm,
            combined_mask
        )
    )

    # Python region-filled is not masked. For this diagnostic, compare the
    # masked FPGA output against the full region-filled Python output only at
    # the valid FPGA/Python confidence locations.
    error_fpga_vs_python_filled_masked, mae_fpga_vs_python_filled_masked, mse_fpga_vs_python_filled_masked, rmse_fpga_vs_python_filled_masked, valid_fpga_vs_python_filled_masked = (
        compute_error_metrics_masked(
            fpga_masked_norm,
            python_region_filled_norm,
            combined_mask
        )
    )

    print(output_data_dir)
    print("MIF pixels written:              ", written)
    print("Original image file:             ", original_png_path)
    print("Python disparity file:           ", python_imgb_path)
    print("Python disparity min/max:        ", np.nanmin(python_crop), np.nanmax(python_crop))
    print("Python filled min/max:           ", np.nanmin(python_region_filled_crop), np.nanmax(python_region_filled_crop))
    print("Weighted disparity min/max:      ", np.nanmin(weighted_disparity), np.nanmax(weighted_disparity))
    print("Confidence min/max:              ", np.nanmin(confidence), np.nanmax(confidence))
    print("Original min/max:                ", np.nanmin(original_crop), np.nanmax(original_crop))
    print("Final shape:                     ", weighted_disparity.shape)
    print("Truth comparison enabled:        ", compare_to_truth)
    print("-----")

    save_raw_grayscale_png(original_raw_u8, output_dir / "original.png")
    save_png(weighted_disparity_norm, output_dir / "fpga_weighted_disparity_normalised.png")
    save_png(python_norm, output_dir / "python_disparity_normalised.png")
    save_png(python_region_filled_norm, output_dir / "python_region_filled_disparity_normalised.png")

    save_signed_error_rgb(
        error_fpga_vs_python,
        output_dir / "difference_fpga_vs_python_disparity.png"
    )

    save_signed_error_rgb(
        error_fpga_vs_python_filled,
        output_dir / "difference_fpga_vs_python_region_filled_disparity.png"
    )

    save_fpga_python_visual_comparison(
        original_display=original_display,
        python_estimate=python_norm,
        python_filled_estimate=python_region_filled_norm,
        fpga_estimate=weighted_disparity_norm,
        error_fpga_vs_python=error_fpga_vs_python,
        error_fpga_vs_python_filled=error_fpga_vs_python_filled,
        path=output_dir / "visual_comparison_fpga_vs_python.png"
    )

    threshold_dir = output_dir / f"threshold_{str(CONFIDENCE_MASK_THRESHOLD).replace('.', 'p')}"
    threshold_dir.mkdir(parents=True, exist_ok=True)

    save_masked_gray_png(
        python_masked_norm,
        threshold_dir / "python_masked_disparity_normalised.png"
    )

    # Region-filled Python is saved unmasked even inside the threshold folder,
    # so you can visually see the filled result next to the masked results.
    save_png(
        python_region_filled_norm,
        threshold_dir / "python_region_filled_unmasked_disparity_normalised.png"
    )

    save_masked_gray_png(
        fpga_masked_norm,
        threshold_dir / "fpga_masked_weighted_disparity_normalised.png"
    )

    save_masked_signed_error_rgb(
        error_fpga_vs_python_masked,
        threshold_dir / "difference_fpga_vs_python_masked_disparity.png"
    )

    save_masked_signed_error_rgb(
        error_fpga_vs_python_filled_masked,
        threshold_dir / "difference_fpga_vs_python_region_filled_unmasked_disparity.png"
    )

    # ------------------------------------------------------------
    # Truth comparison only for RGB
    # ------------------------------------------------------------

    if compare_to_truth:
        if truth_npy_path is None:
            raise ValueError("compare_to_truth=True but truth_npy_path is None")

        truth_norm = load_truth_normalised_npy(truth_npy_path)

        if truth_norm.shape != (image_size, image_size):
            raise ValueError(
                f"Truth shape mismatch for {truth_npy_path}: "
                f"got {truth_norm.shape}, expected {(image_size, image_size)}"
            )

        truth_norm = remove_outer_edges(truth_norm, EDGE_CROP)

        error_fpga, mae_fpga, mse_fpga, rmse_fpga = compute_error_metrics(
            weighted_disparity_norm,
            truth_norm
        )

        error_python, mae_python, mse_python, rmse_python = compute_error_metrics(
            python_norm,
            truth_norm
        )

        error_python_region_filled, mae_python_region_filled, mse_python_region_filled, rmse_python_region_filled = compute_error_metrics(
            python_region_filled_norm,
            truth_norm
        )

        error_python_masked, mae_python_masked, mse_python_masked, rmse_python_masked, valid_python_masked = (
            compute_error_metrics_masked(
                python_masked_norm,
                truth_norm,
                python_mask
            )
        )

        # Region-filled Python truth comparison is intentionally unmasked.
        error_python_region_filled_unmasked, mae_python_region_filled_unmasked, mse_python_region_filled_unmasked, rmse_python_region_filled_unmasked = (
            compute_error_metrics(
                python_region_filled_norm,
                truth_norm
            )
        )

        error_fpga_masked, mae_fpga_masked, mse_fpga_masked, rmse_fpga_masked, valid_fpga_masked = (
            compute_error_metrics_masked(
                fpga_masked_norm,
                truth_norm,
                fpga_mask
            )
        )

        fpga_bit_summary = summarise_leading_bit_correctness(
            truth_norm,
            weighted_disparity_norm
        )

        python_bit_summary = summarise_leading_bit_correctness(
            truth_norm,
            python_norm
        )

        python_region_filled_bit_summary = summarise_leading_bit_correctness(
            truth_norm,
            python_region_filled_norm
        )

        save_png(truth_norm, output_dir / "truth_normalised.png")

        save_signed_error_rgb(
            error_fpga,
            output_dir / "difference_truth_vs_fpga_weighted_disparity.png"
        )

        save_signed_error_rgb(
            error_python,
            output_dir / "difference_truth_vs_python_disparity.png"
        )

        save_signed_error_rgb(
            error_python_region_filled,
            output_dir / "difference_truth_vs_python_region_filled_disparity.png"
        )

        save_visual_comparison(
            original_display,
            truth_norm,
            python_norm,
            python_region_filled_norm,
            weighted_disparity_norm,
            error_python,
            error_python_region_filled,
            error_fpga,
            output_dir / "visual_comparison_truth.png"
        )

        save_masked_signed_error_rgb(
            error_python_masked,
            threshold_dir / "difference_truth_vs_python_masked_disparity.png"
        )

        save_signed_error_rgb(
            error_python_region_filled_unmasked,
            threshold_dir / "difference_truth_vs_python_region_filled_unmasked_disparity.png"
        )

        save_masked_signed_error_rgb(
            error_fpga_masked,
            threshold_dir / "difference_truth_vs_fpga_masked_weighted_disparity.png"
        )

        save_thresholded_visual_comparison(
            original_display=original_display,
            truth=truth_norm,
            python_masked=python_masked_norm,
            python_filled_unmasked=python_region_filled_norm,
            fpga_masked=fpga_masked_norm,
            error_python_masked=error_python_masked,
            error_python_filled_unmasked=error_python_region_filled_unmasked,
            error_fpga_masked=error_fpga_masked,
            path=threshold_dir / "visual_comparison_thresholded_truth.png",
            threshold=CONFIDENCE_MASK_THRESHOLD,
        )

    with open(output_dir / "metrics.txt", "w") as f:
        f.write(f"Output data dir: {output_data_dir}\n")
        f.write(f"Original file:   {original_png_path}\n")
        f.write(f"Python file:     {python_imgb_path}\n")
        f.write(f"Image size:      {image_size}x{image_size}\n")
        f.write(f"Edge removed:    {EDGE_CROP} pixels from each side\n")
        f.write(f"Final size:      {weighted_disparity.shape[0]}x{weighted_disparity.shape[1]}\n")
        f.write(f"MIF pixels written: {written}\n")
        f.write(f"Truth comparison enabled: {compare_to_truth}\n\n")

        f.write("Display scales\n")
        f.write(f"Original colourbar: 0 to {ORIGINAL_MAX}\n")
        f.write("Truth colourbar: 0 to 1\n")
        f.write("Python disparity colourbar: 0 to 1\n")
        f.write("Python region-filled disparity colourbar: 0 to 1\n")
        f.write("FPGA weighted disparity colourbar: 0 to 1\n")
        f.write(f"Difference colourbar: -{DIFF_MAX} to {DIFF_MAX}\n\n")

        f.write("Normalisation\n")
        f.write("All disparity/truth comparisons and metrics use [0, 1] normalised values.\n")
        f.write("Only the original input image is displayed with a 0 to 255 pixel-value colourbar.\n")
        f.write("Estimate normalisation: 0-100 full range over positive finite disparity only; disparity <= 0 mapped to 0 for comparison.\n\n")

        f.write("FPGA vs Python comparison\n")
        f.write("Difference = FPGA - Python\n\n")

        write_error_metrics_block(
            f,
            "FPGA vs Python Final Disparity",
            mae_fpga_vs_python,
            mse_fpga_vs_python,
            rmse_fpga_vs_python
        )

        f.write("\n")

        write_error_metrics_block(
            f,
            "FPGA vs Python Region-Filled Disparity",
            mae_fpga_vs_python_filled,
            mse_fpga_vs_python_filled,
            rmse_fpga_vs_python_filled
        )

        f.write("\nConfidence-thresholded FPGA vs Python comparison\n")
        f.write(f"Confidence threshold: {CONFIDENCE_MASK_THRESHOLD}\n")
        f.write("Masked comparison uses combined Python and FPGA confidence masks for Python final and FPGA.\n")
        f.write("Python region-filled output is not masked; metrics below compare it at the combined valid mask locations only for the thresholded diagnostic.\n\n")

        f.write("FPGA vs Python Final Masked Disparity\n")
        f.write(f"Valid masked pixels: {valid_fpga_vs_python_masked} / {weighted_disparity_norm.size}\n")
        f.write(f"MAE:  {mae_fpga_vs_python_masked:.6f}\n")
        f.write(f"MSE:  {mse_fpga_vs_python_masked:.6f}\n")
        f.write(f"RMSE: {rmse_fpga_vs_python_masked:.6f}\n\n")

        f.write("FPGA vs Python Region-Filled Unmasked Disparity at Valid Mask Locations\n")
        f.write(f"Valid comparison pixels: {valid_fpga_vs_python_filled_masked} / {weighted_disparity_norm.size}\n")
        f.write(f"MAE:  {mae_fpga_vs_python_filled_masked:.6f}\n")
        f.write(f"MSE:  {mse_fpga_vs_python_filled_masked:.6f}\n")
        f.write(f"RMSE: {rmse_fpga_vs_python_filled_masked:.6f}\n\n")

        if compare_to_truth:
            f.write("\n\nRGB truth comparison\n")
            f.write(f"Truth file: {truth_npy_path}\n")
            f.write("Difference = estimate - truth\n")
            f.write("Red = underestimation\n")
            f.write("White = zero difference\n")
            f.write("Green = overestimation\n\n")

            f.write("Confidence-thresholded RGB truth comparison\n")
            f.write(f"Confidence threshold: {CONFIDENCE_MASK_THRESHOLD}\n")
            f.write("Invalid pixels are excluded from the Python final and FPGA masked metrics and shown in pink in the visualisations.\n")
            f.write("Python region-filled output is not masked because it is already the filled result.\n\n")

            f.write("Truth vs Python Masked Disparity\n")
            f.write(f"Valid masked pixels: {valid_python_masked} / {truth_norm.size}\n")
            f.write(f"MAE:  {mae_python_masked:.6f}\n")
            f.write(f"MSE:  {mse_python_masked:.6f}\n")
            f.write(f"RMSE: {rmse_python_masked:.6f}\n\n")

            f.write("Truth vs Python Region-Filled Unmasked Disparity\n")
            f.write(f"Valid pixels: {truth_norm.size} / {truth_norm.size}\n")
            f.write(f"MAE:  {mae_python_region_filled_unmasked:.6f}\n")
            f.write(f"MSE:  {mse_python_region_filled_unmasked:.6f}\n")
            f.write(f"RMSE: {rmse_python_region_filled_unmasked:.6f}\n\n")

            f.write("Truth vs FPGA Masked Weighted Disparity\n")
            f.write(f"Valid masked pixels: {valid_fpga_masked} / {truth_norm.size}\n")
            f.write(f"MAE:  {mae_fpga_masked:.6f}\n")
            f.write(f"MSE:  {mse_fpga_masked:.6f}\n")
            f.write(f"RMSE: {rmse_fpga_masked:.6f}\n\n")

            write_metric_block(
                f,
                "Truth vs Python Disparity",
                mae_python,
                mse_python,
                rmse_python,
                python_bit_summary
            )

            f.write("\n")

            write_metric_block(
                f,
                "Truth vs Python Region-Filled Disparity",
                mae_python_region_filled,
                mse_python_region_filled,
                rmse_python_region_filled,
                python_region_filled_bit_summary
            )

            f.write("\n")

            write_metric_block(
                f,
                "Truth vs FPGA Weighted Disparity",
                mae_fpga,
                mse_fpga,
                rmse_fpga,
                fpga_bit_summary
            )

    print(f"Saved comparison to: {output_dir}")


def main():
    for dataset in DATASETS:
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

                compare_to_truth = should_compare_to_truth(overall_folder)

                truth_path = None

                if compare_to_truth:
                    truth_path = get_truth_npy_path(dataset, image_size)

                    if not truth_path.exists():
                        print(f"Skipping RGB truth comparison for {dataset}: missing truth file {truth_path}")
                        continue

                python_imgb_path = get_python_disparity_path(
                    overall_folder,
                    dataset,
                    mode
                )

                if not python_imgb_path.exists():
                    print(f"Skipping missing Python disparity file: {python_imgb_path}")
                    continue

                python_region_filled_imgb_path = get_python_region_filled_disparity_path(
                    overall_folder,
                    dataset,
                    mode
                )

                if not python_region_filled_imgb_path.exists():
                    print(f"Skipping missing Python region-filled disparity file: {python_region_filled_imgb_path}")
                    continue

                python_confidence_path = get_python_confidence_path(
                    overall_folder,
                    dataset,
                    mode
                )

                if not python_confidence_path.exists():
                    print(f"Skipping missing Python confidence file: {python_confidence_path}")
                    continue

                original_png_path = get_original_png_path(
                    overall_folder,
                    dataset,
                    mode
                )

                if not original_png_path.exists():
                    print(f"Skipping {dataset}: missing original image {original_png_path}")
                    continue

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
                    python_imgb_path=python_imgb_path,
                    python_region_filled_imgb_path=python_region_filled_imgb_path,
                    python_confidence_path=python_confidence_path,
                    output_dir=output_dir,
                    image_size=image_size,
                    compare_to_truth=compare_to_truth,
                )


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Compare Python outputs against FPGA outputs for confidence and disparity.

This script performs three comparison types by default:

1) normalised_png
   Python_Red/No_Libraries/<dataset>/confidence_normalised_png_center_128x128_png/C_avg.png
   vs
   SystemVerilog_HDL_Red/Standard/tb/<dataset>/output_data/fused_confidence_normalised.png

   Python_Red/No_Libraries/<dataset>/disparity_normalised_png_center_128x128_png/Z_conf_nonfilled_blurred.png
   vs
   SystemVerilog_HDL_Red/Standard/tb/<dataset>/output_data/fused_weighted_disparity_normalised.png

2) linear_png
   Python_Red/No_Libraries/<dataset>/confidence_png_center_128x128_png/C_avg.png
   vs
   SystemVerilog_HDL_Red/Standard/tb/<dataset>/output_data/fused_confidence.png

   Python_Red/No_Libraries/<dataset>/disparity_png_center_128x128_png/Z_conf_nonfilled_blurred.png
   vs
   SystemVerilog_HDL_Red/Standard/tb/<dataset>/output_data/fused_weighted_disparity.png

3) raw_numeric
   Python .imgb values are decoded directly from:
      confidence/C_avg.imgb
      disparity/Z_conf_nonfilled_blurred.imgb

   FPGA .mif streams are reconstructed directly from:
      SIM_PIXEL_VALID_OUT.mif
      SIM_ROW_IDX_OUT.mif
      SIM_COLUMN_IDX_OUT.mif
      SIM_CONFIDENCE_PIXEL_BIT_DATA.mif
      SIM_WEIGHTED_DISPARITY_PIXEL_BIT_DATA.mif

The raw_numeric comparison is useful when display PNGs hide important numerical
information, for example when negative disparity is clamped to black or large
positive disparity is also visualised as dark.

For raw_numeric disparity only, the comparison applies the same display-domain
preprocessing convention used by bin_to_png.py and the FPGA MIF-to-PNG converter:
    Z_compare = Z_stored - 1.0
This does not change the stored Python IMGB or FPGA MIF data. It only makes raw
numeric sign/range statistics consistent with the generated disparity PNGs.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# -----------------------------------------------------------------------------
# Default project layout
# -----------------------------------------------------------------------------

DEFAULT_DATASETS = ["head", "dino", "town"]
DEFAULT_KINDS = ["confidence", "disparity"]
DEFAULT_COMPARE_TYPES = ["normalised_png", "linear_png", "raw_numeric"]

PYTHON_PNG_REL_BY_TYPE_KIND = {
    "normalised_png": {
        "confidence": Path("confidence_normalised_png_center_128x128_png") / "C_avg.png",
        "disparity": Path("disparity_normalised_png_center_128x128_png") / "Z_conf_nonfilled_blurred.png",
    },
    "linear_png": {
        "confidence": Path("confidence_png_center_128x128_png") / "C_avg.png",
        "disparity": Path("disparity_png_center_128x128_png") / "Z_conf_nonfilled_blurred.png",
    },
}

FPGA_PNG_NAME_BY_TYPE_KIND = {
    "normalised_png": {
        "confidence": "fused_confidence_normalised.png",
        "disparity": "fused_weighted_disparity_normalised.png",
    },
    "linear_png": {
        "confidence": "fused_confidence.png",
        "disparity": "fused_weighted_disparity.png",
    },
}

PYTHON_IMGB_REL_BY_KIND = {
    "confidence": Path("confidence") / "C_avg.imgb",
    "disparity": Path("disparity") / "Z_conf_nonfilled_blurred.imgb",
}

FPGA_VALID_MIF = "SIM_PIXEL_VALID_OUT.mif"
FPGA_ROW_MIF = "SIM_ROW_IDX_OUT.mif"
FPGA_COL_MIF = "SIM_COLUMN_IDX_OUT.mif"
FPGA_CONF_MIF = "SIM_CONFIDENCE_PIXEL_BIT_DATA.mif"
FPGA_DISP_MIF = "SIM_WEIGHTED_DISPARITY_PIXEL_BIT_DATA.mif"

IMAGE_DIM = 128

# Python IMGB biased Q12.12 settings.
BIAS_INT = 8388608
Q_SCALE = 4096

# FPGA fixed-point formats.
CONF_WIDTH_BITS = 10
CONF_FRAC_BITS = 2
DISP_WIDTH_BITS = 16
DISP_FRAC_BITS = 8

# Display/analysis offset used only for raw_numeric disparity comparison.
# The stored algorithm output is D = 1 + ratio. For visual interpretation we
# compare D - 1, matching the updated Python and FPGA PNG converters.
DISPARITY_RAW_COMPARE_OFFSET = 1.0


# -----------------------------------------------------------------------------
# Data containers
# -----------------------------------------------------------------------------

@dataclass
class Metrics:
    total_pixels: int
    mse: float
    mean_abs_error: float
    median_abs_error: float
    median_error: float
    min_error: float
    max_error: float
    exact_match_pixels: int
    exact_match_fraction: float
    pearson_corr: float | None = None
    spearman_corr: float | None = None
    python_min: float | None = None
    python_max: float | None = None
    fpga_min: float | None = None
    fpga_max: float | None = None
    fpga_minus_python_mean: float | None = None
    fpga_minus_python_median: float | None = None
    sign_match_fraction: float | None = None
    python_negative_pixels: int | None = None
    python_zero_pixels: int | None = None
    python_positive_pixels: int | None = None
    fpga_negative_pixels: int | None = None
    fpga_zero_pixels: int | None = None
    fpga_positive_pixels: int | None = None
    mean_bit_correctness: float | None = None
    median_bit_correctness: float | None = None
    best_bit_correctness: int | None = None
    worst_bit_correctness: int | None = None


@dataclass
class ComparisonResult:
    dataset: str
    kind: str
    compare_type: str
    python_path: Path
    fpga_path: Path
    plot_path: Path
    python_shape: tuple[int, int]
    fpga_shape: tuple[int, int]
    compared_shape: tuple[int, int]
    metrics: Metrics


# -----------------------------------------------------------------------------
# Common file/image helpers
# -----------------------------------------------------------------------------

def require_file(path: Path) -> None:
    """
    Raise FileNotFoundError if a required file is missing.

    Time complexity:
    - O(1), excluding filesystem lookup cost.
    """

    if not path.is_file():
        raise FileNotFoundError(f"Missing required file: {path}")


def load_grayscale_u8(path: Path) -> np.ndarray:
    """
    Load an image as an 8-bit grayscale NumPy array.

    Time complexity:
    - O(H * W), where H and W are the image dimensions.
    """

    require_file(path)
    img = Image.open(path).convert("L")
    arr = np.asarray(img, dtype=np.uint8)

    if arr.ndim != 2:
        raise ValueError(f"Expected a 2D grayscale image at {path}, got shape {arr.shape}")

    return arr


def crop_edges(arr: np.ndarray, crop_edge: int) -> np.ndarray:
    """
    Remove crop_edge pixels from all four sides.

    Time complexity:
    - O(1), because NumPy slicing creates a view.
    """

    if crop_edge <= 0:
        return arr

    if arr.shape[0] <= 2 * crop_edge or arr.shape[1] <= 2 * crop_edge:
        raise ValueError(f"Cannot crop {crop_edge} pixels from image with shape {arr.shape}")

    return arr[crop_edge:-crop_edge, crop_edge:-crop_edge]


def center_crop_to_size(arr: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """
    Centre-crop one array to the requested size.

    Time complexity:
    - O(1), because NumPy slicing creates a view.
    """

    if target_h <= 0 or target_w <= 0:
        raise ValueError("target_h and target_w must be positive")

    if arr.shape[0] < target_h or arr.shape[1] < target_w:
        raise ValueError(f"Cannot crop array of shape {arr.shape} to {target_h}x{target_w}")

    start_y = (arr.shape[0] - target_h) // 2
    start_x = (arr.shape[1] - target_w) // 2
    return arr[start_y:start_y + target_h, start_x:start_x + target_w]


def center_crop_to_common(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Centre-crop two arrays to their common minimum height and width.

    Time complexity:
    - O(1), because NumPy slicing creates views.
    """

    target_h = min(a.shape[0], b.shape[0])
    target_w = min(a.shape[1], b.shape[1])

    return center_crop_to_size(a, target_h, target_w), center_crop_to_size(b, target_h, target_w)


# -----------------------------------------------------------------------------
# MIF parsing helpers
# -----------------------------------------------------------------------------

def _read_depth_from_mif_header(path: Path) -> int:
    """
    Read DEPTH=<N>; from a MIF file header.

    Time complexity:
    - O(L), where L is the number of lines until DEPTH is found.
    """

    with path.open("r", encoding="utf-8") as file_obj:
        for line in file_obj:
            stripped = line.strip()
            if stripped.startswith("DEPTH=") and stripped.endswith(";"):
                return int(stripped[len("DEPTH="):-1])

    raise ValueError(f"Could not parse DEPTH from MIF header: {path}")


def _parse_content_bits_lines(path: Path) -> dict[int, str]:
    """
    Parse CONTENT BEGIN ... END; lines in a MIF file.

    Time complexity:
    - O(L), where L is the total number of lines in the file.
    """

    addr_to_bits: dict[int, str] = {}
    in_content = False

    with path.open("r", encoding="utf-8") as file_obj:
        for raw_line in file_obj:
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

            addr_to_bits[addr] = right.strip().replace(" ", "")

    return addr_to_bits


def load_mif_bits(path: Path, width_bits: int) -> np.ndarray:
    """
    Load a MIF as unsigned integers.

    Time complexity:
    - O(D + L), where D is the MIF depth and L is the number of lines.
    """

    require_file(path)
    depth = _read_depth_from_mif_header(path)
    addr_to_bits = _parse_content_bits_lines(path)

    out = np.zeros(depth, dtype=np.int64)

    for addr, bits in addr_to_bits.items():
        if not (0 <= addr < depth):
            continue

        if len(bits) > width_bits:
            bits_use = bits[-width_bits:]
        elif len(bits) < width_bits:
            bits_use = ("0" * (width_bits - len(bits))) + bits
        else:
            bits_use = bits

        try:
            out[addr] = int(bits_use, 2)
        except ValueError:
            out[addr] = 0

    return out


def twos_complement_to_int(values: np.ndarray, width_bits: int) -> np.ndarray:
    """
    Convert width-bit two's-complement words to signed integers.

    Time complexity:
    - O(N), where N is the number of values.
    """

    values_i64 = values.astype(np.int64, copy=False)
    sign_bit = 1 << (width_bits - 1)
    full_mod = 1 << width_bits
    return np.where((values_i64 & sign_bit) != 0, values_i64 - full_mod, values_i64)


def load_mif_bits_signed(path: Path, width_bits: int) -> np.ndarray:
    """
    Load a MIF as signed two's-complement integers.

    Time complexity:
    - O(D + L), dominated by reading the MIF content.
    """

    return twos_complement_to_int(load_mif_bits(path, width_bits), width_bits)


# -----------------------------------------------------------------------------
# IMGB parsing helpers
# -----------------------------------------------------------------------------

def _u32_le(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off:off + 4], "little", signed=False)


def imgb_parse(buf: bytes) -> tuple[int, int, int, int, bytes]:
    """
    Parse the simple IMGB header used by the Python pipeline.

    Time complexity:
    - O(1) for header parsing.
    """

    width = _u32_le(buf, 4)
    height = _u32_le(buf, 8)
    channels = buf[12]
    dtype_code = buf[13]
    payload = buf[16:]

    return int(width), int(height), int(channels), int(dtype_code), payload


def _decode_u24_q12_12(payload: bytes, n_samples: int) -> np.ndarray:
    """
    Decode biased unsigned 24-bit Q12.12 values into real float values.

    Time complexity:
    - O(N), where N is the number of samples.
    """

    b = np.frombuffer(payload, dtype=np.uint8).reshape((-1, 3))

    u24 = (
        b[:, 0].astype(np.uint32)
        | (b[:, 1].astype(np.uint32) << np.uint32(8))
        | (b[:, 2].astype(np.uint32) << np.uint32(16))
    )

    out = (u24.astype(np.int32) - np.int32(BIAS_INT)).astype(np.float32) / np.float32(Q_SCALE)

    if out.size != n_samples:
        raise ValueError(f"Decoded sample count mismatch: expected {n_samples}, got {out.size}")

    return out


def read_imgb_real(path: Path, channel_mode: str = "first") -> np.ndarray:
    """
    Read an IMGB as a 2D float image.

    Supported dtype_code values:
    - 1: uint8
    - 4: biased unsigned 24-bit Q12.12

    Time complexity:
    - O(H * W * C), where C is the number of channels.
    """

    require_file(path)

    with path.open("rb") as file_obj:
        blob = file_obj.read()

    width, height, channels, dtype_code, payload = imgb_parse(blob)

    if dtype_code == 1:
        arr = np.frombuffer(payload, dtype=np.uint8).astype(np.float32)
    elif dtype_code == 4:
        arr = _decode_u24_q12_12(payload, width * height * channels)
    else:
        raise ValueError(f"Unsupported dtype_code={dtype_code} in {path}")

    if channels == 1:
        return arr.reshape((height, width)).astype(np.float64, copy=False)

    arr = arr.reshape((height, width, channels))

    if channel_mode == "first":
        return arr[:, :, 0].astype(np.float64, copy=False)

    if channel_mode == "mean":
        return np.mean(arr.astype(np.float64), axis=2)

    raise ValueError(f"Unsupported channel_mode={channel_mode!r}")


# -----------------------------------------------------------------------------
# Raw FPGA reconstruction
# -----------------------------------------------------------------------------

def resolve_dataset_fpga_dir(base_dir: Path, fpga_root: Path, dataset: str) -> Path:
    """
    Resolve FPGA output directory for a dataset.

    Search order:
    1. <fpga_root>/<dataset>/output_data
    2. <fpga_root>/<dataset>
    3. <fpga_root>/output_data
    4. <fpga_root>

    Time complexity:
    - O(1), only a few filesystem checks.
    """

    candidates = [
        base_dir / fpga_root / dataset / "output_data",
        base_dir / fpga_root / dataset,
        base_dir / fpga_root / "output_data",
        base_dir / fpga_root,
    ]

    for candidate in candidates:
        if (candidate / FPGA_VALID_MIF).is_file():
            return candidate

    raise FileNotFoundError(
        f"Could not find FPGA MIF output directory for dataset {dataset!r}. Checked:\n"
        + "\n".join(str(c) for c in candidates)
    )


def reconstruct_fpga_raw_outputs(fpga_dir: Path, image_dim: int = IMAGE_DIM) -> tuple[np.ndarray, np.ndarray]:
    """
    Reconstruct FPGA confidence and weighted disparity arrays from MIF streams.

    Returns:
    - confidence_real: unsigned Q8.2 converted to real values
    - disparity_real: signed Q8.8 converted to real values

    Time complexity:
    - O(D + image_dim^2), where D is the MIF stream depth.
    """

    valid = load_mif_bits(fpga_dir / FPGA_VALID_MIF, 1)
    row_idx = load_mif_bits(fpga_dir / FPGA_ROW_MIF, 7)
    col_idx = load_mif_bits(fpga_dir / FPGA_COL_MIF, 7)
    conf_raw_stream = load_mif_bits(fpga_dir / FPGA_CONF_MIF, CONF_WIDTH_BITS)
    disp_raw_stream = load_mif_bits_signed(fpga_dir / FPGA_DISP_MIF, DISP_WIDTH_BITS)

    depth = len(valid)

    if not (
        len(row_idx) == depth
        and len(col_idx) == depth
        and len(conf_raw_stream) == depth
        and len(disp_raw_stream) == depth
    ):
        raise ValueError(f"MIF DEPTH mismatch in FPGA output directory: {fpga_dir}")

    conf = np.full((image_dim, image_dim), np.nan, dtype=np.float64)
    disp = np.full((image_dim, image_dim), np.nan, dtype=np.float64)

    for stream_idx in range(depth):
        if int(valid[stream_idx]) == 0:
            continue

        y_coord = int(row_idx[stream_idx])
        x_coord = int(col_idx[stream_idx])

        if 0 <= y_coord < image_dim and 0 <= x_coord < image_dim:
            conf[y_coord, x_coord] = float(int(conf_raw_stream[stream_idx])) / float(1 << CONF_FRAC_BITS)
            disp[y_coord, x_coord] = float(int(disp_raw_stream[stream_idx])) / float(1 << DISP_FRAC_BITS)

    return conf, disp


# -----------------------------------------------------------------------------
# Metrics
# -----------------------------------------------------------------------------

def popcount8(x: np.ndarray) -> np.ndarray:
    """
    Vectorised popcount for an array of uint8 values.

    Time complexity:
    - O(N), where N is the number of pixels.
    """

    return np.unpackbits(x[..., None], axis=-1).sum(axis=-1).astype(np.uint8)


def compute_png_metrics(py_img: np.ndarray, fpga_img: np.ndarray) -> tuple[Metrics, np.ndarray]:
    """
    Compute 8-bit PNG-domain metrics.

    Error convention:
    - error = FPGA - Python

    Time complexity:
    - O(N), where N is the number of compared pixels.
    """

    py_i16 = py_img.astype(np.int16)
    fpga_i16 = fpga_img.astype(np.int16)
    error = fpga_i16 - py_i16

    xor_vals = np.bitwise_xor(py_img, fpga_img)
    differing_bits = popcount8(xor_vals).astype(np.int16)
    bit_correctness = 8 - differing_bits

    exact_match_pixels = int(np.count_nonzero(xor_vals == 0))
    total_pixels = int(py_img.size)

    metrics = Metrics(
        total_pixels=total_pixels,
        mse=float(np.mean(error.astype(np.float64) ** 2)),
        mean_abs_error=float(np.mean(np.abs(error.astype(np.float64)))),
        median_abs_error=float(np.median(np.abs(error.astype(np.float64)))),
        median_error=float(np.median(error.astype(np.float64))),
        min_error=float(error.min()),
        max_error=float(error.max()),
        exact_match_pixels=exact_match_pixels,
        exact_match_fraction=float(exact_match_pixels / total_pixels) if total_pixels > 0 else 0.0,
        mean_bit_correctness=float(np.mean(bit_correctness.astype(np.float64))),
        median_bit_correctness=float(np.median(bit_correctness.astype(np.float64))),
        best_bit_correctness=int(bit_correctness.max()),
        worst_bit_correctness=int(bit_correctness.min()),
    )

    return metrics, error.astype(np.float64)


def _rankdata_average(values: np.ndarray) -> np.ndarray:
    """
    Rank values using average ranks for ties. This avoids scipy dependency.

    Time complexity:
    - O(N log N), dominated by sorting.
    """

    x = np.asarray(values, dtype=np.float64)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(x.size, dtype=np.float64)
    sorted_x = x[order]

    start = 0
    while start < x.size:
        end = start + 1
        while end < x.size and sorted_x[end] == sorted_x[start]:
            end += 1

        avg_rank = 0.5 * (start + end - 1) + 1.0
        ranks[order[start:end]] = avg_rank
        start = end

    return ranks


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float | None:
    """
    Compute Pearson correlation, returning None for degenerate inputs.

    Time complexity:
    - O(N).
    """

    if a.size < 2 or b.size < 2:
        return None

    if float(np.std(a)) == 0.0 or float(np.std(b)) == 0.0:
        return None

    return float(np.corrcoef(a, b)[0, 1])


def compute_raw_metrics(py_real: np.ndarray, fpga_real: np.ndarray) -> tuple[Metrics, np.ndarray]:
    """
    Compute real-valued raw numeric metrics.

    Error convention:
    - error = FPGA - Python

    Time complexity:
    - O(N log N), dominated by Spearman rank sorting.
    """

    valid = np.isfinite(py_real) & np.isfinite(fpga_real)

    if not valid.any():
        raise ValueError("No valid overlapping raw numeric pixels to compare")

    py = py_real[valid].astype(np.float64)
    fpga = fpga_real[valid].astype(np.float64)
    error_values = fpga - py

    full_error = np.full(py_real.shape, np.nan, dtype=np.float64)
    full_error[valid] = error_values

    pearson = _safe_corr(py, fpga)
    spearman = None
    if py.size >= 2:
        py_rank = _rankdata_average(py)
        fpga_rank = _rankdata_average(fpga)
        spearman = _safe_corr(py_rank, fpga_rank)

    sign_match = np.sign(py) == np.sign(fpga)
    exact_match = np.isclose(py, fpga, atol=0.0, rtol=0.0)

    metrics = Metrics(
        total_pixels=int(py.size),
        mse=float(np.mean(error_values ** 2)),
        mean_abs_error=float(np.mean(np.abs(error_values))),
        median_abs_error=float(np.median(np.abs(error_values))),
        median_error=float(np.median(error_values)),
        min_error=float(np.min(error_values)),
        max_error=float(np.max(error_values)),
        exact_match_pixels=int(np.count_nonzero(exact_match)),
        exact_match_fraction=float(np.count_nonzero(exact_match) / py.size),
        pearson_corr=pearson,
        spearman_corr=spearman,
        python_min=float(np.min(py)),
        python_max=float(np.max(py)),
        fpga_min=float(np.min(fpga)),
        fpga_max=float(np.max(fpga)),
        fpga_minus_python_mean=float(np.mean(error_values)),
        fpga_minus_python_median=float(np.median(error_values)),
        sign_match_fraction=float(np.count_nonzero(sign_match) / py.size),
        python_negative_pixels=int(np.count_nonzero(py < 0.0)),
        python_zero_pixels=int(np.count_nonzero(py == 0.0)),
        python_positive_pixels=int(np.count_nonzero(py > 0.0)),
        fpga_negative_pixels=int(np.count_nonzero(fpga < 0.0)),
        fpga_zero_pixels=int(np.count_nonzero(fpga == 0.0)),
        fpga_positive_pixels=int(np.count_nonzero(fpga > 0.0)),
    )

    return metrics, full_error


# -----------------------------------------------------------------------------
# Plotting
# -----------------------------------------------------------------------------

def _finite_limits(arrays: Iterable[np.ndarray]) -> tuple[float, float]:
    """
    Compute min/max limits over finite values in multiple arrays.

    Time complexity:
    - O(N), where N is the total number of elements.
    """

    values = []
    for arr in arrays:
        finite = np.isfinite(arr)
        if finite.any():
            values.append(arr[finite].astype(np.float64))

    if not values:
        return 0.0, 1.0

    merged = np.concatenate(values)
    vmin = float(np.min(merged))
    vmax = float(np.max(merged))

    if vmax <= vmin:
        vmax = vmin + 1.0

    return vmin, vmax


def make_comparison_plot(
    py_img: np.ndarray,
    fpga_img: np.ndarray,
    error: np.ndarray,
    *,
    title: str,
    py_label: str,
    fpga_label: str,
    value_label: str,
    out_path: Path,
    fixed_u8_scale: bool,
) -> None:
    """
    Save a 1x3 comparison plot: Python, FPGA, and FPGA-Python difference.

    Time complexity:
    - O(H * W), dominated by rendering.
    """

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if fixed_u8_scale:
        data_vmin = 0.0
        data_vmax = 255.0
    else:
        data_vmin, data_vmax = _finite_limits([py_img, fpga_img])

    finite_error = error[np.isfinite(error)]
    if finite_error.size == 0:
        max_abs_err = 1.0
    else:
        max_abs_err = float(np.max(np.abs(finite_error)))
        if max_abs_err == 0.0:
            max_abs_err = 1.0

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    fig.suptitle(title, fontsize=12)

    im0 = axes[0].imshow(py_img, cmap="gray", vmin=data_vmin, vmax=data_vmax)
    axes[0].set_title(py_label)
    axes[0].set_xlabel("Column")
    axes[0].set_ylabel("Row")
    cbar0 = fig.colorbar(im0, ax=axes[0], fraction=0.046, pad=0.04)
    cbar0.set_label(value_label)

    im1 = axes[1].imshow(fpga_img, cmap="gray", vmin=data_vmin, vmax=data_vmax)
    axes[1].set_title(fpga_label)
    axes[1].set_xlabel("Column")
    axes[1].set_ylabel("Row")
    cbar1 = fig.colorbar(im1, ax=axes[1], fraction=0.046, pad=0.04)
    cbar1.set_label(value_label)

    im2 = axes[2].imshow(error, cmap="seismic", vmin=-max_abs_err, vmax=max_abs_err)
    axes[2].set_title("FPGA - Python")
    axes[2].set_xlabel("Column")
    axes[2].set_ylabel("Row")
    cbar2 = fig.colorbar(im2, ax=axes[2], fraction=0.046, pad=0.04)
    cbar2.set_label("Error")

    for axis in axes:
        axis.set_aspect("equal")

    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def make_raw_scatter_plot(py_real: np.ndarray, fpga_real: np.ndarray, out_path: Path, title: str) -> None:
    """
    Save a scatter plot of raw Python vs FPGA values.

    Time complexity:
    - O(N), dominated by plotting.
    """

    valid = np.isfinite(py_real) & np.isfinite(fpga_real)
    py = py_real[valid].astype(np.float64)
    fpga = fpga_real[valid].astype(np.float64)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(1, 1, figsize=(6, 6), constrained_layout=True)

    ax.scatter(
        py,
        fpga,
        s=3,
        alpha=0.35,
        label="Compared pixels",
    )

    ax.set_title(title)
    ax.set_xlabel("Python raw real value")
    ax.set_ylabel("FPGA raw real value")
    ax.grid(True, alpha=0.3)

    if py.size > 0 and fpga.size > 0:
        lo = float(min(np.min(py), np.min(fpga)))
        hi = float(max(np.max(py), np.max(fpga)))

        if hi <= lo:
            hi = lo + 1.0

        ax.plot(
            [lo, hi],
            [lo, hi],
            linestyle="--",
            linewidth=1,
            label="Ideal match: FPGA = Python",
        )

    ax.legend(loc="best", fontsize=8)

    fig.savefig(out_path, dpi=200)
    plt.close(fig)


# -----------------------------------------------------------------------------
# Comparison flow
# -----------------------------------------------------------------------------

def resolve_png_paths(
    *,
    base_dir: Path,
    python_root: Path,
    fpga_root: Path,
    dataset: str,
    kind: str,
    compare_type: str,
) -> tuple[Path, Path]:
    """
    Resolve Python and FPGA PNG paths for a PNG-domain comparison.

    Time complexity:
    - O(1).
    """

    if compare_type not in PYTHON_PNG_REL_BY_TYPE_KIND:
        raise ValueError(f"Unsupported PNG compare_type={compare_type!r}")

    if kind not in PYTHON_PNG_REL_BY_TYPE_KIND[compare_type]:
        raise ValueError(f"Unsupported kind={kind!r}")

    python_path = base_dir / python_root / dataset / PYTHON_PNG_REL_BY_TYPE_KIND[compare_type][kind]
    fpga_path = base_dir / fpga_root / dataset / "output_data" / FPGA_PNG_NAME_BY_TYPE_KIND[compare_type][kind]

    return python_path, fpga_path


def compare_png_one(
    *,
    base_dir: Path,
    python_root: Path,
    fpga_root: Path,
    out_dir: Path,
    dataset: str,
    kind: str,
    compare_type: str,
    crop_edge: int,
) -> ComparisonResult:
    """
    Compare one Python PNG against one FPGA PNG.

    Time complexity:
    - O(H * W), where H and W are the compared image dimensions.
    """

    python_path, fpga_path = resolve_png_paths(
        base_dir=base_dir,
        python_root=python_root,
        fpga_root=fpga_root,
        dataset=dataset,
        kind=kind,
        compare_type=compare_type,
    )

    py_raw = load_grayscale_u8(python_path)
    fpga_raw = load_grayscale_u8(fpga_path)

    py_crop = crop_edges(py_raw, crop_edge)
    fpga_crop = crop_edges(fpga_raw, crop_edge)

    py_img, fpga_img = center_crop_to_common(py_crop, fpga_crop)
    metrics, error = compute_png_metrics(py_img, fpga_img)

    plot_path = out_dir / compare_type / dataset / f"{dataset}_{kind}_{compare_type}_python_vs_fpga.png"
    title = f"{dataset.upper()} | {kind} | {compare_type} comparison"

    make_comparison_plot(
        py_img,
        fpga_img,
        error,
        title=title,
        py_label=f"Python {compare_type}",
        fpga_label=f"FPGA {compare_type}",
        value_label="8-bit pixel value",
        out_path=plot_path,
        fixed_u8_scale=True,
    )

    return ComparisonResult(
        dataset=dataset,
        kind=kind,
        compare_type=compare_type,
        python_path=python_path,
        fpga_path=fpga_path,
        plot_path=plot_path,
        python_shape=py_raw.shape,
        fpga_shape=fpga_raw.shape,
        compared_shape=py_img.shape,
        metrics=metrics,
    )


def compare_raw_one(
    *,
    base_dir: Path,
    python_root: Path,
    fpga_root: Path,
    out_dir: Path,
    dataset: str,
    kind: str,
    raw_center_crop_size: int,
    crop_edge: int,
    channel_mode: str,
) -> ComparisonResult:
    """
    Compare one Python IMGB output against one reconstructed FPGA MIF output.

    Time complexity:
    - O(D + H * W log(H * W)), where D is the MIF depth and rank correlation
      requires sorting.
    """

    python_path = base_dir / python_root / dataset / PYTHON_IMGB_REL_BY_KIND[kind]
    fpga_dir = resolve_dataset_fpga_dir(base_dir, fpga_root, dataset)

    py_full = read_imgb_real(python_path, channel_mode=channel_mode)

    # Python IMGB outputs are often 512x512. FPGA final outputs are usually the
    # centred 128x128 region, so crop the Python raw output before comparison.
    if raw_center_crop_size > 0:
        py_full = center_crop_to_size(py_full, raw_center_crop_size, raw_center_crop_size)

    fpga_conf, fpga_disp = reconstruct_fpga_raw_outputs(fpga_dir, image_dim=IMAGE_DIM)
    fpga_full = fpga_conf if kind == "confidence" else fpga_disp

    # Match the disparity display convention used by the PNG converters.
    # PNG outputs already apply this before visualisation, but raw_numeric
    # decodes IMGB/MIF directly, so apply it here for disparity only.
    # Confidence is left unchanged.
    if kind == "disparity":
        py_full = py_full - DISPARITY_RAW_COMPARE_OFFSET
        fpga_full = fpga_full - DISPARITY_RAW_COMPARE_OFFSET

    py_crop = crop_edges(py_full, crop_edge)
    fpga_crop = crop_edges(fpga_full, crop_edge)

    py_img, fpga_img = center_crop_to_common(py_crop, fpga_crop)
    metrics, error = compute_raw_metrics(py_img, fpga_img)

    plot_path = out_dir / "raw_numeric" / dataset / f"{dataset}_{kind}_raw_numeric_python_vs_fpga.png"
    title = f"{dataset.upper()} | {kind} | raw numeric comparison"

    make_comparison_plot(
        py_img,
        fpga_img,
        error,
        title=title,
        py_label="Python IMGB real value",
        fpga_label="FPGA MIF real value",
        value_label="Real value (disparity shown as stored - 1)",
        out_path=plot_path,
        fixed_u8_scale=False,
    )

    scatter_path = out_dir / "raw_numeric" / dataset / f"{dataset}_{kind}_raw_numeric_scatter.png"
    make_raw_scatter_plot(py_img, fpga_img, scatter_path, f"{dataset.upper()} | {kind} | raw scatter")

    return ComparisonResult(
        dataset=dataset,
        kind=kind,
        compare_type="raw_numeric",
        python_path=python_path,
        fpga_path=fpga_dir,
        plot_path=plot_path,
        python_shape=py_full.shape,
        fpga_shape=fpga_full.shape,
        compared_shape=py_img.shape,
        metrics=metrics,
    )


# -----------------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------------

def _fmt_optional(value, fmt: str = ".6f") -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return format(value, fmt)
    return str(value)


def format_result(result: ComparisonResult) -> str:
    """
    Format one result block for terminal/text-report output.

    Time complexity:
    - O(1).
    """

    m = result.metrics

    lines = [
        f"=== {result.dataset.upper()} | {result.kind} | {result.compare_type} ===",
        f"Python path : {result.python_path}",
        f"FPGA path   : {result.fpga_path}",
        f"Plot saved  : {result.plot_path}",
        f"Python shape: {result.python_shape}",
        f"FPGA shape  : {result.fpga_shape}",
        f"Compared shape: {result.compared_shape}",
        f"Compared pixels: {m.total_pixels}",
        f"MSE: {m.mse:.9f}",
        f"Mean absolute error: {m.mean_abs_error:.9f}",
        f"Median absolute error: {m.median_abs_error:.9f}",
        f"Median error (FPGA - Python): {m.median_error:.9f}",
        f"Minimum error (FPGA - Python): {m.min_error:.9f}",
        f"Maximum error (FPGA - Python): {m.max_error:.9f}",
        f"Exact match pixels: {m.exact_match_pixels} / {m.total_pixels}",
        f"Exact match fraction: {m.exact_match_fraction:.6%}",
    ]

    if result.compare_type in {"normalised_png", "linear_png"}:
        lines.extend(
            [
                f"Mean bit-correctness: {_fmt_optional(m.mean_bit_correctness)} / 8",
                f"Median bit-correctness: {_fmt_optional(m.median_bit_correctness)} / 8",
                f"Best bit-correctness: {_fmt_optional(m.best_bit_correctness)} / 8",
                f"Worst bit-correctness: {_fmt_optional(m.worst_bit_correctness)} / 8",
            ]
        )

    if result.compare_type == "raw_numeric":
        lines.extend(
            [
                f"Pearson correlation: {_fmt_optional(m.pearson_corr)}",
                f"Spearman correlation: {_fmt_optional(m.spearman_corr)}",
                f"Python range: {_fmt_optional(m.python_min)} to {_fmt_optional(m.python_max)}",
                f"FPGA range  : {_fmt_optional(m.fpga_min)} to {_fmt_optional(m.fpga_max)}",
                f"Mean offset (FPGA - Python): {_fmt_optional(m.fpga_minus_python_mean)}",
                f"Median offset (FPGA - Python): {_fmt_optional(m.fpga_minus_python_median)}",
                f"Sign match fraction: {_fmt_optional(m.sign_match_fraction, '.6%')}",
                f"Python counts: negative={m.python_negative_pixels}, zero={m.python_zero_pixels}, positive={m.python_positive_pixels}",
                f"FPGA counts  : negative={m.fpga_negative_pixels}, zero={m.fpga_zero_pixels}, positive={m.fpga_positive_pixels}",
            ]
        )

    lines.append("")
    return "\n".join(lines)


def write_text_report(results: list[ComparisonResult], report_path: Path) -> None:
    """
    Write a human-readable text report.

    Time complexity:
    - O(R), where R is the number of comparison results.
    """

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(format_result(result) for result in results), encoding="utf-8")


def write_csv_report(results: list[ComparisonResult], csv_path: Path) -> None:
    """
    Write a CSV report.

    Time complexity:
    - O(R), where R is the number of comparison results.
    """

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "dataset",
        "kind",
        "compare_type",
        "python_path",
        "fpga_path",
        "plot_path",
        "python_shape",
        "fpga_shape",
        "compared_shape",
        "total_pixels",
        "mse",
        "mean_abs_error",
        "median_abs_error",
        "median_error",
        "min_error",
        "max_error",
        "exact_match_pixels",
        "exact_match_fraction",
        "mean_bit_correctness",
        "median_bit_correctness",
        "best_bit_correctness",
        "worst_bit_correctness",
        "pearson_corr",
        "spearman_corr",
        "python_min",
        "python_max",
        "fpga_min",
        "fpga_max",
        "fpga_minus_python_mean",
        "fpga_minus_python_median",
        "sign_match_fraction",
        "python_negative_pixels",
        "python_zero_pixels",
        "python_positive_pixels",
        "fpga_negative_pixels",
        "fpga_zero_pixels",
        "fpga_positive_pixels",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            m = result.metrics
            writer.writerow(
                {
                    "dataset": result.dataset,
                    "kind": result.kind,
                    "compare_type": result.compare_type,
                    "python_path": str(result.python_path),
                    "fpga_path": str(result.fpga_path),
                    "plot_path": str(result.plot_path),
                    "python_shape": str(result.python_shape),
                    "fpga_shape": str(result.fpga_shape),
                    "compared_shape": str(result.compared_shape),
                    "total_pixels": m.total_pixels,
                    "mse": m.mse,
                    "mean_abs_error": m.mean_abs_error,
                    "median_abs_error": m.median_abs_error,
                    "median_error": m.median_error,
                    "min_error": m.min_error,
                    "max_error": m.max_error,
                    "exact_match_pixels": m.exact_match_pixels,
                    "exact_match_fraction": m.exact_match_fraction,
                    "mean_bit_correctness": m.mean_bit_correctness,
                    "median_bit_correctness": m.median_bit_correctness,
                    "best_bit_correctness": m.best_bit_correctness,
                    "worst_bit_correctness": m.worst_bit_correctness,
                    "pearson_corr": m.pearson_corr,
                    "spearman_corr": m.spearman_corr,
                    "python_min": m.python_min,
                    "python_max": m.python_max,
                    "fpga_min": m.fpga_min,
                    "fpga_max": m.fpga_max,
                    "fpga_minus_python_mean": m.fpga_minus_python_mean,
                    "fpga_minus_python_median": m.fpga_minus_python_median,
                    "sign_match_fraction": m.sign_match_fraction,
                    "python_negative_pixels": m.python_negative_pixels,
                    "python_zero_pixels": m.python_zero_pixels,
                    "python_positive_pixels": m.python_positive_pixels,
                    "fpga_negative_pixels": m.fpga_negative_pixels,
                    "fpga_zero_pixels": m.fpga_zero_pixels,
                    "fpga_positive_pixels": m.fpga_positive_pixels,
                }
            )


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Time complexity:
    - O(A), where A is the number of command-line arguments.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Compare Python and FPGA outputs using normalised PNGs, non-normalised PNGs, "
            "and raw IMGB/MIF numeric values."
        )
    )

    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path.cwd(),
        help="Project root containing Python_Red/ and SystemVerilog_HDL_Red/.",
    )

    parser.add_argument(
        "--python-root",
        type=Path,
        default=Path("Python_Red") / "No_Libraries",
        help="Root containing per-dataset Python output folders.",
    )

    parser.add_argument(
        "--fpga-root",
        type=Path,
        default=Path("SystemVerilog_HDL_Red") / "Standard" / "tb",
        help="Root containing per-dataset FPGA output folders.",
    )

    parser.add_argument(
        "--datasets",
        nargs="+",
        default=DEFAULT_DATASETS,
        help="Datasets to compare, e.g. head dino town.",
    )

    parser.add_argument(
        "--kinds",
        nargs="+",
        default=DEFAULT_KINDS,
        choices=DEFAULT_KINDS,
        help="Output kinds to compare.",
    )

    parser.add_argument(
        "--compare-types",
        nargs="+",
        default=DEFAULT_COMPARE_TYPES,
        choices=DEFAULT_COMPARE_TYPES,
        help="Comparison types to run.",
    )

    parser.add_argument(
        "--png-crop-edge",
        type=int,
        default=0,
        help="Optional extra crop applied to PNGs before comparison. Default is 0.",
    )

    parser.add_argument(
        "--raw-crop-edge",
        type=int,
        default=0,
        help="Optional extra crop applied to raw numeric arrays before comparison. Default is 0.",
    )

    parser.add_argument(
        "--raw-center-crop-size",
        type=int,
        default=128,
        help=(
            "Centre-crop Python IMGB raw outputs to this square size before raw comparison. "
            "Use 128 for the red 128 FPGA comparison. Use 0 to disable."
        ),
    )

    parser.add_argument(
        "--channel-mode",
        choices=["first", "mean"],
        default="first",
        help="How to handle multi-channel Python IMGB files in raw_numeric mode.",
    )

    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("SystemVerilog_HDL_Red") / "Standard" / "comparison_outputs_all",
        help="Directory where plots and reports are written.",
    )

    return parser.parse_args()


def main() -> None:
    """
    Run all requested comparisons.

    Time complexity:
    - O(R * (D + H * W log(H * W))), where R is the number of comparisons and
      D is the MIF depth for raw_numeric comparisons.
    """

    args = parse_args()

    base_dir = args.base_dir.resolve()
    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = base_dir / out_dir
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[ComparisonResult] = []

    for dataset in args.datasets:
        for kind in args.kinds:
            for compare_type in args.compare_types:
                print(f"\nComparing dataset={dataset}, kind={kind}, compare_type={compare_type}")

                if compare_type in {"normalised_png", "linear_png"}:
                    result = compare_png_one(
                        base_dir=base_dir,
                        python_root=args.python_root,
                        fpga_root=args.fpga_root,
                        out_dir=out_dir,
                        dataset=dataset,
                        kind=kind,
                        compare_type=compare_type,
                        crop_edge=args.png_crop_edge,
                    )
                elif compare_type == "raw_numeric":
                    result = compare_raw_one(
                        base_dir=base_dir,
                        python_root=args.python_root,
                        fpga_root=args.fpga_root,
                        out_dir=out_dir,
                        dataset=dataset,
                        kind=kind,
                        raw_center_crop_size=args.raw_center_crop_size,
                        crop_edge=args.raw_crop_edge,
                        channel_mode=args.channel_mode,
                    )
                else:
                    raise ValueError(f"Unsupported compare_type={compare_type!r}")

                results.append(result)
                print(format_result(result), end="")

    report_path = out_dir / "python_vs_fpga_all_comparisons_report.txt"
    csv_path = out_dir / "python_vs_fpga_all_comparisons_report.csv"

    write_text_report(results, report_path)
    write_csv_report(results, csv_path)

    print(f"Saved text report: {report_path}")
    print(f"Saved CSV report : {csv_path}")


if __name__ == "__main__":
    main()

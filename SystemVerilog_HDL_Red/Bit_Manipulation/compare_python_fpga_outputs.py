#!/usr/bin/env python3
"""
Compare Python IMGB outputs against FPGA MIF outputs for confidence and disparity.

This replaces the older PNG-vs-PNG comparison with a numeric comparison in the
same fixed-point domains used by the hardware:

- Python outputs:
    confidence/C_avg.imgb
    disparity/Z_conf.imgb

- FPGA outputs:
    SIM_PIXEL_VALID_OUT.mif
    SIM_ROW_IDX_OUT.mif
    SIM_COLUMN_IDX_OUT.mif
    SIM_CONFIDENCE_PIXEL_BIT_DATA.mif
    SIM_WEIGHTED_DISPARITY_PIXEL_BIT_DATA.mif

Default fixed-point formats:
- confidence: unsigned Q8.2, 10-bit
- disparity:  signed   Q8.8, 16-bit

The comparison reports:
- real-valued errors, e.g. FPGA_float - Python_float
- fixed-point/raw errors, e.g. FPGA_raw - quantised_Python_raw
- exact raw match fraction
- mean/worst/best bit correctness over the actual FPGA word width
- side-by-side plots for Python, FPGA, and difference
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BIAS_INT = 8388608
Q_SCALE = 4096


# -----------------------------------------------------------------------------
# Default project layout
# -----------------------------------------------------------------------------

DEFAULT_DATASETS = ["head", "dino", "town"]

PYTHON_CONF_REL = Path("confidence") / "C_avg.imgb"
PYTHON_DISP_REL = Path("disparity") / "Z_conf.imgb"

FPGA_VALID_MIF = "SIM_PIXEL_VALID_OUT.mif"
FPGA_ROW_MIF = "SIM_ROW_IDX_OUT.mif"
FPGA_COL_MIF = "SIM_COLUMN_IDX_OUT.mif"
FPGA_CONF_MIF = "SIM_CONFIDENCE_PIXEL_BIT_DATA.mif"
FPGA_DISP_MIF = "SIM_WEIGHTED_DISPARITY_PIXEL_BIT_DATA.mif"

IMAGE_DIM = 128

CONF_WIDTH_BITS = 10
CONF_FRAC_BITS = 2

DISP_WIDTH_BITS = 16
DISP_FRAC_BITS = 8


# -----------------------------------------------------------------------------
# Data containers
# -----------------------------------------------------------------------------

@dataclass
class NumericImagePair:
    """Holds aligned Python and FPGA data for one output type."""

    dataset: str
    kind: str
    python_path: Path
    fpga_dir: Path
    python_real: np.ndarray
    python_raw_quantised: np.ndarray
    fpga_real: np.ndarray
    fpga_raw: np.ndarray
    valid_mask: np.ndarray
    width_bits: int
    frac_bits: int
    signed: bool


@dataclass
class Metrics:
    """Scalar metrics for one Python-vs-FPGA comparison."""

    total_pixels: int
    compared_pixels: int

    real_mse: float
    real_mean_abs_error: float
    real_median_abs_error: float
    real_min_error: float
    real_max_error: float
    real_median_error: float

    raw_mse: float
    raw_mean_abs_error: float
    raw_median_abs_error: float
    raw_min_error: int
    raw_max_error: int
    raw_median_error: float

    mean_bit_correctness: float
    median_bit_correctness: float
    best_bit_correctness: int
    worst_bit_correctness: int

    exact_match_pixels: int
    exact_match_fraction: float


@dataclass
class ComparisonResult:
    """Stores paths and metrics for one completed comparison."""

    dataset: str
    kind: str
    python_path: Path
    fpga_dir: Path
    plot_path: Path
    metrics: Metrics
    compared_shape: tuple[int, int]


# -----------------------------------------------------------------------------
# MIF parsing helpers
# -----------------------------------------------------------------------------

def _u32_le(b: bytes, off: int) -> int:
    return int.from_bytes(b[off:off + 4], "little", signed=False)

def imgb_parse(buf: bytes):
    W = _u32_le(buf, 4)
    H = _u32_le(buf, 8)
    C = buf[12]
    dtype_code = buf[13]
    payload = buf[16:]

    return int(W), int(H), int(C), int(dtype_code), payload

def _read_depth_from_mif_header(path: Path) -> int:
    """
    Read the DEPTH field from a .mif header.

    Time complexity:
    - O(L), where L is the number of header lines scanned before DEPTH is found.
    """

    with path.open("r", encoding="utf-8") as file_obj:
        for line in file_obj:
            stripped = line.strip()
            if stripped.startswith("DEPTH=") and stripped.endswith(";"):
                return int(stripped[len("DEPTH="):-1])

    raise ValueError(f"Could not parse DEPTH from MIF header: {path}")


def _parse_content_bits_lines(path: Path) -> dict[int, str]:
    """
    Parse the CONTENT BEGIN ... END; region of a .mif file.

    Time complexity:
    - O(L), where L is the total number of lines in the MIF file.
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

            bits = right.strip().replace(" ", "")
            addr_to_bits[addr] = bits

    return addr_to_bits


def load_mif_bits(path: Path, width_bits: int) -> np.ndarray:
    """
    Load a MIF as unsigned integer values.

    Time complexity:
    - O(D + L), where D is the MIF depth and L is the number of lines.
    """

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
    Convert unsigned width-bit words to signed two's-complement integers.

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

    raw = load_mif_bits(path, width_bits)
    return twos_complement_to_int(raw, width_bits)


# -----------------------------------------------------------------------------
# IMGB parsing helpers
# -----------------------------------------------------------------------------

def _decode_u24_q12_12(payload: bytes, n_samples: int) -> np.ndarray:
    """
    Decode biased unsigned 24-bit Q12.12 IMGB payload values into float32.

    Time complexity:
    - O(N), where N is the number of samples.
    """

    b = np.frombuffer(payload, dtype=np.uint8).reshape((-1, 3))

    u24 = (
        b[:, 0].astype(np.uint32)
        | (b[:, 1].astype(np.uint32) * np.uint32(256))
        | (b[:, 2].astype(np.uint32) * np.uint32(65536))
    )

    decoded = (
        u24.astype(np.int32) - np.int32(BIAS_INT)
    ).astype(np.float32) / np.float32(Q_SCALE)

    if decoded.size != n_samples:
        raise ValueError(
            f"Decoded IMGB sample count mismatch: expected {n_samples}, got {decoded.size}"
        )

    return decoded


def read_imgb_real(path: Path, channel_mode: str = "first") -> np.ndarray:
    """
    Read an IMGB file and return a 2D float32 image.

    Supported dtype codes:
    - 1: raw unsigned 8-bit
    - 4: biased unsigned 24-bit Q12.12

    If the IMGB has multiple channels, channel_mode controls the reduction:
    - first: use channel 0
    - mean: average all channels

    Time complexity:
    - O(H * W * C), where C is the number of channels.
    """

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
        return arr.reshape((height, width)).astype(np.float32, copy=False)

    arr = arr.reshape((height, width, channels))

    if channel_mode == "first":
        return arr[:, :, 0].astype(np.float32, copy=False)

    if channel_mode == "mean":
        return np.mean(arr.astype(np.float32), axis=2)

    raise ValueError(f"Unsupported channel_mode={channel_mode!r}. Use 'first' or 'mean'.")


# -----------------------------------------------------------------------------
# Fixed-point conversion helpers
# -----------------------------------------------------------------------------

def quantise_real_to_fixed_raw(
    real_values: np.ndarray,
    *,
    width_bits: int,
    frac_bits: int,
    signed: bool,
) -> np.ndarray:
    """
    Quantise float values into the target fixed-point raw integer domain.

    Time complexity:
    - O(N), where N is the number of pixels.
    """

    finite_values = np.where(np.isfinite(real_values), real_values, 0.0)
    scaled = np.rint(finite_values.astype(np.float64) * float(1 << frac_bits))

    if signed:
        min_raw = -(1 << (width_bits - 1))
        max_raw = (1 << (width_bits - 1)) - 1
    else:
        min_raw = 0
        max_raw = (1 << width_bits) - 1

    clipped = np.clip(scaled, min_raw, max_raw)
    return clipped.astype(np.int64)


def fixed_raw_to_real(raw_values: np.ndarray, frac_bits: int) -> np.ndarray:
    """
    Convert fixed-point raw integer values into float64 real values.

    Time complexity:
    - O(N), where N is the number of pixels.
    """

    return raw_values.astype(np.float64) / float(1 << frac_bits)


def crop_edges(arr: np.ndarray, crop_edge: int) -> np.ndarray:
    """
    Remove crop_edge pixels from all four sides.

    Time complexity:
    - O(1) view creation for NumPy arrays.
    """

    if crop_edge <= 0:
        return arr

    if arr.shape[0] <= 2 * crop_edge or arr.shape[1] <= 2 * crop_edge:
        raise ValueError(f"Cannot crop {crop_edge} pixels from array with shape {arr.shape}")

    return arr[crop_edge:-crop_edge, crop_edge:-crop_edge]


def center_crop_to_common(
    arrays: Iterable[np.ndarray],
) -> list[np.ndarray]:
    """
    Center-crop arrays to the common minimum height and width.

    Time complexity:
    - O(K), where K is the number of arrays; crops are NumPy views.
    """

    arrays_list = list(arrays)
    target_h = min(arr.shape[0] for arr in arrays_list)
    target_w = min(arr.shape[1] for arr in arrays_list)

    cropped = []

    for arr in arrays_list:
        start_y = (arr.shape[0] - target_h) // 2
        start_x = (arr.shape[1] - target_w) // 2
        cropped.append(arr[start_y:start_y + target_h, start_x:start_x + target_w])

    return cropped


# -----------------------------------------------------------------------------
# FPGA reconstruction
# -----------------------------------------------------------------------------

def require_file(path: Path) -> None:
    """
    Raise FileNotFoundError if the file does not exist.

    Time complexity:
    - O(1), filesystem lookup aside.
    """

    if not path.is_file():
        raise FileNotFoundError(f"Missing required file: {path}")


def reconstruct_fpga_fused_outputs(
    fpga_dir: Path,
    *,
    image_dim: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Reconstruct FPGA confidence and fused weighted disparity raw arrays from MIF streams.

    Output arrays:
    - confidence_raw: int64 array, unsigned Q8.2 raw values
    - disparity_raw:  int64 array, signed Q8.8 raw values

    Missing/unwritten pixels are left as NaN in float arrays during construction
    and then returned as float arrays so the valid mask can be formed cleanly.

    Time complexity:
    - O(D + image_dim^2), where D is the MIF stream depth.
    """

    valid_path = fpga_dir / FPGA_VALID_MIF
    row_path = fpga_dir / FPGA_ROW_MIF
    col_path = fpga_dir / FPGA_COL_MIF
    conf_path = fpga_dir / FPGA_CONF_MIF
    disp_path = fpga_dir / FPGA_DISP_MIF

    for path in [valid_path, row_path, col_path, conf_path, disp_path]:
        require_file(path)

    valid = load_mif_bits(valid_path, 1)
    row_idx = load_mif_bits(row_path, 7)
    col_idx = load_mif_bits(col_path, 7)
    conf_raw_stream = load_mif_bits(conf_path, CONF_WIDTH_BITS)
    disp_raw_stream = load_mif_bits_signed(disp_path, DISP_WIDTH_BITS)

    depth = len(valid)

    if not (
        len(row_idx) == depth
        and len(col_idx) == depth
        and len(conf_raw_stream) == depth
        and len(disp_raw_stream) == depth
    ):
        raise ValueError(f"MIF DEPTH mismatch in FPGA output directory: {fpga_dir}")

    conf_raw = np.full((image_dim, image_dim), np.nan, dtype=np.float64)
    disp_raw = np.full((image_dim, image_dim), np.nan, dtype=np.float64)

    for stream_idx in range(depth):
        if int(valid[stream_idx]) == 0:
            continue

        y_coord = int(row_idx[stream_idx])
        x_coord = int(col_idx[stream_idx])

        if 0 <= y_coord < image_dim and 0 <= x_coord < image_dim:
            conf_raw[y_coord, x_coord] = float(int(conf_raw_stream[stream_idx]))
            disp_raw[y_coord, x_coord] = float(int(disp_raw_stream[stream_idx]))

    return conf_raw, disp_raw


# -----------------------------------------------------------------------------
# Metrics and plotting
# -----------------------------------------------------------------------------

def _raw_to_unsigned_word(raw_values: np.ndarray, width_bits: int) -> np.ndarray:
    """
    Convert signed/unsigned raw integer values to masked unsigned words.

    Time complexity:
    - O(N), where N is the number of pixels.
    """

    mask = (1 << width_bits) - 1
    return np.bitwise_and(raw_values.astype(np.int64), mask).astype(np.uint64)


def bit_correctness(
    python_raw: np.ndarray,
    fpga_raw: np.ndarray,
    width_bits: int,
) -> np.ndarray:
    """
    Compute matching bit count per pixel for the target word width.

    Time complexity:
    - O(N * width_bits), implemented with a small loop over bit positions.
    """

    py_word = _raw_to_unsigned_word(python_raw, width_bits)
    fpga_word = _raw_to_unsigned_word(fpga_raw, width_bits)
    xor_word = np.bitwise_xor(py_word, fpga_word)

    differing = np.zeros(xor_word.shape, dtype=np.int16)

    for bit_idx in range(width_bits):
        differing += ((xor_word // np.uint64(1 << bit_idx)) & np.uint64(1)).astype(np.int16)

    return width_bits - differing


def compute_metrics(pair: NumericImagePair) -> tuple[Metrics, np.ndarray, np.ndarray]:
    """
    Compute real-domain and raw fixed-point-domain metrics.

    Time complexity:
    - O(N * width_bits), dominated by bit-correctness calculation.
    """

    mask = pair.valid_mask

    py_real = pair.python_real[mask].astype(np.float64)
    fpga_real = pair.fpga_real[mask].astype(np.float64)

    py_raw = pair.python_raw_quantised[mask].astype(np.int64)
    fpga_raw = pair.fpga_raw[mask].astype(np.int64)

    real_error = fpga_real - py_real
    raw_error = fpga_raw - py_raw

    bc = bit_correctness(py_raw, fpga_raw, pair.width_bits)

    exact_match_pixels = int(np.count_nonzero(raw_error == 0))
    compared_pixels = int(raw_error.size)

    metrics = Metrics(
        total_pixels=int(pair.valid_mask.size),
        compared_pixels=compared_pixels,

        real_mse=float(np.mean(real_error ** 2)),
        real_mean_abs_error=float(np.mean(np.abs(real_error))),
        real_median_abs_error=float(np.median(np.abs(real_error))),
        real_min_error=float(np.min(real_error)),
        real_max_error=float(np.max(real_error)),
        real_median_error=float(np.median(real_error)),

        raw_mse=float(np.mean(raw_error.astype(np.float64) ** 2)),
        raw_mean_abs_error=float(np.mean(np.abs(raw_error.astype(np.float64)))),
        raw_median_abs_error=float(np.median(np.abs(raw_error.astype(np.float64)))),
        raw_min_error=int(np.min(raw_error)),
        raw_max_error=int(np.max(raw_error)),
        raw_median_error=float(np.median(raw_error.astype(np.float64))),

        mean_bit_correctness=float(np.mean(bc.astype(np.float64))),
        median_bit_correctness=float(np.median(bc.astype(np.float64))),
        best_bit_correctness=int(np.max(bc)),
        worst_bit_correctness=int(np.min(bc)),

        exact_match_pixels=exact_match_pixels,
        exact_match_fraction=float(exact_match_pixels / compared_pixels) if compared_pixels > 0 else 0.0,
    )

    full_real_error = np.full(pair.valid_mask.shape, np.nan, dtype=np.float64)
    full_raw_error = np.full(pair.valid_mask.shape, np.nan, dtype=np.float64)

    full_real_error[mask] = pair.fpga_real[mask] - pair.python_real[mask]
    full_raw_error[mask] = pair.fpga_raw[mask].astype(np.float64) - pair.python_raw_quantised[mask].astype(np.float64)

    return metrics, full_real_error, full_raw_error


def _finite_limits(arrays: Iterable[np.ndarray]) -> tuple[float, float]:
    """
    Compute common min/max over finite values in multiple arrays.

    Time complexity:
    - O(N), where N is the total number of pixels.
    """

    values = []

    for arr in arrays:
        finite = np.isfinite(arr)
        if finite.any():
            values.append(arr[finite])

    if not values:
        return 0.0, 1.0

    merged = np.concatenate(values)
    vmin = float(np.min(merged))
    vmax = float(np.max(merged))

    if vmax <= vmin:
        vmax = vmin + 1.0

    return vmin, vmax


def make_comparison_plot(
    pair: NumericImagePair,
    real_error: np.ndarray,
    out_path: Path,
) -> None:
    """
    Save a 1x3 comparison plot: Python, FPGA, and FPGA-Python difference.

    Time complexity:
    - O(H * W), dominated by rendering.
    """

    py_plot = np.where(pair.valid_mask, pair.python_real, np.nan)
    fpga_plot = np.where(pair.valid_mask, pair.fpga_real, np.nan)

    data_vmin, data_vmax = _finite_limits([py_plot, fpga_plot])

    finite_error = real_error[np.isfinite(real_error)]
    if finite_error.size == 0:
        max_abs_error = 1.0
    else:
        max_abs_error = float(np.max(np.abs(finite_error)))
        if max_abs_error == 0.0:
            max_abs_error = 1.0

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)

    fig.suptitle(
        f"{pair.dataset.upper()} | {pair.kind} | Python IMGB vs FPGA MIF",
        fontsize=12,
    )

    im0 = axes[0].imshow(py_plot, cmap="gray", vmin=data_vmin, vmax=data_vmax)
    axes[0].set_title("Python real value")
    axes[0].set_xlabel("Column")
    axes[0].set_ylabel("Row")
    cbar0 = fig.colorbar(im0, ax=axes[0], fraction=0.046, pad=0.04)
    cbar0.set_label(pair.kind)

    im1 = axes[1].imshow(fpga_plot, cmap="gray", vmin=data_vmin, vmax=data_vmax)
    axes[1].set_title("FPGA real value")
    axes[1].set_xlabel("Column")
    axes[1].set_ylabel("Row")
    cbar1 = fig.colorbar(im1, ax=axes[1], fraction=0.046, pad=0.04)
    cbar1.set_label(pair.kind)

    im2 = axes[2].imshow(real_error, cmap="seismic", vmin=-max_abs_error, vmax=max_abs_error)
    axes[2].set_title("FPGA - Python")
    axes[2].set_xlabel("Column")
    axes[2].set_ylabel("Row")
    cbar2 = fig.colorbar(im2, ax=axes[2], fraction=0.046, pad=0.04)
    cbar2.set_label("Real-value error")

    for axis in axes:
        axis.set_aspect("equal")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


# -----------------------------------------------------------------------------
# Comparison flow
# -----------------------------------------------------------------------------

def resolve_dataset_fpga_dir(base_dir: Path, fpga_root: Path, dataset: str) -> Path:
    """
    Resolve the FPGA output directory for a dataset.

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
        "Could not find FPGA output MIF directory for dataset "
        f"{dataset!r}. Checked:\n" + "\n".join(str(c) for c in candidates)
    )


def build_pair(
    *,
    base_dir: Path,
    python_root: Path,
    fpga_root: Path,
    dataset: str,
    kind: str,
    crop_edge: int,
    channel_mode: str,
) -> NumericImagePair:
    """
    Load, reconstruct, crop, align, and quantise one comparison pair.

    Time complexity:
    - O(D + H * W), where D is FPGA stream depth.
    """

    dataset_python_dir = base_dir / python_root / dataset
    fpga_dir = resolve_dataset_fpga_dir(base_dir, fpga_root, dataset)

    python_path = dataset_python_dir / (PYTHON_CONF_REL if kind == "confidence" else PYTHON_DISP_REL)

    if not python_path.is_file():
        raise FileNotFoundError(f"Missing Python IMGB output: {python_path}")

    python_real = read_imgb_real(python_path, channel_mode=channel_mode).astype(np.float64)

    fpga_conf_raw_full, fpga_disp_raw_full = reconstruct_fpga_fused_outputs(
        fpga_dir,
        image_dim=IMAGE_DIM,
    )

    if kind == "confidence":
        width_bits = CONF_WIDTH_BITS
        frac_bits = CONF_FRAC_BITS
        signed = False
        fpga_raw = fpga_conf_raw_full
    elif kind == "disparity":
        width_bits = DISP_WIDTH_BITS
        frac_bits = DISP_FRAC_BITS
        signed = True
        fpga_raw = fpga_disp_raw_full
    else:
        raise ValueError(f"Unsupported kind={kind!r}")

    fpga_real = fixed_raw_to_real(fpga_raw, frac_bits)

    python_real = crop_edges(python_real, crop_edge)
    fpga_real = crop_edges(fpga_real, crop_edge)
    fpga_raw = crop_edges(fpga_raw, crop_edge)

    python_real, fpga_real, fpga_raw = center_crop_to_common(
        [python_real, fpga_real, fpga_raw]
    )

    python_raw_quantised = quantise_real_to_fixed_raw(
        python_real,
        width_bits=width_bits,
        frac_bits=frac_bits,
        signed=signed,
    )

    fpga_raw_quantised = fpga_raw.astype(np.float64)

    valid_mask = (
        np.isfinite(python_real)
        & np.isfinite(fpga_real)
        & np.isfinite(fpga_raw_quantised)
    )

    return NumericImagePair(
        dataset=dataset,
        kind=kind,
        python_path=python_path,
        fpga_dir=fpga_dir,
        python_real=python_real,
        python_raw_quantised=python_raw_quantised,
        fpga_real=fpga_real,
        fpga_raw=np.where(np.isfinite(fpga_raw_quantised), fpga_raw_quantised, 0.0).astype(np.int64),
        valid_mask=valid_mask,
        width_bits=width_bits,
        frac_bits=frac_bits,
        signed=signed,
    )


def compare_one(
    *,
    base_dir: Path,
    python_root: Path,
    fpga_root: Path,
    out_dir: Path,
    dataset: str,
    kind: str,
    crop_edge: int,
    channel_mode: str,
) -> ComparisonResult:
    """
    Compare one dataset/kind pair and save its plot.

    Time complexity:
    - O(D + H * W * width_bits).
    """

    pair = build_pair(
        base_dir=base_dir,
        python_root=python_root,
        fpga_root=fpga_root,
        dataset=dataset,
        kind=kind,
        crop_edge=crop_edge,
        channel_mode=channel_mode,
    )

    metrics, real_error, _raw_error = compute_metrics(pair)

    plot_path = out_dir / dataset / f"{dataset}_{kind}_python_vs_fpga.png"
    make_comparison_plot(pair, real_error, plot_path)

    return ComparisonResult(
        dataset=dataset,
        kind=kind,
        python_path=pair.python_path,
        fpga_dir=pair.fpga_dir,
        plot_path=plot_path,
        metrics=metrics,
        compared_shape=pair.python_real.shape,
    )


# -----------------------------------------------------------------------------
# Reporting helpers
# -----------------------------------------------------------------------------

def format_result(result: ComparisonResult) -> str:
    """
    Format one result for terminal/text report output.

    Time complexity:
    - O(1).
    """

    m = result.metrics

    lines = [
        f"=== {result.dataset.upper()} | {result.kind} ===",
        f"Python path: {result.python_path}",
        f"FPGA dir   : {result.fpga_dir}",
        f"Plot saved : {result.plot_path}",
        f"Compared shape: {result.compared_shape}",
        f"Compared pixels: {m.compared_pixels} / {m.total_pixels}",
        "",
        "Real-value metrics:",
        f"  MSE: {m.real_mse:.9f}",
        f"  Mean absolute error: {m.real_mean_abs_error:.9f}",
        f"  Median absolute error: {m.real_median_abs_error:.9f}",
        f"  Median error (FPGA - Python): {m.real_median_error:.9f}",
        f"  Minimum error (FPGA - Python): {m.real_min_error:.9f}",
        f"  Maximum error (FPGA - Python): {m.real_max_error:.9f}",
        "",
        "Raw fixed-point metrics:",
        f"  MSE: {m.raw_mse:.9f}",
        f"  Mean absolute error: {m.raw_mean_abs_error:.9f}",
        f"  Median absolute error: {m.raw_median_abs_error:.9f}",
        f"  Median error (FPGA_raw - quantised_Python_raw): {m.raw_median_error:.9f}",
        f"  Minimum error (FPGA_raw - quantised_Python_raw): {m.raw_min_error}",
        f"  Maximum error (FPGA_raw - quantised_Python_raw): {m.raw_max_error}",
        "",
        "Bit-correctness metrics:",
        f"  Mean bit-correctness: {m.mean_bit_correctness:.9f}",
        f"  Median bit-correctness: {m.median_bit_correctness:.9f}",
        f"  Best bit-correctness: {m.best_bit_correctness}",
        f"  Worst bit-correctness: {m.worst_bit_correctness}",
        f"  Exact raw-match pixels: {m.exact_match_pixels} / {m.compared_pixels}",
        f"  Exact raw-match fraction: {m.exact_match_fraction:.9%}",
        "",
    ]

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
    Write a machine-readable CSV report.

    Time complexity:
    - O(R), where R is the number of comparison results.
    """

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "dataset",
        "kind",
        "python_path",
        "fpga_dir",
        "plot_path",
        "compared_shape",
        "compared_pixels",
        "total_pixels",
        "real_mse",
        "real_mean_abs_error",
        "real_median_abs_error",
        "real_median_error",
        "real_min_error",
        "real_max_error",
        "raw_mse",
        "raw_mean_abs_error",
        "raw_median_abs_error",
        "raw_median_error",
        "raw_min_error",
        "raw_max_error",
        "mean_bit_correctness",
        "median_bit_correctness",
        "best_bit_correctness",
        "worst_bit_correctness",
        "exact_match_pixels",
        "exact_match_fraction",
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
                    "python_path": str(result.python_path),
                    "fpga_dir": str(result.fpga_dir),
                    "plot_path": str(result.plot_path),
                    "compared_shape": str(result.compared_shape),
                    "compared_pixels": m.compared_pixels,
                    "total_pixels": m.total_pixels,
                    "real_mse": m.real_mse,
                    "real_mean_abs_error": m.real_mean_abs_error,
                    "real_median_abs_error": m.real_median_abs_error,
                    "real_median_error": m.real_median_error,
                    "real_min_error": m.real_min_error,
                    "real_max_error": m.real_max_error,
                    "raw_mse": m.raw_mse,
                    "raw_mean_abs_error": m.raw_mean_abs_error,
                    "raw_median_abs_error": m.raw_median_abs_error,
                    "raw_median_error": m.raw_median_error,
                    "raw_min_error": m.raw_min_error,
                    "raw_max_error": m.raw_max_error,
                    "mean_bit_correctness": m.mean_bit_correctness,
                    "median_bit_correctness": m.median_bit_correctness,
                    "best_bit_correctness": m.best_bit_correctness,
                    "worst_bit_correctness": m.worst_bit_correctness,
                    "exact_match_pixels": m.exact_match_pixels,
                    "exact_match_fraction": m.exact_match_fraction,
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
            "Compare Python .imgb confidence/disparity outputs against FPGA "
            ".mif confidence/disparity outputs."
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
        default=Path("Python_Red") / "Bit_Manipulation",
        help="Root containing per-dataset Python output folders.",
    )

    parser.add_argument(
        "--fpga-root",
        type=Path,
        default=Path("SystemVerilog_HDL_Red") / "Bit_Manipulation" / "tb",
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
        default=["confidence", "disparity"],
        choices=["confidence", "disparity"],
        help="Output kinds to compare.",
    )

    parser.add_argument(
        "--crop-edge",
        type=int,
        default=7,
        help=(
            "Pixels removed from all four sides before comparison. "
            "Use 7 for final low-pass/top-level outputs and 5 for pre-final FAO outputs."
        ),
    )

    parser.add_argument(
        "--channel-mode",
        choices=["first", "mean"],
        default="first",
        help="How to handle multi-channel Python IMGB files.",
    )

    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("SystemVerilog_HDL_Red") / "Bit_Manipulation" / "comparison_outputs_numeric",
        help="Directory where plots and reports are written.",
    )

    return parser.parse_args()


def main() -> None:
    """
    Run all requested comparisons.

    Time complexity:
    - O(R * (D + H * W * width_bits)), where R is the number of comparisons.
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
            print(f"\nComparing dataset={dataset}, kind={kind}")

            result = compare_one(
                base_dir=base_dir,
                python_root=args.python_root,
                fpga_root=args.fpga_root,
                out_dir=out_dir,
                dataset=dataset,
                kind=kind,
                crop_edge=args.crop_edge,
                channel_mode=args.channel_mode,
            )

            results.append(result)
            print(format_result(result), end="")

    report_path = out_dir / "python_vs_fpga_numeric_report.txt"
    csv_path = out_dir / "python_vs_fpga_numeric_report.csv"

    write_text_report(results, report_path)
    write_csv_report(results, csv_path)

    print(f"Saved text report: {report_path}")
    print(f"Saved CSV report : {csv_path}")


if __name__ == "__main__":
    main()
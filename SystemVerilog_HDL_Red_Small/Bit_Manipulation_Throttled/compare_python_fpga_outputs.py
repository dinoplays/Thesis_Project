#!/usr/bin/env python3
"""
Compare FPGA output PNGs against Python_Red reference PNGs.

Outputs:
- Terminal summary
- Text report
- Side-by-side comparison PNGs (Python_Red | FPGA | Normalized Difference)

Metrics per pair:
- MSE
- minimum error
- maximum error
- mean bit-correctness
- best bit-correctness
- worst bit-correctness

Bit-correctness is computed per pixel on 8-bit grayscale values as the number of
matching bit positions between the Python_Red and FPGA pixels, in the range [0, 8].
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# -----------------------------------------------------------------------------
# Relative paths provided by user
# -----------------------------------------------------------------------------
PAIR_SPECS = [
    {
        "name": "confidence_nonrobust",
        "python_rel": "Python_Red/Bit_Manipulation/headshot/confidence_png_center_64x64_png/C_avg.png",
        "fpga_rel": "SystemVerilog_HDL_Red_Small/Bit_Manipulation/tb/output_data/fused_confidence.png",
        "kind": "confidence",
        "robust": False,
        "index": 1,
    },
    {
        "name": "disparity_nonrobust",
        "python_rel": "Python_Red/Bit_Manipulation/headshot/disparity_png_center_64x64_png/Z_conf.png",
        "fpga_rel": "SystemVerilog_HDL_Red_Small/Bit_Manipulation/tb/output_data/fused_weighted_disparity.png",
        "kind": "disparity",
        "robust": False,
        "index": 2,
    },
    {
        "name": "confidence_robust",
        "python_rel": "Python_Red/Bit_Manipulation/headshot/confidence_robust_png_center_64x64_png/C_avg.png",
        "fpga_rel": "SystemVerilog_HDL_Red_Small/Bit_Manipulation/tb/output_data/fused_confidence_robust.png",
        "kind": "confidence",
        "robust": True,
        "index": 3,
    },
    {
        "name": "disparity_robust",
        "python_rel": "Python_Red/Bit_Manipulation/headshot/disparity_robust_png_center_64x64_png/Z_conf.png",
        "fpga_rel": "SystemVerilog_HDL_Red_Small/Bit_Manipulation/tb/output_data/fused_weighted_disparity_robust.png",
        "kind": "disparity",
        "robust": True,
        "index": 4,
    },
]


@dataclass
class Metrics:
    mse: float
    min_error: int
    max_error: int
    mean_abs_error: float
    median_abs_error: float
    median_error: float
    mean_bit_correctness: float
    median_bit_correctness: float
    best_bit_correctness: int
    worst_bit_correctness: int
    exact_match_pixels: int
    total_pixels: int
    exact_match_fraction: float


@dataclass
class ComparisonResult:
    name: str
    python_path: Path
    fpga_path: Path
    output_plot_path: Path
    metrics: Metrics
    python_shape: tuple[int, int]
    fpga_shape: tuple[int, int]
    compared_shape: tuple[int, int]
    robust: bool
    kind: str


# -----------------------------------------------------------------------------
# Image and metric helpers
# -----------------------------------------------------------------------------
def load_grayscale_u8(path: Path) -> np.ndarray:
    """Load an image as 8-bit grayscale array."""
    img = Image.open(path).convert("L")
    arr = np.asarray(img, dtype=np.uint8)
    if arr.ndim != 2:
        raise ValueError(f"Expected grayscale 2D image at {path}, got shape {arr.shape}")
    return arr


def center_crop_to_common(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Center crop two arrays to their common minimum size."""
    target_h = min(a.shape[0], b.shape[0])
    target_w = min(a.shape[1], b.shape[1])

    def crop_center(x: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
        start_y = (x.shape[0] - out_h) // 2
        start_x = (x.shape[1] - out_w) // 2
        return x[start_y:start_y + out_h, start_x:start_x + out_w]

    return crop_center(a, target_h, target_w), crop_center(b, target_h, target_w)


def popcount8(x: np.ndarray) -> np.ndarray:
    """Vectorized popcount for uint8 array."""
    unpacked = np.unpackbits(x[..., None], axis=-1)
    return unpacked.sum(axis=-1).astype(np.uint8)


def compute_metrics(py_img: np.ndarray, fpga_img: np.ndarray) -> tuple[Metrics, np.ndarray]:
    """Compute scalar metrics and signed error image."""
    py_i16 = py_img.astype(np.int16)
    fpga_i16 = fpga_img.astype(np.int16)
    error = fpga_i16 - py_i16

    mse = float(np.mean(error.astype(np.float64) ** 2))
    min_error = int(error.min())
    max_error = int(error.max())
    mean_abs_error = float(np.mean(np.abs(error.astype(np.float64))))
    median_abs_error = float(np.median(np.abs(error.astype(np.float64))))
    median_error = float(np.median(error.astype(np.float64)))

    xor_vals = np.bitwise_xor(py_img, fpga_img)
    differing_bits = popcount8(xor_vals)
    bit_correctness = 8 - differing_bits.astype(np.int16)

    exact_match_pixels = int(np.count_nonzero(xor_vals == 0))
    total_pixels = int(py_img.size)
    exact_match_fraction = float(exact_match_pixels / total_pixels)

    metrics = Metrics(
        mse=mse,
        min_error=min_error,
        max_error=max_error,
        mean_abs_error=mean_abs_error,
        median_abs_error=median_abs_error,
        median_error=median_error,
        mean_bit_correctness=float(np.mean(bit_correctness.astype(np.float64))),
        median_bit_correctness=float(np.median(bit_correctness.astype(np.float64))),
        best_bit_correctness=int(bit_correctness.max()),
        worst_bit_correctness=int(bit_correctness.min()),
        exact_match_pixels=exact_match_pixels,
        total_pixels=total_pixels,
        exact_match_fraction=exact_match_fraction,
    )
    return metrics, error


def make_comparison_plot(
    py_img: np.ndarray,
    fpga_img: np.ndarray,
    error: np.ndarray,
    title: str,
    out_path: Path,
) -> None:
    """Create a single-row comparison image with separate color scales."""
    # Normalize difference symmetrically around zero for visibility.
    max_abs_err = int(np.max(np.abs(error)))
    if max_abs_err == 0:
        max_abs_err = 1

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    fig.suptitle(title, fontsize=12)

    im0 = axes[0].imshow(py_img, cmap="gray", vmin=0, vmax=255)
    axes[0].set_title("Python_Red")
    axes[0].set_xlabel("Column")
    axes[0].set_ylabel("Row")
    cbar0 = fig.colorbar(im0, ax=axes[0], fraction=0.046, pad=0.04)
    cbar0.set_label("Pixel value")

    im1 = axes[1].imshow(fpga_img, cmap="gray", vmin=0, vmax=255)
    axes[1].set_title("FPGA")
    axes[1].set_xlabel("Column")
    axes[1].set_ylabel("Row")
    cbar1 = fig.colorbar(im1, ax=axes[1], fraction=0.046, pad=0.04)
    cbar1.set_label("Pixel value")

    im2 = axes[2].imshow(error, cmap="seismic", vmin=-max_abs_err, vmax=max_abs_err)
    axes[2].set_title("Normalized Difference")
    axes[2].set_xlabel("Column")
    axes[2].set_ylabel("Row")
    cbar2 = fig.colorbar(im2, ax=axes[2], fraction=0.046, pad=0.04)
    cbar2.set_label("FPGA - Python_Red")

    for ax in axes:
        ax.set_aspect("equal")

    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def compare_one_pair(base_dir: Path, out_dir: Path, spec: dict) -> ComparisonResult:
    """Compare one Python_Red/FPGA image pair and save the plot."""
    python_path = base_dir / spec["python_rel"]
    fpga_path = base_dir / spec["fpga_rel"]

    if not python_path.exists():
        raise FileNotFoundError(f"Missing Python_Red image: {python_path}")
    if not fpga_path.exists():
        raise FileNotFoundError(f"Missing FPGA image: {fpga_path}")

    py_raw = load_grayscale_u8(python_path)
    fpga_raw = load_grayscale_u8(fpga_path)

    # First align sizes
    py_img, fpga_img = center_crop_to_common(py_raw, fpga_raw)

    # ---------------------------------------------------------------------
    # NEW: crop out 4-pixel border on all sides
    # ---------------------------------------------------------------------
    BORDER = 4
    if py_img.shape[0] <= 2 * BORDER or py_img.shape[1] <= 2 * BORDER:
        raise ValueError("Image too small for 4-pixel border crop")

    py_img = py_img[BORDER:-BORDER, BORDER:-BORDER]
    fpga_img = fpga_img[BORDER:-BORDER, BORDER:-BORDER]
    # ---------------------------------------------------------------------

    metrics, error = compute_metrics(py_img, fpga_img)

    out_plot_path = out_dir / f"{spec['name']}_comparison.png"
    title = f"{spec['name']} | Python_Red vs FPGA vs Difference"
    make_comparison_plot(py_img, fpga_img, error, title, out_plot_path)

    return ComparisonResult(
        name=spec["name"],
        python_path=python_path,
        fpga_path=fpga_path,
        output_plot_path=out_plot_path,
        metrics=metrics,
        python_shape=py_raw.shape,
        fpga_shape=fpga_raw.shape,
        compared_shape=py_img.shape,
        robust=bool(spec["robust"]),
        kind=str(spec["kind"]),
    )


# -----------------------------------------------------------------------------
# Reporting helpers
# -----------------------------------------------------------------------------
def format_result(result: ComparisonResult) -> str:
    """Format one result block for terminal and text file."""
    m = result.metrics
    lines = [
        f"=== {result.name} ===",
        f"kind: {result.kind}",
        f"robust: {result.robust}",
        f"python image : {result.python_path}",
        f"fpga image   : {result.fpga_path}",
        f"plot saved   : {result.output_plot_path}",
        f"python shape : {result.python_shape}",
        f"fpga shape   : {result.fpga_shape}",
        f"compared shape: {result.compared_shape}",
        f"MSE: {m.mse:.6f}",
        f"Mean absolute error: {m.mean_abs_error:.6f}",
        f"Median absolute error: {m.median_abs_error:.6f}",
        f"Median error (FPGA - Python_Red): {m.median_error:.6f}",
        f"Minimum error (FPGA - Python_Red): {m.min_error}",
        f"Maximum error (FPGA - Python_Red): {m.max_error}",
        f"Mean bit-correctness: {m.mean_bit_correctness:.6f} / 8",
        f"Median bit-correctness: {m.median_bit_correctness:.6f} / 8",
        f"Best bit-correctness: {m.best_bit_correctness} / 8",
        f"Worst bit-correctness: {m.worst_bit_correctness} / 8",
        f"Exact-match pixels: {m.exact_match_pixels} / {m.total_pixels}",
        f"Exact-match fraction: {m.exact_match_fraction:.6%}",
        "",
    ]
    return "\n".join(lines)


def write_report(results: Iterable[ComparisonResult], report_path: Path) -> None:
    """Write all result blocks to a text report."""
    blocks = [format_result(r) for r in results]
    report_path.write_text("\n".join(blocks), encoding="utf-8")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    default_base = Path.cwd()
    parser = argparse.ArgumentParser(description="Compare Python_Red PNG outputs to FPGA PNG outputs.")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=default_base,
        help="Repository/project root that contains the Python_Red/ and SystemVerilog_HDL_Red_Small/ folders.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("SystemVerilog_HDL_Red_Small/Bit_Manipulation/comparison_outputs"),
        help="Directory where plots and report are written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = args.base_dir.resolve()
    out_dir = (args.base_dir / args.out_dir).resolve() if not args.out_dir.is_absolute() else args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[ComparisonResult] = []
    for spec in PAIR_SPECS:
        result = compare_one_pair(base_dir, out_dir, spec)
        results.append(result)
        print(format_result(result), end="")

    report_path = out_dir / "comparison_metrics_report.txt"
    write_report(results, report_path)
    print(f"Saved text report: {report_path}")


if __name__ == "__main__":
    main()

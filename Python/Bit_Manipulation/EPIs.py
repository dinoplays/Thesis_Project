# EPIs.py
# Build horizontal and vertical EPIs as IMGB BYTES in memory.

import os
import re

from utils import imgb_parse_wh_payload, imbg_parse_payload, imgb_make

# Byte geometry (constants for 512/9 pipeline)
# u24 geometry
BYTES_PER_SAMPLE = 3
BYTES_PER_PIXEL_RGB = 9 # each pixel is 3 bytes/sample, 3 channels => 9 bytes per pixel

EPI_ROW_BYTES = 4608  # 512 pixels * 9 bytes/pixel
ROW_BYTES_X3 = 13824 # 512 pixels * 9 bytes/pixel * 3 rows (for horizontal EPIs) = 13824
ROW_BYTES_X9 = 41472 # 512 pixels * 9 bytes/pixel * 9 rows (U/V) = 41472

def natkey(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

def _read_imgb_blob(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()

def load_cross_crops(cross_dir: str):
    h_files = [f for f in os.listdir(cross_dir) if f.startswith("h_") and f.lower().endswith(".imgb")]
    v_files = [f for f in os.listdir(cross_dir) if f.startswith("v_") and f.lower().endswith(".imgb")]
    h_files.sort(key=natkey)
    v_files.sort(key=natkey)

    blob0 = _read_imgb_blob(os.path.join(cross_dir, h_files[0]))
    cross_w, cross_h, pay0 = imgb_parse_wh_payload(blob0)

    h_stack = [pay0]
    for f in h_files[1:]:
        blob = _read_imgb_blob(os.path.join(cross_dir, f))
        pay = imbg_parse_payload(blob)
        h_stack.append(pay)

    v_stack = []
    for f in v_files:
        blob = _read_imgb_blob(os.path.join(cross_dir, f))
        pay = imbg_parse_payload(blob)
        v_stack.append(pay)

    U = len(h_stack)
    V = len(v_stack)

    return h_stack, v_stack, (cross_h, cross_w, U, V)

def build_epis_imgb_in_memory(h_stack, v_stack, dims, y_rows, x_cols):
    cross_h, cross_w, U, V = dims

    # EPI dimensions:
    # Horizontal EPI: width = cross_w (512), height = U (9)
    # Vertical EPI:   width = cross_h (512), height = V (9)
    EPI_W_H = cross_w
    EPI_H_H = U
    EPI_W_V = cross_h
    EPI_H_V = V

    epi_h_imgb = []
    for y in y_rows:
        # out bytes = EPI_H_H * EPI_ROW_BYTES  -> U=9 => (EPI_ROW_BYTES * 9)
        out = bytearray(ROW_BYTES_X9)
        out_i = 0

        # row_base = y * EPI_ROW_BYTES
        # keep multiply here for simplicity; y ranges 0..511.
        row_base = y * EPI_ROW_BYTES

        for u in range(EPI_H_H):
            frame = h_stack[u]
            out[out_i:out_i + EPI_ROW_BYTES] = frame[row_base:row_base + EPI_ROW_BYTES]
            out_i += EPI_ROW_BYTES

        epi_h_imgb.append(
            imgb_make(W=EPI_W_H, H=EPI_H_H, C=3, dtype_code=4, payload=bytes(out))
        )

    epi_v_imgb = []
    for x in x_cols:
        # out bytes = V * cross_h * 9
        out = bytearray(ROW_BYTES_X9)
        out_i = 0

        col_off = (x << 3) + x  # x*9 (BYTES_PER_PIXEL_RGB)

        for v in range(EPI_H_V):
            frame = v_stack[v]
            src = col_off
            for _ in range(EPI_W_V):  # cross_h == 512
                out[out_i:out_i + BYTES_PER_PIXEL_RGB] = frame[src:src + BYTES_PER_PIXEL_RGB]
                out_i += BYTES_PER_PIXEL_RGB
                src += EPI_ROW_BYTES

        epi_v_imgb.append(
            imgb_make(W=EPI_W_V, H=EPI_H_V, C=3, dtype_code=4, payload=bytes(out))
        )

    return epi_h_imgb, epi_v_imgb

def load_cross_crops_and_build_epis_imgb(cross_dir: str):
    h_stack, v_stack, dims = load_cross_crops(cross_dir)
    cross_h, cross_w, _, _ = dims

    y_rows = range(cross_h)
    x_cols = range(cross_w)

    epi_h_imgb, epi_v_imgb = build_epis_imgb_in_memory(h_stack, v_stack, dims, y_rows, x_cols)
    return epi_h_imgb, epi_v_imgb
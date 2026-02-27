# EPIs.py
# Build horizontal and vertical EPIs as IMGB BYTES in memory.
#
# Assumptions for speed:
# - dtype_code = 4 (u24) storing biased signed Q12.12
# - channels C = 3 always (RGB)
# - all frames share identical W,H,C
#
# Output EPIs are also dtype_code=4 (u24), same biased Q12.12.

import os
import re

from utils import imgb_parse, imbg_parse_payload, imgb_make

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
    W, H, C, dtype_code, pay0 = imgb_parse(blob0)

    if dtype_code != 4 or C != 3:
        raise ValueError("EPIs expects cross outputs as dtype_code=4 (u24 Q12.12 biased), C=3")

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
    return h_stack, v_stack, (H, W, U, V)

def build_epis_imgb_in_memory(h_stack, v_stack, dims, y_rows, x_cols):
    H, W, U, V = dims

    # each pixel is 3 bytes/sample, 3 channels => 9 bytes per pixel
    bytes_per_pixel = 3 * 3
    row_bytes = W * bytes_per_pixel

    epi_h_imgb = []
    for y in y_rows:
        out = bytearray(U * row_bytes)
        out_i = 0
        row_base = y * row_bytes

        for u in range(U):
            frame = h_stack[u]
            out[out_i:out_i + row_bytes] = frame[row_base:row_base + row_bytes]
            out_i += row_bytes

        # width=W, height=U
        epi_h_imgb.append(imgb_make(W=W, H=U, C=3, dtype_code=4, payload=bytes(out)))

    epi_v_imgb = []
    for x in x_cols:
        out = bytearray(V * H * bytes_per_pixel)
        out_i = 0
        col_off = x * bytes_per_pixel

        for v in range(V):
            frame = v_stack[v]
            src = col_off
            for _ in range(H):
                out[out_i:out_i + bytes_per_pixel] = frame[src:src + bytes_per_pixel]
                out_i += bytes_per_pixel
                src += row_bytes

        # width=H, height=V
        epi_v_imgb.append(imgb_make(W=H, H=V, C=3, dtype_code=4, payload=bytes(out)))

    return epi_h_imgb, epi_v_imgb

def load_cross_crops_and_build_epis_imgb(cross_dir: str):
    h_stack, v_stack, dims = load_cross_crops(cross_dir)
    H, W, U, V = dims

    y_rows = range(H)
    x_cols = range(W)

    epi_h_imgb, epi_v_imgb = build_epis_imgb_in_memory(h_stack, v_stack, dims, y_rows, x_cols)
    return epi_h_imgb, epi_v_imgb
# utils.py
# Shared utilities (pure stdlib).

import os
import math

_MAGIC = b"IMGB"

Q_FRAC = 12
Q_SCALE = 4096  # 2^12 = 1 << 12

BIAS_INT = 8388608 # 1 << (11 + Q_FRAC)

U24_MAX = 16777215 # (1 << 24) - 1

# Project constants
WH_SHIFT = 9
WH_SIZE = 512  # 1 << WH_SHIFT
EPI_UV = 9     # U=V=9 in your pipeline


# ---------------- IMGB helpers ----------------

def _u32_le(b: bytes, off: int) -> int:
    return int.from_bytes(b[off:off + 4], "little", signed=False)

def _bytes_per_sample(dtype_code: int) -> int:
    if dtype_code == 1:
        return 1
    if dtype_code == 2:
        return 2
    if dtype_code == 3:
        return 4
    if dtype_code == 4:
        return 3  # u24

def imgb_parse(buf: bytes):
    W = _u32_le(buf, 4)
    H = _u32_le(buf, 8)
    C = buf[12]
    dtype_code = buf[13]
    payload = buf[16:]

    return int(W), int(H), int(C), int(dtype_code), payload

def imgb_parse_wh_payload(buf: bytes):
    W = _u32_le(buf, 4)
    H = _u32_le(buf, 8)
    payload = buf[16:]
    return int(W), int(H), payload

def imbg_parse_payload(buf: bytes):
    return buf[16:]

def imgb_make(W: int, H: int, C: int, dtype_code: int, payload: bytes) -> bytes:
    hdr = bytearray(16)
    hdr[0:4] = _MAGIC
    hdr[4:8] = int(W).to_bytes(4, "little", signed=False)
    hdr[8:12] = int(H).to_bytes(4, "little", signed=False)
    hdr[12] = int(C) & 0xFF
    hdr[13] = int(dtype_code) & 0xFF
    hdr[14:16] = (0).to_bytes(2, "little", signed=False)
    return bytes(hdr) + payload

def save_imgb(imgb_blob: bytes, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(imgb_blob)


# ---------------- u24 pack/unpack ----------------

def _u24_read(payload: bytes, byte_off: int) -> int:
    return payload[byte_off] | (payload[byte_off + 1] << 8) | (payload[byte_off + 2] << 16)

def _u24_write(out: bytearray, byte_off: int, v: int) -> None:
    v &= U24_MAX
    out[byte_off] = v & 0xFF
    out[byte_off + 1] = (v >> 8) & 0xFF
    out[byte_off + 2] = (v >> 16) & 0xFF
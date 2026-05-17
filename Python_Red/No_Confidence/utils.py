# utils.py
# Shared utilities (pure stdlib).
#
# IMGB header (16 bytes):
#   0..3   : b'IMGB'
#   4..7   : width  uint32 little-endian
#   8..11  : height uint32 little-endian
#   12     : channels uint8 (1/3/4)
#   13     : dtype_code uint8
#              1 = u8
#              2 = u16
#              3 = f32
#              4 = u24  (3 bytes/sample)  <-- used for biased signed Q12.12 everywhere after cross
#   14..15 : reserved uint16 (0)
#
# For dtype_code=4, payload is u24 little-endian per sample (3 bytes).
# We interpret those u24 integers as "biased signed Q12.12":
#   signed_q12_12_int = u24 - BIAS_INT
#   float_value       = signed_q12_12_int / 4096.0
#
# Bias:
#   BIAS = 2048.0
#   BIAS_INT = 2048 * 4096 = 8388608

import os
import math

_MAGIC = b"IMGB"

Q_FRAC = 12
Q_SCALE = 1 << Q_FRAC

BIAS = 2048.0
BIAS_INT = int(BIAS * Q_SCALE)  # 8388608

U24_MAX = (1 << 24) - 1


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
    raise ValueError(f"Unsupported dtype_code: {dtype_code}")

def imgb_parse(buf: bytes):
    if len(buf) < 16:
        raise ValueError("IMGB buffer too small")
    if buf[0:4] != _MAGIC:
        raise ValueError("Bad IMGB magic")

    W = _u32_le(buf, 4)
    H = _u32_le(buf, 8)
    C = buf[12]
    dtype_code = buf[13]
    payload = buf[16:]

    bps = _bytes_per_sample(dtype_code)
    expected = int(W) * int(H) * int(C) * bps
    if len(payload) != expected:
        raise ValueError(f"IMGB payload size mismatch: got {len(payload)}, expected {expected}")

    return int(W), int(H), int(C), int(dtype_code), payload

def imbg_parse_payload(buf: bytes):
    return buf[16:]

def imgb_make(W: int, H: int, C: int, dtype_code: int, payload: bytes) -> bytes:
    bps = _bytes_per_sample(dtype_code)
    expected = int(W) * int(H) * int(C) * bps
    if len(payload) != expected:
        raise ValueError(f"Payload size mismatch: got {len(payload)}, expected {expected}")

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
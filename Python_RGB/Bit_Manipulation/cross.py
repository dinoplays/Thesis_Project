# cross.py
# Convert cross_raw_data frames from IMGB dtype_code=1 (u8 RGB)
# into IMGB dtype_code=4 (u24), storing biased signed Q12.12 values.
#
# Bit-manipulative architecture version:
#   - No pre-EPI low-pass filter.
#   - u8 -> Q12.12 conversion uses left shifts.
#   - Output remains RGB C=3 so the RGB EPI/confidence/disparity pipeline
#     can compute R/G/B channels separately.
#
# INPUT:
#   cross_raw_data frames as IMGB dtype_code=1, C=3
#
# OUTPUT:
#   IMGB dtype_code=4, C=3, biased signed Q12.12
#
# NO numpy, NO imageio. Pure stdlib.

import os
import re

from utils import (
    Q_FRAC,
    BIAS_INT,
    U24_MAX,
    imgb_make,
    imgb_parse,
    save_imgb,
)


# W = H = 512 in your current RGB pipeline.
WH_SHIFT = 9
WH_SIZE = 1 << WH_SHIFT


# ----------------------------------------------------------
# Filesystem helpers
# ----------------------------------------------------------

def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


# ----------------------------------------------------------
# u8 RGB -> biased signed Q12.12 u24 conversion
# ----------------------------------------------------------

def _u8_rgb_to_q12_12_u24_payload(raw_u8_rgb: bytes, W: int, H: int) -> bytes:
    """
    Convert raw interleaved u8 RGB payload into biased signed Q12.12 u24 payload.

    Mapping:
        q12_12 = u8 << Q_FRAC
        stored = q12_12 + BIAS_INT

    Time complexity:
        One pass over W * H * 3 channel samples, so O(W * H).
    """

    expected = W * H * 3

    if len(raw_u8_rgb) != expected:
        raise ValueError(
            f"Input RGB payload size mismatch: got {len(raw_u8_rgb)}, expected {expected}"
        )

    out = bytearray(W * H * 3 * 3)
    o = 0

    for b in raw_u8_rgb:
        v_q = int(b) << Q_FRAC
        u = v_q + BIAS_INT

        if u < 0:
            u = 0
        elif u > U24_MAX:
            u = U24_MAX

        out[o] = u & 0xFF
        out[o + 1] = (u >> 8) & 0xFF
        out[o + 2] = (u >> 16) & 0xFF

        o += 3

    return bytes(out)


# ----------------------------------------------------------
# Folder conversion
# ----------------------------------------------------------

def convert_cross_u8_to_q12_12(in_dir: str, out_dir: str) -> str:
    """
    Convert all .imgb files in in_dir from u8 RGB to biased signed Q12.12 u24 RGB.

    No filtering, blurring, convolution, or pixel modification is performed.
    This preserves the standard RGB architecture where filtering happens after
    disparity fusion, not before EPI construction.
    """

    os.makedirs(out_dir, exist_ok=True)

    names = [n for n in os.listdir(in_dir) if n.lower().endswith(".imgb")]
    names.sort(key=_natural_key)

    for name in names:
        src = os.path.join(in_dir, name)
        dst = os.path.join(out_dir, name)

        with open(src, "rb") as f:
            blob = f.read()

        W, H, C, dtype_code, payload = imgb_parse(blob)

        if dtype_code != 1 or C != 3:
            raise ValueError(
                f"cross expects input u8 RGB IMGB. "
                f"Got dtype_code={dtype_code}, C={C} in {src}"
            )

        out_payload = _u8_rgb_to_q12_12_u24_payload(payload, W, H)
        out_blob = imgb_make(W=W, H=H, C=3, dtype_code=4, payload=out_payload)

        save_imgb(out_blob, dst)

    return out_dir

# disparity.py
# FPGA-aligned disparity and fusion from precomputed EPI derivatives.
#
# The estimator mirrors the current HDL disparity_estimator more closely than
# the earlier Python 5x5 least-squares version:
#   sum_uv = Σ_a L_u(a) * L_s(a)
#   sum_uu = Σ_a L_u(a) * L_u(a)
#   ratio  = sum_uv / sum_uu
#   output = 1 + ratio
#
# Derivatives are decoded back to the FPGA's signed Q8.2 integer domain. Output
# disparity is quantised to signed Q8.8, then stored as a Q12.12 IMGB value so
# existing Python visualisation/conversion code still works.

from utils import (
    imgb_parse,
    imgb_make,
    BIAS_INT,
    Q_SCALE,
    U24_MAX,
)

Q8_2_TO_Q12_SHIFT = 10
Q8_8_TO_Q12_SHIFT = 4
Q8_2_TO_Q12 = 1 << Q8_2_TO_Q12_SHIFT
Q8_8_TO_Q12 = 1 << Q8_8_TO_Q12_SHIFT


def _u24_read(p: bytes, o: int) -> int:
    return p[o] | (p[o + 1] << 8) | (p[o + 2] << 16)


def _u24_write(out: bytearray, o: int, u: int) -> None:
    u &= U24_MAX
    out[o] = u & 0xFF
    out[o + 1] = (u >> 8) & 0xFF
    out[o + 2] = (u >> 16) & 0xFF


def _bias_q(q: int) -> int:
    u = int(q) + BIAS_INT

    if u < 0:
        return 0

    if u > U24_MAX:
        return U24_MAX

    return u


def _div_toward_zero(num: int, den: int) -> int:
    if den == 0:
        return 0

    if num >= 0:
        return num // den

    return -((-num) // den)


def _q12_to_q8_2(q12: int) -> int:
    return _div_toward_zero(q12, Q8_2_TO_Q12)


def _q12_to_q8_8(q12: int) -> int:
    return _div_toward_zero(q12, Q8_8_TO_Q12)


def _sat_s16(x: int) -> int:
    if x > 32767:
        return 32767

    if x < -32768:
        return -32768

    return int(x)


def _sat_u10(x: int) -> int:
    if x < 0:
        return 0

    if x > 1023:
        return 1023

    return int(x)


def _read_derivative_q8_2(payload: bytes, W: int, a: int, x: int) -> int:
    q12 = _u24_read(payload, ((a * W) + x) * 3) - BIAS_INT
    return _q12_to_q8_2(q12)


def _write_q8_8_disparity(out: bytearray, idx: int, q8_8: int) -> None:
    _u24_write(out, idx * 3, _bias_q(_sat_s16(q8_8) << Q8_8_TO_Q12_SHIFT))


def _estimate_disparity_q8_8(angular_vals_q8_2, spatial_vals_q8_2) -> int:
    sum_uv = 0
    sum_uu = 0

    for a_val, s_val in zip(angular_vals_q8_2, spatial_vals_q8_2):
        sum_uv += int(a_val) * int(s_val)
        sum_uu += int(a_val) * int(a_val)

    if sum_uu == 0:
        return 0

    # FPGA divider computes abs(sum_uv) * 256 / sum_uu, restores sign, then
    # adds +1.0 in Q8.8. Integer division truncates toward zero.
    ratio_mag_q8_8 = (abs(sum_uv) << 8) // sum_uu

    if sum_uv < 0:
        ratio_q8_8 = -ratio_mag_q8_8
    else:
        ratio_q8_8 = ratio_mag_q8_8

    return _sat_s16(ratio_q8_8 + 256)


def compute_horizontal_from_epis(
    epi_h_imgb,
    dL_du_h,
    dL_ds_h,
    *,
    d=1.0,
    ds=1.0,
    du=1.0,
    win=5,
) -> bytes:
    """
    FPGA-aligned horizontal disparity.

    d/ds/du/win are accepted for API compatibility. The current FPGA assumes
    unit geometry and uses a seven-sample angular sum, so win is intentionally
    ignored here.
    """

    H = len(dL_du_h)
    if H == 0:
        raise ValueError("Empty horizontal derivative list")

    W, A, C, dtype_code, _ = imgb_parse(dL_du_h[0])
    if dtype_code != 4 or C != 1:
        raise ValueError("dL_du_h must contain single-channel Q12.12 IMGB blobs")

    payload = bytearray(W * H * 3)

    for y in range(H):
        Wd, Ad, Cd, dtd, du_pay = imgb_parse(dL_du_h[y])
        Ws, As, Cs, dts, ds_pay = imgb_parse(dL_ds_h[y])

        if Wd != W or Ad != A or Cd != 1 or dtd != 4:
            raise ValueError("dL_du_h shape mismatch")

        if Ws != W or As != A or Cs != 1 or dts != 4:
            raise ValueError("dL_ds_h shape mismatch")

        for x in range(W):
            angular = []
            spatial = []

            for a in range(1, A - 1):
                angular.append(_read_derivative_q8_2(du_pay, W, a, x))
                spatial.append(_read_derivative_q8_2(ds_pay, W, a, x))

            q8_8 = _estimate_disparity_q8_8(angular, spatial)
            _write_q8_8_disparity(payload, y * W + x, q8_8)

    return imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(payload))


def compute_vertical_from_epis(
    epi_v_imgb,
    dL_dv_v,
    dL_dt_v,
    *,
    d=1.0,
    dt=1.0,
    dv=1.0,
    win=5,
) -> bytes:
    """
    FPGA-aligned vertical disparity. API parameters are retained for
    compatibility; the FPGA-style estimator uses unit geometry and seven angular
    derivative samples.
    """

    W_img = len(dL_dv_v)
    if W_img == 0:
        raise ValueError("Empty vertical derivative list")

    H, A, C, dtype_code, _ = imgb_parse(dL_dv_v[0])
    if dtype_code != 4 or C != 1:
        raise ValueError("dL_dv_v must contain single-channel Q12.12 IMGB blobs")

    payload = bytearray(W_img * H * 3)

    for x_img in range(W_img):
        Wd, Ad, Cd, dtd, dv_pay = imgb_parse(dL_dv_v[x_img])
        Wt, At, Ct, dtt, dt_pay = imgb_parse(dL_dt_v[x_img])

        if Wd != H or Ad != A or Cd != 1 or dtd != 4:
            raise ValueError("dL_dv_v shape mismatch")

        if Wt != H or At != A or Ct != 1 or dtt != 4:
            raise ValueError("dL_dt_v shape mismatch")

        for y in range(H):
            angular = []
            spatial = []

            for a in range(1, A - 1):
                angular.append(_read_derivative_q8_2(dv_pay, H, a, y))
                spatial.append(_read_derivative_q8_2(dt_pay, H, a, y))

            q8_8 = _estimate_disparity_q8_8(angular, spatial)
            _write_q8_8_disparity(payload, y * W_img + x_img, q8_8)

    return imgb_make(W=W_img, H=H, C=1, dtype_code=4, payload=bytes(payload))


def _decode_single_channel_q12(imgb_blob: bytes, label: str):
    W, H, C, dtype_code, payload = imgb_parse(imgb_blob)

    if dtype_code != 4 or C != 1:
        raise ValueError(f"{label} expects dtype_code=4, C=1")

    vals = [0] * (W * H)
    for i in range(W * H):
        vals[i] = _u24_read(payload, i * 3) - BIAS_INT

    return W, H, vals


def fuse_disparity_precision(
    Z_h_imgb,
    Z_v_imgb,
    C_h_imgb,
    C_v_imgb,
    *,
    temperature=1,
    floor=0,
    cap=None,
    eps=0,
):
    """
    FPGA-aligned linear confidence fusion.

    The signature is kept compatible with the older Python path, but the FPGA
    does not use confidence^temperature, floor/cap sharpening, or epsilon in the
    final fusion. It computes:

        Z = (Z_h*C_h + Z_v*C_v) / (C_h + C_v)

    in Q8.8/Q8.2 fixed-point terms.
    """

    W_h, H_h, zh_q12 = _decode_single_channel_q12(Z_h_imgb, "Z_h")
    W_v, H_v, zv_q12 = _decode_single_channel_q12(Z_v_imgb, "Z_v")
    W_ch, H_ch, ch_q12 = _decode_single_channel_q12(C_h_imgb, "C_h")
    W_cv, H_cv, cv_q12 = _decode_single_channel_q12(C_v_imgb, "C_v")

    if not (W_h == W_v == W_ch == W_cv and H_h == H_v == H_ch == H_cv):
        raise ValueError("Shape mismatch in disparity fusion inputs")

    payload = bytearray(W_h * H_h * 3)

    for i in range(W_h * H_h):
        zh = _q12_to_q8_8(zh_q12[i])
        zv = _q12_to_q8_8(zv_q12[i])
        ch = _sat_u10(_q12_to_q8_2(ch_q12[i]))
        cv = _sat_u10(_q12_to_q8_2(cv_q12[i]))

        denom = ch + cv

        if denom == 0:
            fused = 0
        else:
            numerator = (zh * ch) + (zv * cv)
            fused_mag = abs(numerator) // denom
            if numerator < 0:
                fused = -fused_mag
            else:
                fused = fused_mag
            fused = _sat_s16(fused)

        _write_q8_8_disparity(payload, i, fused)

    return imgb_make(W=W_h, H=H_h, C=1, dtype_code=4, payload=bytes(payload))


# -----------------------------------------------------------------------------
# RGB disparity fusion
# -----------------------------------------------------------------------------

def fuse_rgb_disparity_precision(
    Z_h_red_imgb: bytes,
    Z_v_red_imgb: bytes,
    C_h_red_imgb: bytes,
    C_v_red_imgb: bytes,
    Z_h_green_imgb: bytes,
    Z_v_green_imgb: bytes,
    C_h_green_imgb: bytes,
    C_v_green_imgb: bytes,
    Z_h_blue_imgb: bytes,
    Z_v_blue_imgb: bytes,
    C_h_blue_imgb: bytes,
    C_v_blue_imgb: bytes,
    *,
    temperature=1,
    floor=0,
    cap=None,
    eps=0,
) -> bytes:
    """
    FPGA-style RGB confidence-weighted fusion over all six estimates.

    This extends the red-channel hardware-style fusion to RGB:
        Z = sum(Z_i * C_i) / sum(C_i)

    Each disparity is interpreted in Q8.8 and each confidence in Q8.2, matching
    the reduced-precision FPGA-oriented representation used by the red
    bit-manipulative implementation. temperature/floor/cap/eps are accepted for
    API compatibility but intentionally ignored because the FPGA-style fusion is
    linear in confidence.
    """

    inputs = [
        (Z_h_red_imgb, C_h_red_imgb),
        (Z_v_red_imgb, C_v_red_imgb),
        (Z_h_green_imgb, C_h_green_imgb),
        (Z_v_green_imgb, C_v_green_imgb),
        (Z_h_blue_imgb, C_h_blue_imgb),
        (Z_v_blue_imgb, C_v_blue_imgb),
    ]

    decoded = []
    W0 = H0 = None

    for z_blob, c_blob in inputs:
        Wz, Hz, z_vals = _decode_single_channel_q12(z_blob, "Z_rgb")
        Wc, Hc, c_vals = _decode_single_channel_q12(c_blob, "C_rgb")
        if Wz != Wc or Hz != Hc:
            raise ValueError("RGB fusion input shape mismatch")
        if W0 is None:
            W0, H0 = Wz, Hz
        elif Wz != W0 or Hz != H0:
            raise ValueError("RGB fusion input shape mismatch")
        decoded.append((z_vals, c_vals))

    payload = bytearray(W0 * H0 * 3)

    for i in range(W0 * H0):
        numerator = 0
        denom = 0

        for z_q12, c_q12 in decoded:
            z = _q12_to_q8_8(z_q12[i])
            c = _sat_u10(_q12_to_q8_2(c_q12[i]))
            numerator += z * c
            denom += c

        if denom == 0:
            fused = 0
        else:
            fused_mag = abs(numerator) // denom
            if numerator < 0:
                fused = -fused_mag
            else:
                fused = fused_mag
            fused = _sat_s16(fused)

        _write_q8_8_disparity(payload, i, fused)

    return imgb_make(W=W0, H=H0, C=1, dtype_code=4, payload=bytes(payload))

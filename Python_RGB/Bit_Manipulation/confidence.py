# confidence.py
# FPGA-aligned confidence and derivative generation from precomputed EPIs.
#
# This version follows the HDL confidence_computer stage more closely than the
# earlier canonical/least-squares Python implementation:
#   - 3x3 weighted derivative kernels in the spatial/angular EPI plane
#   - seven valid angular centres for a 9-view cross EPI, rows 1..7
#   - confidence from max/min gradient-magnitude approximation
#   - confidence stored as Q8.2-equivalent values in biased Q12.12 IMGB
#
# The paper motivates 2D gradient operators on s,u and t,v EPI slices, gives a
# Sobel-like 3x3 derivative kernel as a simple noise-robust derivative estimate,
# and uses gradient magnitude as confidence. The FPGA keeps the same structure,
# but approximates the Euclidean magnitude for hardware efficiency.

from utils import (
    imgb_parse,
    imbg_parse_payload,
    imgb_make,
    BIAS_INT,
    Q_SCALE,
    U24_MAX,
)

# The FPGA derivative values are signed Q8.2. In the Python IMGB files we store
# the same real value in Q12.12, so q12 = q8_2 * 2^(12-2) = q8_2 * 1024.
Q8_2_TO_Q12_SHIFT = 10
Q8_2_TO_Q12 = 1 << Q8_2_TO_Q12_SHIFT


# -----------------------------------------------------------------------------
# u24 helpers
# -----------------------------------------------------------------------------

def _u24_read(payload: bytes, byte_off: int) -> int:
    return payload[byte_off] | (payload[byte_off + 1] << 8) | (payload[byte_off + 2] << 16)


def _u24_write(out: bytearray, byte_off: int, u: int) -> None:
    u &= U24_MAX
    out[byte_off] = u & 0xFF
    out[byte_off + 1] = (u >> 8) & 0xFF
    out[byte_off + 2] = (u >> 16) & 0xFF


def _bias_from_q12_12(q: int) -> int:
    u = int(q) + BIAS_INT

    if u < 0:
        return 0

    if u > U24_MAX:
        return U24_MAX

    return u


def _q12_to_u8_sample(q12: int) -> int:
    """
    Convert the cross-data Q12.12 stored image sample back to the 8-bit sample
    used by the FPGA EPI stream.
    """

    if q12 >= 0:
        v = q12 // Q_SCALE
    else:
        v = -((-q12) // Q_SCALE)

    if v < 0:
        return 0

    if v > 255:
        return 255

    return int(v)


def _read_epi_u8(payload: bytes, sample_idx_rgb: int, ch: int) -> int:
    q12 = _u24_read(payload, sample_idx_rgb + ch * 3) - BIAS_INT
    return _q12_to_u8_sample(q12)


def _sat_u10(x: int) -> int:
    if x < 0:
        return 0

    if x > 1023:
        return 1023

    return int(x)


def _sat_s11(x: int) -> int:
    if x > 1023:
        return 1023

    if x < -1024:
        return -1024

    return int(x)


def _abs_i(x: int) -> int:
    if x < 0:
        return -x

    return x


def _grad_mag_approx_q8_2(spatial_q8_2: int, angular_q8_2: int) -> int:
    abs_spatial = _abs_i(spatial_q8_2)
    abs_angular = _abs_i(angular_q8_2)

    if abs_spatial >= abs_angular:
        max_abs = abs_spatial
        min_abs = abs_angular
    else:
        max_abs = abs_angular
        min_abs = abs_spatial

    # Bit-manipulative version: max + (min >> 2) + (min >> 3).
    return max_abs + (min_abs >> 2) + (min_abs >> 3)


def _weighted_angular_q8_2(tl: int, tm: int, tr: int, bl: int, bm: int, br: int) -> int:
    # Bit-manipulative FPGA kernel:
    #   (tl - bl) + 2*(tm - bm) + (tr - br)
    # Coefficient 2 is implemented with a left shift, matching the bit-oriented
    # HDL version.
    diff_left = tl - bl
    diff_mid = tm - bm
    diff_right = tr - br
    return _sat_s11(diff_left + (diff_mid << 1) + diff_right)


def _weighted_spatial_q8_2(lt: int, lm: int, lb: int, rt: int, rm: int, rb: int) -> int:
    # Bit-manipulative FPGA kernel:
    #   (lt - rt) + 2*(lm - rm) + (lb - rb)
    diff_top = lt - rt
    diff_mid = lm - rm
    diff_bot = lb - rb
    return _sat_s11(diff_top + (diff_mid << 1) + diff_bot)


def _make_zero_derivative_blob(W: int, A: int) -> bytes:
    payload = bytearray(W * A * 3)
    for i in range(W * A):
        _u24_write(payload, i * 3, BIAS_INT)
    return imgb_make(W=W, H=A, C=1, dtype_code=4, payload=bytes(payload))


def _write_derivative_q8_2(out: bytearray, W: int, a: int, x: int, q8_2: int) -> None:
    _u24_write(out, ((a * W) + x) * 3, _bias_from_q12_12(q8_2 << Q8_2_TO_Q12_SHIFT))


def compute_from_epis_with_diffs(epi_h_imgb, epi_v_imgb, channel=None):
    ch = 0 if channel is None else int(channel)

    H_img = len(epi_h_imgb)
    W_img = len(epi_v_imgb)

    if H_img == 0 or W_img == 0:
        raise ValueError("Empty EPI lists")

    W_h, A_h, C_hc, dt_h, _ = imgb_parse(epi_h_imgb[0])
    W_v, A_v, C_vc, dt_v, _ = imgb_parse(epi_v_imgb[0])

    if dt_h != 4 or dt_v != 4:
        raise ValueError("EPIs must be dtype_code=4")

    if C_hc != 3 or C_vc != 3:
        raise ValueError("EPIs must be RGB")

    W = int(W_h)
    H = int(H_img)
    A = int(A_h)

    if int(W_img) != W:
        raise ValueError("epi_v_imgb length must equal image width")

    if int(W_v) != H:
        raise ValueError("vertical EPI width must equal image height")

    if int(A_v) != A:
        raise ValueError("horizontal and vertical angular counts must match")

    if A < 3:
        zero_h = [_make_zero_derivative_blob(W, A) for _ in range(H)]
        zero_v = [_make_zero_derivative_blob(H, A) for _ in range(W)]
        empty_payload_h = bytearray(W * H * 3)
        empty_payload_v = bytearray(W * H * 3)
        for i in range(W * H):
            _u24_write(empty_payload_h, i * 3, BIAS_INT)
            _u24_write(empty_payload_v, i * 3, BIAS_INT)
        return (
            imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(empty_payload_h)),
            imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(empty_payload_v)),
            zero_h,
            zero_v,
            zero_h,
            zero_v,
        )

    bytes_per_pixel_rgb = 9

    # ------------------------------------------------------------------
    # Horizontal EPI derivatives and confidence
    # ------------------------------------------------------------------
    C_h_q8_2 = [0] * (H * W)
    dL_du_h = []
    dL_ds_h = []

    for y in range(H):
        pay = imbg_parse_payload(epi_h_imgb[y])
        out_du = bytearray(A * W * 3)
        out_ds = bytearray(A * W * 3)

        for i in range(A * W):
            _u24_write(out_du, i * 3, BIAS_INT)
            _u24_write(out_ds, i * 3, BIAS_INT)

        for x in range(1, W - 1):
            mag_sum = 0

            for a in range(1, A - 1):
                # Read 3x3 EPI window as 8-bit values, matching the FPGA input.
                top_left  = _read_epi_u8(pay, (((a - 1) * W + (x - 1)) * bytes_per_pixel_rgb), ch)
                top_mid   = _read_epi_u8(pay, (((a - 1) * W + x)       * bytes_per_pixel_rgb), ch)
                top_right = _read_epi_u8(pay, (((a - 1) * W + (x + 1)) * bytes_per_pixel_rgb), ch)

                mid_left  = _read_epi_u8(pay, ((a * W + (x - 1)) * bytes_per_pixel_rgb), ch)
                mid_right = _read_epi_u8(pay, ((a * W + (x + 1)) * bytes_per_pixel_rgb), ch)

                bot_left  = _read_epi_u8(pay, (((a + 1) * W + (x - 1)) * bytes_per_pixel_rgb), ch)
                bot_mid   = _read_epi_u8(pay, (((a + 1) * W + x)       * bytes_per_pixel_rgb), ch)
                bot_right = _read_epi_u8(pay, (((a + 1) * W + (x + 1)) * bytes_per_pixel_rgb), ch)

                angular = _weighted_angular_q8_2(top_left, top_mid, top_right, bot_left, bot_mid, bot_right)
                spatial = _weighted_spatial_q8_2(top_left, mid_left, bot_left, top_right, mid_right, bot_right)

                _write_derivative_q8_2(out_du, W, a, x, angular)
                _write_derivative_q8_2(out_ds, W, a, x, spatial)

                mag_sum += _grad_mag_approx_q8_2(spatial, angular)

            C_h_q8_2[y * W + x] = _sat_u10(mag_sum // (A - 2))

        dL_du_h.append(imgb_make(W=W, H=A, C=1, dtype_code=4, payload=bytes(out_du)))
        dL_ds_h.append(imgb_make(W=W, H=A, C=1, dtype_code=4, payload=bytes(out_ds)))

    # ------------------------------------------------------------------
    # Vertical EPI derivatives and confidence
    # ------------------------------------------------------------------
    C_v_q8_2 = [0] * (H * W)
    dL_dv_v = []
    dL_dt_v = []

    for x_img in range(W):
        pay = imbg_parse_payload(epi_v_imgb[x_img])
        out_dv = bytearray(A * H * 3)
        out_dt = bytearray(A * H * 3)

        for i in range(A * H):
            _u24_write(out_dv, i * 3, BIAS_INT)
            _u24_write(out_dt, i * 3, BIAS_INT)

        for y in range(1, H - 1):
            mag_sum = 0

            for a in range(1, A - 1):
                top_left  = _read_epi_u8(pay, (((a - 1) * H + (y - 1)) * bytes_per_pixel_rgb), ch)
                top_mid   = _read_epi_u8(pay, (((a - 1) * H + y)       * bytes_per_pixel_rgb), ch)
                top_right = _read_epi_u8(pay, (((a - 1) * H + (y + 1)) * bytes_per_pixel_rgb), ch)

                mid_left  = _read_epi_u8(pay, ((a * H + (y - 1)) * bytes_per_pixel_rgb), ch)
                mid_right = _read_epi_u8(pay, ((a * H + (y + 1)) * bytes_per_pixel_rgb), ch)

                bot_left  = _read_epi_u8(pay, (((a + 1) * H + (y - 1)) * bytes_per_pixel_rgb), ch)
                bot_mid   = _read_epi_u8(pay, (((a + 1) * H + y)       * bytes_per_pixel_rgb), ch)
                bot_right = _read_epi_u8(pay, (((a + 1) * H + (y + 1)) * bytes_per_pixel_rgb), ch)

                angular = _weighted_angular_q8_2(top_left, top_mid, top_right, bot_left, bot_mid, bot_right)
                spatial = _weighted_spatial_q8_2(top_left, mid_left, bot_left, top_right, mid_right, bot_right)

                _write_derivative_q8_2(out_dv, H, a, y, angular)
                _write_derivative_q8_2(out_dt, H, a, y, spatial)

                mag_sum += _grad_mag_approx_q8_2(spatial, angular)

            C_v_q8_2[y * W + x_img] = _sat_u10(mag_sum // (A - 2))

        dL_dv_v.append(imgb_make(W=H, H=A, C=1, dtype_code=4, payload=bytes(out_dv)))
        dL_dt_v.append(imgb_make(W=H, H=A, C=1, dtype_code=4, payload=bytes(out_dt)))

    payload_h = bytearray(W * H * 3)
    payload_v = bytearray(W * H * 3)

    for idx, val in enumerate(C_h_q8_2):
        _u24_write(payload_h, idx * 3, _bias_from_q12_12(_sat_u10(val) << Q8_2_TO_Q12_SHIFT))

    for idx, val in enumerate(C_v_q8_2):
        _u24_write(payload_v, idx * 3, _bias_from_q12_12(_sat_u10(val) << Q8_2_TO_Q12_SHIFT))

    C_h_imgb = imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(payload_h))
    C_v_imgb = imgb_make(W=W, H=H, C=1, dtype_code=4, payload=bytes(payload_v))

    return C_h_imgb, C_v_imgb, dL_du_h, dL_dv_v, dL_ds_h, dL_dt_v


def _decode_q8_2_image(imgb_blob: bytes):
    W, H, C, dtype_code, payload = imgb_parse(imgb_blob)

    if dtype_code != 4 or C != 1:
        raise ValueError("Expected single-channel Q12.12 IMGB confidence image")

    vals = [0] * (W * H)
    for i in range(W * H):
        q12 = _u24_read(payload, i * 3) - BIAS_INT
        if q12 >= 0:
            vals[i] = q12 // Q8_2_TO_Q12
        else:
            vals[i] = -((-q12) // Q8_2_TO_Q12)

    return W, H, vals


def fuse_avg(C_h_imgb, C_v_imgb):
    """
    FPGA-aligned confidence consolidation.

    The name is retained for compatibility with the existing pipeline, but this
    now matches fused_aligned_output more closely: confidence is the saturated
    sum C_h + C_v in unsigned Q8.2, not an arithmetic average.
    """

    W_h, H_h, ch = _decode_q8_2_image(C_h_imgb)
    W_v, H_v, cv = _decode_q8_2_image(C_v_imgb)

    if W_h != W_v or H_h != H_v:
        raise ValueError("Confidence image shape mismatch")

    payload = bytearray(W_h * H_h * 3)

    for i in range(W_h * H_h):
        fused = ch[i] + cv[i]
        if fused > 1023:
            fused = 1023
        _u24_write(payload, i * 3, _bias_from_q12_12(fused << Q8_2_TO_Q12_SHIFT))

    return imgb_make(W=W_h, H=H_h, C=1, dtype_code=4, payload=bytes(payload))


# -----------------------------------------------------------------------------
# RGB confidence helpers
# -----------------------------------------------------------------------------

def fuse_avg_three(C_a_imgb: bytes, C_b_imgb: bytes, C_c_imgb: bytes) -> bytes:
    """
    Average three already-fused per-channel confidence maps.

    In the RGB pipeline each channel first produces C_avg_channel using
    fuse_avg(C_h, C_v). This helper combines the red, green and blue confidence
    maps into one compatibility/reliability map for visualisation and region
    filling. The arithmetic stays in the FPGA/bit-manipulative Q8.2-equivalent
    representation, then is stored back into Q12.12 IMGB form.
    """

    W_a, H_a, a_vals = _decode_q8_2_image(C_a_imgb)
    W_b, H_b, b_vals = _decode_q8_2_image(C_b_imgb)
    W_c, H_c, c_vals = _decode_q8_2_image(C_c_imgb)

    if not (W_a == W_b == W_c and H_a == H_b == H_c):
        raise ValueError("fuse_avg_three expects same-sized confidence maps")

    payload = bytearray(W_a * H_a * 3)

    for i in range(W_a * H_a):
        # rounded integer average of three Q8.2-domain confidence values
        total = a_vals[i] + b_vals[i] + c_vals[i]
        avg = (total + 1) // 3
        if avg > 1023:
            avg = 1023
        _u24_write(payload, i * 3, _bias_from_q12_12(avg << Q8_2_TO_Q12_SHIFT))

    return imgb_make(W=W_a, H=H_a, C=1, dtype_code=4, payload=bytes(payload))

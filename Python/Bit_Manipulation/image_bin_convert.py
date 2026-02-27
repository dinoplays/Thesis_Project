# img_bin_convert.py
# Convert all images in a folder to a simple raw binary format (and optionally back).
# Format:
#   bytes 0..3   : b'IMGB'
#   bytes 4..7   : width  (uint32, little-endian)
#   bytes 8..11  : height (uint32, little-endian)
#   byte  12     : channels (uint8)  [1,3,4]
#   byte  13     : dtype_code (uint8)  [1=u8, 2=u16]
#   bytes 14..15 : reserved (uint16) (0)
#   bytes 16..   : raw pixel bytes, row-major, interleaved channels

import os
import imageio.v3 as iio

MAGIC = b"IMGB"

DTYPE_TO_CODE = {
    "uint8": 1,
    "uint16": 2,
}

CODE_TO_DTYPE = {
    1: "uint8",
    2: "uint16",
}

def _u32_le(n: int) -> bytes:
    return int(n).to_bytes(4, "little", signed=False)

def _u16_le(n: int) -> bytes:
    return int(n).to_bytes(2, "little", signed=False)

def _read_u32_le(b: bytes, off: int) -> int:
    return int.from_bytes(b[off:off+4], "little", signed=False)

def _write_imgb(path_out: str, img) -> None:
    # img is typically a numpy ndarray from imageio; we treat it generically.
    H = int(img.shape[0])
    W = int(img.shape[1])
    if len(img.shape) == 2:
        C = 1
    else:
        C = int(img.shape[2])

    # dtype name like 'uint8' / 'uint16'
    dtype_name = str(img.dtype)
    dtype_code = DTYPE_TO_CODE.get(dtype_name)
    if dtype_code is None:
        raise ValueError(f"Unsupported dtype {dtype_name} for {path_out}. Use uint8/uint16 images.")

    header = bytearray()
    header += MAGIC
    header += _u32_le(W)
    header += _u32_le(H)
    header += bytes([C])
    header += bytes([dtype_code])
    header += _u16_le(0)  # reserved

    # raw bytes
    payload = img.tobytes(order="C")

    with open(path_out, "wb") as f:
        f.write(header)
        f.write(payload)

def _read_imgb(path_in: str):
    with open(path_in, "rb") as f:
        hdr = f.read(16)
        if hdr[0:4] != MAGIC:
            raise ValueError(f"Bad magic in {path_in}")

        W = _read_u32_le(hdr, 4)
        H = _read_u32_le(hdr, 8)
        C = hdr[12]
        dtype_code = hdr[13]
        dtype_name = CODE_TO_DTYPE.get(dtype_code)
        if dtype_name is None:
            raise ValueError(f"Unknown dtype_code {dtype_code} in {path_in}")

        raw = f.read()

    # Reconstruct array using imageio’s underlying numpy without importing numpy explicitly
    # We *must* use numpy to reshape; imageio already depends on numpy.
    import numpy as np  # only used here for reshape/frombuffer

    dt = np.dtype(dtype_name)
    if C == 1:
        arr = np.frombuffer(raw, dtype=dt).reshape((H, W))
    else:
        arr = np.frombuffer(raw, dtype=dt).reshape((H, W, C))
    return arr

def convert_folder_to_bin(in_dir: str, out_dir: str | None = None) -> str:
    if in_dir is None:
        in_dir = out_dir.rstrip("/\\") + "_png"
    os.makedirs(in_dir, exist_ok=True)

    exts = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")
    names = [n for n in os.listdir(in_dir) if n.lower().endswith(exts)]
    names.sort()

    for name in names:
        src = os.path.join(in_dir, name)
        base = os.path.splitext(name)[0]
        dst = os.path.join(out_dir, base + ".imgb")

        img = iio.imread(src)
        _write_imgb(dst, img)

    return out_dir

def convert_folder_bin_to_images(in_dir: str, out_dir: str | None = None, ext: str = ".png") -> str:
    if out_dir is None:
        out_dir = in_dir.rstrip("/\\") + "_images"
    os.makedirs(out_dir, exist_ok=True)

    names = [n for n in os.listdir(in_dir) if n.lower().endswith(".imgb")]
    names.sort()

    for name in names:
        src = os.path.join(in_dir, name)
        base = os.path.splitext(name)[0]
        dst = os.path.join(out_dir, base + ext)

        arr = _read_imgb(src)
        iio.imwrite(dst, arr)

    return out_dir

if __name__ == "__main__":
    # Example usage:
    #   python3 img_bin_convert.py
    #
    # Change these:
    folder = "dino/cross_raw_data"
    out_bin = convert_folder_to_bin(None, folder)
    print("Wrote:", out_bin)

    folder = "headshot/cross_raw_data"
    out_bin = convert_folder_to_bin(None, folder)
    print("Wrote:", out_bin)

    folder = "town/cross_raw_data"
    out_bin = convert_folder_to_bin(None, folder)
    print("Wrote:", out_bin)
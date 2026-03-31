# Input images are expected to be 512x512
# The crop is the exact central 128x128 region

import os
import imageio.v3 as iio

def crop_center_image(img, crop_h: int = 128, crop_w: int = 128):
    img_h = int(img.shape[0])
    img_w = int(img.shape[1])

    if crop_h > img_h or crop_w > img_w:
        raise ValueError(
            f"Crop size ({crop_h}x{crop_w} is larger than image size ({img_h}x{img_w}))"
        )

    start_y = (img_h - crop_h) // 2
    start_x = (img_w - crop_w) // 2
    end_y = start_y + crop_h
    end_x = start_x + crop_w

    return img[start_y:end_y, start_x:end_x]

def convert_folder_center_crop_to_png(
    in_dir: str,
    out_dir: str | None = None,
    expected_h: int = 512,
    expected_w: int = 512,
    crop_h: int = 128,
    crop_w: int = 128,
):
    if out_dir is None:
        out_dir = in_dir.rstrip("/\\") + f"_center_{crop_h}x{crop_w}_png"
    
    os.makedirs(out_dir, exist_ok=True)

    exts = (".png")
    names = [name for name in os.listdir(in_dir) if name.lower().endswith(exts)]
    names.sort()

    for name in names:
        src = os.path.join(in_dir, name)
        base = os.path.splitext(name)[0]
        dst = os.path.join(out_dir, base + ".png")

        if name == "reliable_avg_Z_conf_0_25.png":
            continue

        # Read image
        img = iio.imread(src)

        # Validate dimensions
        img_h = int(img.shape[0])
        img_w = int(img.shape[1])

        if img_h != expected_h or img_w != expected_w:
            raise ValueError(
                f"{name} has size {img_h}x{img_w}, expected {expected_h}x{expected_w}."
            )
        
        # Crop centre 128x128
        cropped = crop_center_image(img, crop_h=crop_h, crop_w=crop_w)

        iio.imwrite(dst, cropped)

    return out_dir

if __name__ == "__main__":
    folder = "Python_Red/Bit_Manipulation/headshot/cross_raw_data_png"
    out_png = convert_folder_center_crop_to_png(folder)
    print("Wrote:", out_png)

    folder = "Python_Red/Bit_Manipulation/headshot/cross_data_blurred_png"
    out_png = convert_folder_center_crop_to_png(folder)
    print("Wrote:", out_png)

    folder = "Python_Red/Bit_Manipulation/headshot/confidence_png"
    out_png = convert_folder_center_crop_to_png(folder)
    print("Wrote:", out_png)

    folder = "Python_Red/Bit_Manipulation/headshot/confidence_robust_png"
    out_png = convert_folder_center_crop_to_png(folder)
    print("Wrote:", out_png)

    folder = "Python_Red/Bit_Manipulation/headshot/disparity_png"
    out_png = convert_folder_center_crop_to_png(folder)
    print("Wrote:", out_png)

    folder = "Python_Red/Bit_Manipulation/headshot/disparity_robust_png"
    out_png = convert_folder_center_crop_to_png(folder)
    print("Wrote:", out_png)
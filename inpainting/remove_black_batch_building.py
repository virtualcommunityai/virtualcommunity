import torch
import sys
import argparse
import numpy as np
from pathlib import Path
from matplotlib import pyplot as plt
import cv2
from PIL import Image

from sam_segment import predict_masks_with_sam
from lama_inpaint import inpaint_img_with_lama
from utils import load_img_to_array, save_array_to_img, dilate_mask, \
    show_mask, show_points, get_clicked_point


def setup_args(parser):
    parser.add_argument(
        "--input_img", type=str, required=True,
        help="Path to a single input img",
    )
    parser.add_argument(
        "--coords_type", type=str, required=True,
        default="key_in", choices=["click", "key_in"], 
        help="The way to select coords",
    )
    parser.add_argument(
        "--point_coords", type=float, nargs='+', required=True,
        help="The coordinate of the point prompt, [coord_W coord_H].",
    )
    parser.add_argument(
        "--point_labels", type=int, nargs='+', required=True,
        help="The labels of the point prompt, 1 or 0.",
    )
    parser.add_argument(
        "--dilate_kernel_size", type=int, default=None,
        help="Dilate kernel size. Default: None",
    )
    parser.add_argument(
        "--output_dir", type=str, required=True,
        help="Output path to the directory with results.",
    )
    parser.add_argument(
        "--sam_model_type", type=str,
        default="vit_h", choices=['vit_h', 'vit_l', 'vit_b', 'vit_t'],
        help="The type of sam model to load. Default: 'vit_h"
    )
    parser.add_argument(
        "--sam_ckpt", type=str, required=True,
        help="The path to the SAM checkpoint to use for mask generation.",
    )
    parser.add_argument(
        "--lama_config", type=str,
        default="./lama/configs/prediction/default.yaml",
        help="The path to the config file of lama model. "
             "Default: the config of big-lama",
    )
    parser.add_argument(
        "--lama_ckpt", type=str, required=True,
        help="The path to the lama checkpoint.",
    )

def find_black_pixel(img):
    black_pixels = np.where((img[:,:,0] == 0) & 
                            (img[:,:,1] == 0) & 
                            (img[:,:,2] == 0))
    
    height, width, _ = img.shape
    if len(black_pixels[0]) *3 >img.size-10:
        return None
    def is_black(pixel):
        return np.all(pixel == [0, 0, 0])
    def is_isolated(y, x):
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dy == 0 and dx == 0:
                    continue
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width:
                    if not is_black(img[ny, nx]):
                        return False
        return True
    for y in range(height):
        for x in range(width):
            if is_black(img[y, x]) and is_isolated(y, x):
                return [x, y]
    if len(black_pixels[0]) > 0:
        return [black_pixels[1][0], black_pixels[0][0]]
    else:
        return None

def inpaint_one_image(img):
    latest_coords = find_black_pixel(img)
    iter_i = 0
    while latest_coords != None:
        iter_i = iter_i + 1

        mask = cv2.inRange(img, (0, 0, 0), (5, 5, 5))
        # if len(masks)>0:
        #     mask |= tensor_to_image(masks).astype(np.uint8) * 255
        masks = [mask]


        # dilate mask to avoid unmasked edge effect
        if args.dilate_kernel_size is not None:
            masks = [dilate_mask(mask, args.dilate_kernel_size) for mask in masks]

        # visualize the segmentation results
        img_stem = Path(args.input_img).stem
        out_dir = Path(args.output_dir) / img_stem
        out_dir.mkdir(parents=True, exist_ok=True)
        for idx, mask in enumerate(masks):
            if idx != 0 : continue
            # path to the results
            mask_p = out_dir / f"mask_{idx}_{iter_i}.png"
            img_points_p = out_dir / f"with_points_{iter_i}.png"
            img_mask_p = out_dir / f"with_mask_{idx}_{iter_i}.png"

            # save the mask
            save_array_to_img(mask, mask_p)

            # save the pointed and masked image
            dpi = plt.rcParams['figure.dpi']
            height, width = img.shape[:2]
            plt.figure(figsize=(width/dpi/0.77, height/dpi/0.77))
            plt.imshow(img)
            plt.axis('off')
            show_points(plt.gca(), [latest_coords], args.point_labels,
                        size=(width*0.04)**2)
            plt.savefig(img_points_p, bbox_inches='tight', pad_inches=0)
            show_mask(plt.gca(), mask, random_color=False)
            plt.savefig(img_mask_p, bbox_inches='tight', pad_inches=0)
            plt.close()

        # inpaint the masked image
        for idx, mask in enumerate(masks):
            if idx != 0 : continue
            mask_p = out_dir / f"mask_{idx}_{iter_i}.png"
            img_inpainted_p = out_dir / f"inpainted_with_mask_{idx}_{iter_i}.png"
            img_inpainted = inpaint_img_with_lama(
                img, mask, args.lama_config, args.lama_ckpt, device=device)
            save_array_to_img(img_inpainted, img_inpainted_p)

        if np.array_equal(img, img_inpainted): break
        img  = img_inpainted
        latest_coords=find_black_pixel(img)
        break
    return img

if __name__ == "__main__":
    """Example usage:
    python remove_anything.py \
        --input_img FA_demo/FA1_dog.png \
        --coords_type key_in \
        --point_coords 750 500 \
        --point_labels 1 \
        --dilate_kernel_size 15 \
        --output_dir ./results \
        --sam_model_type "vit_h" \
        --sam_ckpt sam_vit_h_4b8939.pth \
        --lama_config lama/configs/prediction/default.yaml \
        --lama_ckpt big-lama 
    """
    parser = argparse.ArgumentParser()
    setup_args(parser)
    args = parser.parse_args(sys.argv[1:])
    device = "cuda" if torch.cuda.is_available() else "cpu"

    if args.coords_type == "click":
        latest_coords = get_clicked_point(args.input_img)
    elif args.coords_type == "key_in":
        latest_coords = args.point_coords
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    crop_box=(0,0,189,256)
    for file in Path(args.input_img).iterdir():
        if not ("png" in str(file)):continue
        print("Processing:",file)
        img = load_img_to_array(file)
        img = inpaint_one_image(img)
        img_p = out_dir / f"{file.name}"
        print("Save to:",img_p)
        save_array_to_img(img, img_p)

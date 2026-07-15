from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]

SOURCE_DIR = REPO_ROOT / "assets/layers/source/environment/plum_battery_v23"
OUTPUT_DIR = REPO_ROOT / "assets/layers/mvp/plum_battery_v23"
BACKGROUND_V22 = REPO_ROOT / "assets/layers/mvp/clean_background_v22.png"
BACKGROUND_V23 = REPO_ROOT / "assets/layers/mvp/clean_background_v23.png"
MANIFEST_PATH = SOURCE_DIR / "manifest.json"

SOURCE_CROP = (70, 430, 520, 1150)
STRUCTURE_DILATION_PIXELS = 5

STAGES = (
    (0, 15, "plum_stage_01_bare.png", None),
    (
        16,
        35,
        "plum_stage_02_first_blooms.png",
        "plum_blossoms_stage_02.png",
    ),
    (
        36,
        55,
        "plum_stage_03_early_bloom.png",
        "plum_blossoms_stage_03.png",
    ),
    (
        56,
        80,
        "plum_stage_04_rich_bloom.png",
        "plum_blossoms_stage_04.png",
    ),
    (
        81,
        100,
        "plum_stage_05_full_bloom.png",
        "plum_blossoms_stage_05.png",
    ),
)


def _plum_structure_mask(bare: Image.Image, original: Image.Image) -> Image.Image:
    """Replace only the old and new plum ink, leaving the original paper untouched."""
    masks = []
    for image in (bare, original):
        rgb = np.asarray(image, dtype=np.int16)
        red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        luma = (red * 30 + green * 59 + blue * 11) / 100.0
        chroma = np.max(rgb, axis=2) - np.min(rgb, axis=2)
        masks.append((luma < 142) | ((chroma > 48) & (luma < 174)))

    spatial = Image.new("L", bare.size, 0)
    ImageDraw.Draw(spatial).polygon(
        [
            (225, 65),
            (335, 65),
            (350, 225),
            (449, 250),
            (449, 670),
            (350, 719),
            (35, 719),
            (25, 360),
            (65, 285),
            (165, 245),
            (188, 135),
        ],
        fill=255,
    )
    spatial_array = np.asarray(spatial) > 0
    structure = (masks[0] | masks[1]) & spatial_array
    structure = ndimage.binary_dilation(
        structure, iterations=STRUCTURE_DILATION_PIXELS
    )
    structure = ndimage.binary_closing(structure, iterations=2)
    alpha = Image.fromarray(np.where(structure, 255, 0).astype(np.uint8), "L")
    return alpha.filter(ImageFilter.GaussianBlur(radius=1.25))


def _load_stage(filename: str) -> Image.Image:
    with Image.open(SOURCE_DIR / filename) as source:
        stage = source.convert("RGB")
    expected_size = (
        SOURCE_CROP[2] - SOURCE_CROP[0],
        SOURCE_CROP[3] - SOURCE_CROP[1],
    )
    if stage.size != expected_size:
        raise ValueError(f"{filename} must be {expected_size}, got {stage.size}")
    return stage


def _build_background(bare: Image.Image) -> None:
    with Image.open(BACKGROUND_V22) as source:
        background = source.convert("RGB")
    if background.size != (1254, 1254):
        raise ValueError(f"Unexpected V2.2 background size: {background.size}")

    original_crop = background.crop(SOURCE_CROP)
    merged_crop = Image.composite(
        bare, original_crop, _plum_structure_mask(bare, original_crop)
    )
    background.paste(merged_crop, SOURCE_CROP[:2])
    background.save(BACKGROUND_V23, optimize=True)


def _overlay_from_stage(
    bare: Image.Image, stage: Image.Image, output_path: Path
) -> tuple[tuple[int, int], tuple[int, int], int]:
    bare_array = np.asarray(bare, dtype=np.int16)
    stage_array = np.asarray(stage, dtype=np.int16)
    difference = np.max(np.abs(stage_array - bare_array), axis=2) > 2
    difference = ndimage.binary_dilation(difference, iterations=1)
    alpha = Image.fromarray(np.where(difference, 255, 0).astype(np.uint8), "L")
    alpha = alpha.filter(ImageFilter.GaussianBlur(radius=0.45))
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError(f"No visible flower difference for {output_path.name}")

    left = max(0, bounds[0] - 2)
    top = max(0, bounds[1] - 2)
    right = min(stage.width, bounds[2] + 2)
    bottom = min(stage.height, bounds[3] + 2)
    crop_box = (left, top, right, bottom)

    rgba = stage.convert("RGBA").crop(crop_box)
    crop_alpha = alpha.crop(crop_box)
    rgba.putalpha(crop_alpha)
    pixels = np.asarray(rgba).copy()
    pixels[pixels[..., 3] == 0, :3] = 0
    rgba = Image.fromarray(pixels, "RGBA")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(output_path, optimize=True)
    alpha_pixels = int(np.count_nonzero(pixels[..., 3]))
    return (left, top), rgba.size, alpha_pixels


def build_assets() -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bare = _load_stage(STAGES[0][2])
    _build_background(bare)

    stage_entries: list[dict[str, object]] = []
    for index, (minimum, maximum, source_name, output_name) in enumerate(STAGES, 1):
        entry: dict[str, object] = {
            "stage": index,
            "minimumPercent": minimum,
            "maximumPercent": maximum,
            "source": str((SOURCE_DIR / source_name).relative_to(REPO_ROOT)),
        }
        if output_name is None:
            entry.update(
                {
                    "asset": None,
                    "positionSource": [SOURCE_CROP[0], SOURCE_CROP[1]],
                    "sizeSource": [0, 0],
                    "alphaPixels": 0,
                }
            )
        else:
            stage = _load_stage(source_name)
            output_path = OUTPUT_DIR / output_name
            offset, size, alpha_pixels = _overlay_from_stage(
                bare, stage, output_path
            )
            entry.update(
                {
                    "asset": str(output_path.relative_to(REPO_ROOT)),
                    "positionSource": [
                        SOURCE_CROP[0] + offset[0],
                        SOURCE_CROP[1] + offset[1],
                    ],
                    "sizeSource": list(size),
                    "alphaPixels": alpha_pixels,
                }
            )
        stage_entries.append(entry)

    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "version": "2.3",
        "status": "approved_static_battery_plum",
        "sourceCanvas": [1254, 1254],
        "logicalCanvas": [450, 450],
        "sourceCrop": list(SOURCE_CROP),
        "backgroundComposite": "PLUM_STRUCTURE_MASK",
        "structureDilationPixels": STRUCTURE_DILATION_PIXELS,
        "baseBackground": str(BACKGROUND_V23.relative_to(REPO_ROOT)),
        "keepNumericBatteryIndicator": True,
        "transition": "STATIC_LAYER_SWAP",
        "animatedBloom": False,
        "stages": stage_entries,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    print(json.dumps(build_assets(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

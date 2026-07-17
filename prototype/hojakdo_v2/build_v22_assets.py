from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from scipy import ndimage


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
CONFIG_PATH = PACKAGE_DIR / "config.json"
LOGICAL_SIZE = 450


def _source_path(relative: str) -> Path:
    return REPO_ROOT / relative


def _logical_body_mask() -> Image.Image:
    """Soft region for the body-only local scale, excluding fixed UI and seals."""
    mask = Image.new("L", (LOGICAL_SIZE, LOGICAL_SIZE), 0)
    draw = ImageDraw.Draw(mask)

    # Main torso, rear leg, belly, and the two front legs.
    draw.polygon(
        [
            (278, 257),
            (334, 255),
            (362, 277),
            (359, 307),
            (345, 330),
            (354, 363),
            (360, 390),
            (346, 414),
            (315, 433),
            (276, 439),
            (237, 429),
            (204, 413),
            (201, 380),
            (210, 345),
            (228, 310),
            (251, 279),
        ],
        fill=255,
    )

    # Forward arm and chest connection.
    draw.polygon(
        [
            (310, 288),
            (345, 292),
            (361, 320),
            (365, 356),
            (361, 390),
            (344, 410),
            (325, 402),
            (316, 378),
            (320, 347),
            (307, 319),
        ],
        fill=255,
    )

    # Curled tail. Keep the ground and seal to its right untouched.
    draw.polygon(
        [
            (348, 335),
            (371, 330),
            (386, 342),
            (395, 368),
            (394, 397),
            (382, 416),
            (362, 425),
            (347, 414),
            (351, 397),
            (365, 378),
            (365, 350),
        ],
        fill=255,
    )

    # A small dilation covers the antialiased ink fringe; feathering avoids a cutout edge.
    array = np.asarray(mask, dtype=np.uint8) > 0
    array = ndimage.binary_dilation(array, iterations=3)
    expanded = Image.fromarray(np.where(array, 255, 0).astype(np.uint8), "L")
    feathered = expanded.filter(ImageFilter.GaussianBlur(radius=3.0))

    # These interface elements overlap the broad tiger region but must not scale.
    protected = Image.new("L", feathered.size, 0)
    protected_draw = ImageDraw.Draw(protected)
    protected_draw.rectangle((188, 414, 282, 449), fill=255)  # battery + percentage
    protected_draw.rectangle((392, 255, 449, 392), fill=255)  # title + red seal
    protected = protected.filter(ImageFilter.GaussianBlur(radius=1.5))
    return ImageChops.subtract(feathered, protected)


def _resize_mask(mask: Image.Image, size: tuple[int, int]) -> Image.Image:
    return mask.resize(size, Image.Resampling.LANCZOS)


def _affine_scale(
    layer: Image.Image, scale: float, anchor: tuple[float, float]
) -> Image.Image:
    inverse = 1.0 / scale
    ax, ay = anchor
    return layer.transform(
        layer.size,
        Image.Transform.AFFINE,
        (inverse, 0.0, ax - ax * inverse, 0.0, inverse, ay - ay * inverse),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )


def build_assets() -> dict[str, str | float | list[float]]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    render = config["render"]
    scale = float(render["tigerScale"])
    logical_anchor = tuple(float(value) for value in render["tigerScaleAnchor"])

    background_path = _source_path("assets/layers/mvp/clean_background.png")
    head_path = _source_path("assets/layers/source/characters/tiger_head_v21.png")
    pupils_path = _source_path("assets/layers/mvp/tiger_pupils.png")

    with Image.open(background_path) as source:
        background = source.convert("RGBA")
    with Image.open(head_path) as source:
        head = source.convert("RGBA")
    with Image.open(pupils_path) as source:
        pupils = source.convert("RGBA")

    sx = background.width / LOGICAL_SIZE
    sy = background.height / LOGICAL_SIZE
    source_anchor = (logical_anchor[0] * sx, logical_anchor[1] * sy)
    body_mask = _resize_mask(_logical_body_mask(), background.size)

    # Warp the complete background inside a soft tiger-shaped window. This shrinks
    # the embedded body while naturally sampling adjacent paper into the exposed
    # six-percent rim; no synthetic inpaint or radial fill is required.
    scaled_background = _affine_scale(background, scale, source_anchor)
    scaled_head = _affine_scale(head, scale, source_anchor)
    scaled_pupils = _affine_scale(pupils, scale, source_anchor)

    background_v22 = Image.composite(scaled_background, background, body_mask)

    background_out = _source_path("assets/layers/mvp/clean_background_v22.png")
    head_out = _source_path("assets/layers/source/characters/tiger_head_v22.png")
    pupils_out = _source_path("assets/layers/source/characters/tiger_pupils_v22.png")
    mask_out = _source_path("assets/layers/source/drafts/tiger_body_mask_v22.png")

    background_v22.convert("RGB").save(background_out, optimize=True)
    scaled_head.save(head_out, optimize=True)
    scaled_pupils.save(pupils_out, optimize=True)
    body_mask.save(mask_out, optimize=True)

    return {
        "version": "2.2",
        "tigerScale": scale,
        "logicalAnchor": list(logical_anchor),
        "background": str(background_out.relative_to(REPO_ROOT)),
        "head": str(head_out.relative_to(REPO_ROOT)),
        "pupils": str(pupils_out.relative_to(REPO_ROOT)),
        "mask": str(mask_out.relative_to(REPO_ROOT)),
    }


def main() -> None:
    print(json.dumps(build_assets(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from scipy import ndimage

from prototype.hojakdo_v2.render_prototype import FACE_SIZE, PrototypeRenderer
from prototype.hojakdo_v2.render_v31_preview import (
    _polished_background,
    _polished_hour_hand,
)
from prototype.hojakdo_v2.scene_calculator import HojakdoSceneCalculator


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
V4_ROOT = REPO_ROOT / "assets/layers/v4"
DRAWABLE_DIR = V4_ROOT / "drawable"
ANIMATION_DIR = V4_ROOT / "animations"
FRAME_DIR = V4_ROOT / "frames"
OUTPUT_DIR = PACKAGE_DIR / "output"
MANIFEST_PATH = V4_ROOT / "manifest.json"

PIVOT = (224.0, 207.0)
HOUR_POLISH_ANCHOR = (302.0, 148.0)
SOURCE_HAND_PERCH_ANCHORS = {
    "HOUR": {
        "LARGE": (305.0, 143.0),
        "SMALL": (302.0, 148.0),
    },
    "MINUTE": {
        "LARGE": (159.0, 118.0),
        "SMALL": (171.0, 122.0),
    },
}
HOUR_HAND_TARGET_LENGTH = 92.0
MINUTE_HAND_TARGET_LENGTH = 126.0
HOUR_HAND_BRIGHTNESS = 0.78
V4_BASE_HOUR_BRIGHTNESS = 0.88
HAND_ALPHA_THRESHOLD = 16
# Match the flying pose to the 61 px-tall approved small static magpie. The
# former 100x78 resource made the character grow visibly at takeoff/exit.
SMALL_FLIGHT_WIDTH = 70
LARGE_TIGER_FOOT = (335.0, 233.0)
# The former y=235 point touched only the very tip of the tiger's crown.
# Overlap the foot by six logical pixels so the small bird reads as planted
# on the head at watch size instead of optically floating above it.
SMALL_TIGER_FOOT = (340.0, 241.0)
FRAME_DURATION_MS = 125
FPS = 1000 / FRAME_DURATION_MS
READOUT_CENTER_X = FACE_SIZE // 2
READOUT_TIME_Y = 85
READOUT_TIME_FONT_SIZE = 52
READOUT_DATE_WEEKDAY_Y = 132
READOUT_DATE_WEEKDAY_FONT_SIZE = 16
READOUT_DATE_WEEKDAY_SEPARATOR = "  "
READOUT_TIME_WFF_BOUNDS = (131, 74, 188, 66)
READOUT_DATE_WEEKDAY_WFF_BOUNDS = (166, 129, 118, 25)
BATTERY_ICON_POSITION = (194, 418)
BATTERY_TEXT_CENTER_X = 236
BATTERY_TEXT_Y = 416
DATE_CLOUD_CLEANUP_BOUNDS = (198, 250, 252, 300)
DATE_HANJI_OVERLAY_BOUNDS = (188, 272, 270, 294)
PINE_SPRIG_CLEANUP_BOUNDS = (282, 158, 306, 181)
TIGER_HIND_LEG_GHOST_POLYGON = (
    (195, 320),
    (220, 309),
    (231, 329),
    (227, 380),
    (222, 414),
    (199, 414),
    (191, 391),
    (192, 345),
)
TIGER_HIND_LEG_GHOST_BOUNDS = (191, 309, 231, 414)


@dataclass(frozen=True)
class Pose:
    sprite: Image.Image
    anchor: tuple[float, float]
    foot: tuple[float, float]
    angle: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    mirror: bool = False


@dataclass(frozen=True)
class HandLengthTransform:
    source_length: float
    target_length: float
    axis: tuple[float, float]

    @property
    def scale(self) -> float:
        return self.target_length / self.source_length

    def map_point(self, point: tuple[float, float]) -> tuple[float, float]:
        ux, uy = self.axis
        vx, vy = -uy, ux
        dx = point[0] - PIVOT[0]
        dy = point[1] - PIVOT[1]
        along = dx * ux + dy * uy
        across = dx * vx + dy * vy
        return (
            PIVOT[0] + along * self.scale * ux + across * vx,
            PIVOT[1] + along * self.scale * uy + across * vy,
        )


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSerif-Bold.ttf" if bold else "DejaVuSerif.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    return ImageFont.truetype(str(path), size=size)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decoded_image_bytes(path: Path) -> int:
    with Image.open(path) as image:
        return image.width * image.height * 4


def _save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = image.convert("RGBA")
    pixels = np.asarray(rgba, dtype=np.uint8).copy()
    pixels[pixels[..., 3] == 0, :3] = 0
    # Keep the previous valid resource in place until Pillow has completed and
    # verified the replacement. This makes repeated V4 builds safe even if a
    # generation process is interrupted while writing a PNG.
    temporary = path.with_suffix(path.suffix + ".tmp")
    Image.fromarray(pixels, "RGBA").save(
        temporary, format="PNG", optimize=True
    )
    with Image.open(temporary) as written:
        written.verify()
    temporary.replace(path)


def _save_rgb_png(image: Image.Image, path: Path) -> None:
    """Atomically save a user-facing RGB preview and verify the PNG first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    image.convert("RGB").save(temporary, format="PNG", optimize=True)
    with Image.open(temporary) as written:
        written.verify()
    temporary.replace(path)


def _logical_layer(path: Path, mode: str = "RGBA") -> Image.Image:
    with Image.open(path) as source:
        return source.convert(mode).resize(
            (FACE_SIZE, FACE_SIZE), Image.Resampling.LANCZOS
        )


def _hand_length_transform(
    layer: Image.Image, target_length: float
) -> HandLengthTransform:
    alpha = np.asarray(layer.convert("RGBA").getchannel("A"), dtype=np.uint8)
    y, x = np.where(alpha > HAND_ALPHA_THRESHOLD)
    if len(x) == 0:
        raise ValueError("Clock-hand layer has no visible pixels")
    dx = x.astype(np.float64) - PIVOT[0]
    dy = y.astype(np.float64) - PIVOT[1]
    distances = np.hypot(dx, dy)
    tip = int(np.argmax(distances))
    source_length = float(distances[tip])
    return HandLengthTransform(
        source_length=source_length,
        target_length=target_length,
        axis=(float(dx[tip] / source_length), float(dy[tip] / source_length)),
    )


def _apply_hand_length_transform(
    layer: Image.Image, transform: HandLengthTransform
) -> Image.Image:
    ux, uy = transform.axis
    vx, vy = -uy, ux
    inverse_scale = 1.0 / transform.scale
    a = inverse_scale * ux * ux + vx * vx
    b = inverse_scale * ux * uy + vx * vy
    d = inverse_scale * uy * ux + vy * vx
    e = inverse_scale * uy * uy + vy * vy
    c = PIVOT[0] - a * PIVOT[0] - b * PIVOT[1]
    f = PIVOT[1] - d * PIVOT[0] - e * PIVOT[1]
    return layer.convert("RGBA").transform(
        layer.size,
        Image.Transform.AFFINE,
        (a, b, c, d, e, f),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )


def _mapped_hand_perch_anchors(
    hour_transform: HandLengthTransform,
    minute_transform: HandLengthTransform,
) -> dict[str, dict[str, tuple[int, int]]]:
    transforms = {"HOUR": hour_transform, "MINUTE": minute_transform}
    return {
        hand: {
            character: tuple(
                int(round(value))
                for value in transforms[hand].map_point(source_anchor)
            )
            for character, source_anchor in anchors.items()
        }
        for hand, anchors in SOURCE_HAND_PERCH_ANCHORS.items()
    }


def _replace_paper_texture(
    values: np.ndarray,
    target_box: tuple[int, int, int, int],
    donor_box: tuple[int, int, int, int],
    feather_pixels: float,
) -> None:
    """Replace a plain-paper artifact with a color-matched texture patch."""
    x0, y0, x1, y1 = target_box
    target = values[y0:y1, x0:x1].copy()
    donor = values[
        donor_box[1] : donor_box[3], donor_box[0] : donor_box[2]
    ].copy()
    if donor.shape != target.shape:
        raise ValueError("Paper donor and target patches must have identical sizes")

    donor += np.median(target, axis=(0, 1)) - np.median(donor, axis=(0, 1))
    donor = np.clip(donor, 0, 255)
    height, width = target.shape[:2]
    yy, xx = np.indices((height, width))
    edge_distance = np.minimum.reduce((xx, yy, width - 1 - xx, height - 1 - yy))
    patch_alpha = np.clip(
        edge_distance.astype(np.float32) / feather_pixels, 0.0, 1.0
    )
    patch_alpha = patch_alpha * patch_alpha * (3.0 - 2.0 * patch_alpha)
    values[y0:y1, x0:x1] = (
        target * (1.0 - patch_alpha[..., None])
        + donor * patch_alpha[..., None]
    )


def _repair_tiger_hind_leg_ghost(background: Image.Image) -> Image.Image:
    """Replace the exposed 100% tiger leg rim with the approved 94% source."""
    with Image.open(REPO_ROOT / "assets/layers/mvp/clean_background.png") as source:
        original = source.convert("RGBA").resize(
            (FACE_SIZE, FACE_SIZE), Image.Resampling.LANCZOS
        )

    scale = 0.94
    anchor_x, anchor_y = (300.0, 429.0)
    inverse = 1.0 / scale
    scaled = original.transform(
        original.size,
        Image.Transform.AFFINE,
        (
            inverse,
            0.0,
            anchor_x - anchor_x * inverse,
            0.0,
            inverse,
            anchor_y - anchor_y * inverse,
        ),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )

    # V2.2's soft body window stopped just inside the old rear-leg outline,
    # leaving a second pale/dark contour to the left of the approved 94% leg.
    # Pull only that narrow contour from the correctly scaled source. Keep the
    # live battery footprint outside the repair even at the feathered edge.
    mask = Image.new("L", (FACE_SIZE, FACE_SIZE), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(TIGER_HIND_LEG_GHOST_POLYGON, fill=255)
    draw.rectangle((184, 414, 282, 449), fill=0)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=3.0))
    return Image.composite(scaled, background.convert("RGBA"), mask).convert("RGB")


def _remove_embedded_ui(background: Image.Image) -> Image.Image:
    """Remove the V2.3 baked readout and battery pixels."""
    values = np.asarray(background.convert("RGB"), dtype=np.float32)

    # Replace the pale cloud tail beside the date with nearby clean paper
    # texture. Pasting only the detected line pixels avoids a flat rectangular
    # repair and preserves the adjacent plum branch.
    cloud_box = (148, 240, 202, 275)
    donor_box = (210, 100, 264, 135)
    x0, y0, x1, y1 = cloud_box
    cloud = values[y0:y1, x0:x1].copy()
    donor = values[donor_box[1] : donor_box[3], donor_box[0] : donor_box[2]].copy()
    cloud_luma = (
        0.2126 * cloud[..., 0]
        + 0.7152 * cloud[..., 1]
        + 0.0722 * cloud[..., 2]
    )
    donor_luma = (
        0.2126 * donor[..., 0]
        + 0.7152 * donor[..., 1]
        + 0.0722 * donor[..., 2]
    )
    cloud_paper = cloud[cloud_luma > 168]
    donor_paper = donor[donor_luma > 168]
    donor += np.median(cloud_paper, axis=0) - np.median(donor_paper, axis=0)
    cloud_mask = cloud_luma < 167
    cloud_mask = ndimage.binary_dilation(cloud_mask, iterations=2)
    cloud_alpha = ndimage.gaussian_filter(cloud_mask.astype(np.float32), sigma=0.8)
    values[y0:y1, x0:x1] = (
        cloud * (1.0 - cloud_alpha[..., None])
        + donor * cloud_alpha[..., None]
    )

    luma = (
        0.2126 * values[..., 0]
        + 0.7152 * values[..., 1]
        + 0.0722 * values[..., 2]
    )
    mask = np.zeros(luma.shape, dtype=bool)
    # The original center crop contains 14:18, 07.13, and SUN. Cover the full
    # glyph bounds, including the anti-aliased last digit and weekday remnants
    # that previously looked like a dark hook and a pale cloud behind V4 text.
    # Keep these battery components separate: one broad rectangle also catches
    # the tiger's front leg, which starts immediately to the right.
    for x0, y0, x1, y1, threshold in (
        (175, 220, 275, 295, 165),
        (187, 416, 220, 435, 118),
        (222, 421, 231, 435, 118),
        (231, 421, 240, 435, 118),
        (240, 421, 253, 435, 118),
    ):
        local = luma[y0:y1, x0:x1] < threshold
        labels, count = ndimage.label(local, np.ones((3, 3), dtype=bool))
        kept = np.zeros_like(local)
        for index in range(1, count + 1):
            component = labels == index
            if int(component.sum()) >= 2:
                kept |= component
        mask[y0:y1, x0:x1] |= kept
    mask = ndimage.binary_dilation(mask, iterations=2)
    _, nearest = ndimage.distance_transform_edt(mask, return_indices=True)
    filled = values.copy()
    filled[mask] = values[nearest[0][mask], nearest[1][mask]]
    feather = ndimage.gaussian_filter(mask.astype(np.float32), sigma=0.75)
    result = values * (1.0 - feather[..., None]) + filled * feather[..., None]

    # The old date left a very pale, block-shaped cloud halo after its dark
    # pixels were inpainted. Replace the complete quiet-zone patch, not merely
    # another luma threshold, so no anti-aliased edge can survive behind the
    # live date. A feathered clean-paper donor keeps the repair invisible and
    # stops before the adjacent tiger and plum artwork.
    _replace_paper_texture(
        result,
        DATE_CLOUD_CLEANUP_BOUNDS,
        (230, 45, 284, 95),
        feather_pixels=5.0,
    )
    # Force the entire live-date footprint and its right-side margin to clean
    # hanji. This second, wider repair is not threshold-based: every pixel in
    # the full-opacity interior is replaced, including any cloud-colored halo.
    _replace_paper_texture(
        result,
        DATE_HANJI_OVERLAY_BOUNDS,
        (200, 60, 282, 82),
        feather_pixels=2.0,
    )

    # Remove the detached pine-needle fragment floating in the upper-right
    # paper field. The donor is the immediately adjacent clean paper strip, so
    # the local color and grain stay continuous without touching the magpie,
    # cloud, pivot, or either live hand layer.
    _replace_paper_texture(
        result,
        PINE_SPRIG_CLEANUP_BOUNDS,
        (258, 158, 282, 181),
        feather_pixels=3.0,
    )
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8), "RGB")


def _trim(
    image: Image.Image,
    anchor: tuple[float, float] | None = None,
    padding: int = 4,
) -> tuple[Image.Image, tuple[float, float] | None, tuple[int, int, int, int]]:
    bounds = image.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("Cannot trim an empty image")
    box = (
        max(0, bounds[0] - padding),
        max(0, bounds[1] - padding),
        min(image.width, bounds[2] + padding),
        min(image.height, bounds[3] + padding),
    )
    local_anchor = None
    if anchor is not None:
        local_anchor = (anchor[0] - box[0], anchor[1] - box[1])
    return image.crop(box), local_anchor, box


def _posed_sprite(pose: Pose) -> tuple[Image.Image, tuple[float, float]]:
    pad = 32
    source = pose.sprite.convert("RGBA")
    anchor = pose.anchor
    if pose.mirror:
        source = source.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        anchor = (source.width - 1 - anchor[0], anchor[1])
    canvas = Image.new(
        "RGBA", (source.width + pad * 2, source.height + pad * 2), (0, 0, 0, 0)
    )
    canvas.alpha_composite(source, (pad, pad))
    center = (anchor[0] + pad, anchor[1] + pad)
    sx = pose.scale_x
    sy = pose.scale_y
    if math.isclose(sx, 0.0):
        sx = 0.02
    if math.isclose(sy, 0.0):
        sy = 0.02
    affine = (
        1.0 / sx,
        0.0,
        center[0] - center[0] / sx,
        0.0,
        1.0 / sy,
        center[1] - center[1] / sy,
    )
    transformed = canvas.transform(
        canvas.size,
        Image.Transform.AFFINE,
        affine,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )
    if not math.isclose(pose.angle, 0.0):
        transformed = transformed.rotate(
            -pose.angle,
            center=center,
            resample=Image.Resampling.BICUBIC,
            expand=False,
        )
    return transformed, center


def _scene_frame(pose: Pose) -> Image.Image:
    sprite, anchor = _posed_sprite(pose)
    frame = Image.new("RGBA", (FACE_SIZE, FACE_SIZE), (0, 0, 0, 0))
    position = (
        int(round(pose.foot[0] - anchor[0])),
        int(round(pose.foot[1] - anchor[1])),
    )
    frame.alpha_composite(sprite, position)
    return frame


def _curve(
    start: tuple[float, float],
    end: tuple[float, float],
    count: int,
    arc: float = 0.0,
) -> list[tuple[float, float]]:
    points = []
    for index in range(count):
        raw = index / max(1, count - 1)
        t = raw * raw * (3.0 - 2.0 * raw)
        x = start[0] + (end[0] - start[0]) * t
        y = start[1] + (end[1] - start[1]) * t - 4.0 * arc * t * (1.0 - t)
        points.append((x, y))
    return points


def _pose_sequence(
    sprite: Image.Image,
    anchor: tuple[float, float],
    points: Sequence[tuple[float, float]],
    *,
    angles: Sequence[float] | None = None,
    scale_x: Sequence[float] | None = None,
    scale_y: Sequence[float] | None = None,
    mirrors: Sequence[bool] | None = None,
) -> list[Image.Image]:
    count = len(points)
    angles = angles or [0.0] * count
    scale_x = scale_x or [1.0] * count
    scale_y = scale_y or [1.0] * count
    mirrors = mirrors or [False] * count
    return [
        _scene_frame(
            Pose(
                sprite=sprite,
                anchor=anchor,
                foot=points[index],
                angle=float(angles[index]),
                scale_x=float(scale_x[index]),
                scale_y=float(scale_y[index]),
                mirror=bool(mirrors[index]),
            )
        )
        for index in range(count)
    ]


def _quantize_gif(frame: Image.Image) -> Image.Image:
    alpha = frame.getchannel("A")
    paletted = frame.convert("RGB").convert(
        "P", palette=Image.Palette.ADAPTIVE, colors=255
    )
    paletted.paste(255, mask=alpha.point(lambda value: 255 if value <= 8 else 0))
    paletted.info["transparency"] = 255
    return paletted


def _write_animation(name: str, frames: list[Image.Image]) -> dict[str, object]:
    union = None
    for frame in frames:
        bounds = frame.getchannel("A").getbbox()
        if bounds is None:
            continue
        if union is None:
            union = list(bounds)
        else:
            union = [
                min(union[0], bounds[0]),
                min(union[1], bounds[1]),
                max(union[2], bounds[2]),
                max(union[3], bounds[3]),
            ]
    if union is None:
        raise ValueError(f"Animation {name} is empty")
    box = (
        max(0, union[0] - 4),
        max(0, union[1] - 4),
        min(FACE_SIZE, union[2] + 4),
        min(FACE_SIZE, union[3] + 4),
    )
    cropped = [frame.crop(box) for frame in frames]
    frame_root = FRAME_DIR / name
    for index, frame in enumerate(cropped):
        _save_png(frame, frame_root / f"frame_{index:02d}.png")

    gif_path = ANIMATION_DIR / f"{name}.gif"
    gif_path.parent.mkdir(parents=True, exist_ok=True)
    quantized = [_quantize_gif(frame) for frame in cropped]
    quantized[0].save(
        gif_path,
        save_all=True,
        append_images=quantized[1:],
        duration=FRAME_DURATION_MS,
        loop=0,
        optimize=False,
        disposal=2,
        transparency=255,
    )
    thumbnail_path = DRAWABLE_DIR / f"{name}_thumbnail.png"
    _save_png(cropped[0], thumbnail_path)
    decoded_bytes = cropped[0].width * cropped[0].height * 4 * len(cropped)
    metadata = {
        "schemaVersion": 1,
        "id": name,
        "format": "AGIF",
        "resource": f"{name}.gif",
        "thumbnail": thumbnail_path.name,
        "placementLogical": [box[0], box[1]],
        "sizeLogical": [box[2] - box[0], box[3] - box[1]],
        "anchorX": 0,
        "anchorY": 0,
        "anchorSemantics": "common_frame_canvas_top_left",
        "cropX": box[0],
        "cropY": box[1],
        "cropWidth": box[2] - box[0],
        "cropHeight": box[3] - box[1],
        "facing": "SCENE_DIRECTED",
        "startPose": f"{name}:frame_00",
        "endPose": f"{name}:frame_{len(cropped) - 1:02d}",
        "loopCount": 1,
        "frameCount": len(cropped),
        "frameDurationMs": FRAME_DURATION_MS,
        "fps": FPS,
        "decodedBytesEstimate": decoded_bytes,
        "sha256": _sha256(gif_path),
    }
    metadata_path = ANIMATION_DIR / f"{name}.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def _static_pose(
    name: str,
    sprite: Image.Image,
    anchor: tuple[float, float],
    *,
    angle: float = 0.0,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    mirror: bool = False,
) -> dict[str, object]:
    posed, posed_anchor = _posed_sprite(
        Pose(
            sprite=sprite,
            anchor=anchor,
            foot=(0.0, 0.0),
            angle=angle,
            scale_x=scale_x,
            scale_y=scale_y,
            mirror=mirror,
        )
    )
    trimmed, local_anchor, _ = _trim(posed, posed_anchor, padding=3)
    if local_anchor is None:
        raise AssertionError("Static pose anchor was lost")
    path = DRAWABLE_DIR / f"{name}.png"
    _save_png(trimmed, path)
    return {
        "id": name,
        "resource": path.name,
        "sizeLogical": list(trimmed.size),
        "anchorLogical": [round(local_anchor[0], 3), round(local_anchor[1], 3)],
        "sha256": _sha256(path),
    }


def _foreground_mask(
    name: str,
    background: Image.Image,
    roi: tuple[int, int, int, int],
    polygon: Iterable[tuple[int, int]],
    threshold: float,
) -> dict[str, object]:
    rgba = background.convert("RGBA")
    values = np.asarray(rgba.convert("RGB"), dtype=np.float32)
    luma = (
        0.2126 * values[..., 0]
        + 0.7152 * values[..., 1]
        + 0.0722 * values[..., 2]
    )
    chroma = values.max(axis=2) - values.min(axis=2)
    spatial = Image.new("L", (FACE_SIZE, FACE_SIZE), 0)
    ImageDraw.Draw(spatial).polygon(list(polygon), fill=255)
    selected = ((luma < threshold) | ((chroma > 35) & (luma < 185))) & (
        np.asarray(spatial) > 0
    )
    selected = ndimage.binary_dilation(selected, iterations=1)
    alpha = ndimage.gaussian_filter(selected.astype(np.float32), sigma=0.55)
    layer = np.asarray(rgba, dtype=np.uint8).copy()
    layer[..., 3] = np.clip(alpha * 255, 0, 255).astype(np.uint8)
    layer[layer[..., 3] == 0, :3] = 0
    x0, y0, x1, y1 = roi
    crop = Image.fromarray(layer, "RGBA").crop(roi)
    path = DRAWABLE_DIR / f"{name}.png"
    _save_png(crop, path)
    return {
        "id": name,
        "resource": path.name,
        "placementLogical": [x0, y0],
        "sizeLogical": [x1 - x0, y1 - y0],
        "sha256": _sha256(path),
    }


def _build_tiger_reaction(
    head: Image.Image, pupils: Image.Image
) -> list[Image.Image]:
    frames = []
    head_angles = (0.0, -0.8, -1.7, -1.7, 0.3, 0.0, 0.0)
    pupil_dx = (0, 0, -1, -2, -1, 1, 0)
    for angle, dx in zip(head_angles, pupil_dx):
        canvas = Image.new("RGBA", (FACE_SIZE, FACE_SIZE), (0, 0, 0, 0))
        posed_head = head.rotate(
            angle,
            center=(335, 233),
            resample=Image.Resampling.BICUBIC,
            expand=False,
        )
        canvas.alpha_composite(posed_head, (-1 if angle < -0.2 else 0, 0))
        pupil_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        pupil_layer.alpha_composite(pupils, (dx, 0))
        canvas.alpha_composite(pupil_layer)
        frames.append(canvas)
    return frames


def _animation_specs(
    large: tuple[Image.Image, tuple[float, float]],
    small: tuple[Image.Image, tuple[float, float]],
    small_flight: tuple[Image.Image, tuple[float, float]],
    hand_perch_anchors: dict[str, dict[str, tuple[int, int]]],
) -> dict[str, list[Image.Image]]:
    large_sprite, large_anchor = large
    small_sprite, small_anchor = small
    flight_sprite, flight_anchor = small_flight
    large_minute_anchor = hand_perch_anchors["MINUTE"]["LARGE"]
    small_minute_anchor = hand_perch_anchors["MINUTE"]["SMALL"]
    specs: dict[str, list[Image.Image]] = {}

    specs["magpie_large_fly_pine_to_hand"] = _pose_sequence(
        large_sprite,
        large_anchor,
        _curve((112, 166), large_minute_anchor, 8, 28),
        angles=(-5, -4, -2, 1, 3, 2, 0, 0),
        scale_y=(0.94, 0.98, 1.02, 1.05, 1.02, 0.98, 0.96, 1.0),
    )
    specs["magpie_large_land_on_hand"] = _pose_sequence(
        large_sprite,
        large_anchor,
        _curve(
            (large_minute_anchor[0], large_minute_anchor[1] - 15),
            large_minute_anchor,
            6,
            2,
        ),
        angles=(-3, -2, 1, 3, 1, 0),
        scale_y=(1.03, 1.01, 0.97, 0.94, 0.98, 1.0),
    )
    large_walk = _curve((94, 352), (151, 337), 8)
    specs["magpie_large_walk_step"] = _pose_sequence(
        large_sprite,
        large_anchor,
        [
            (x, y - (3 if index in {2, 5} else 0))
            for index, (x, y) in enumerate(large_walk)
        ],
        angles=(0, 2, 4, 1, -1, -3, -1, 0),
        scale_y=(1, 0.97, 1.02, 1, 0.97, 1.02, 1, 1),
    )
    specs["magpie_large_hop_to_tiger"] = _pose_sequence(
        large_sprite,
        large_anchor,
        _curve((281, 310), LARGE_TIGER_FOOT, 8, 24),
        angles=(0, -2, -4, -2, 2, 4, 2, 0),
    )
    specs["magpie_large_exit_right_jump"] = _pose_sequence(
        large_sprite,
        large_anchor,
        _curve(LARGE_TIGER_FOOT, (495, 175), 8, 26),
        angles=(0, -4, -7, -6, -3, 0, 2, 2),
    )
    specs["magpie_large_head_tilt"] = _pose_sequence(
        large_sprite,
        large_anchor,
        [LARGE_TIGER_FOOT] * 7,
        angles=(0, 1, 3, 4, 2, -1, 0),
    )
    specs["magpie_large_turn_perch"] = _pose_sequence(
        large_sprite,
        large_anchor,
        [(335, 233), (335, 231), (335, 229), (335, 229), (335, 231), (335, 233)],
        scale_x=(1.0, 0.62, 0.18, 0.18, 0.62, 1.0),
        mirrors=(False, False, False, True, True, True),
    )

    specs["magpie_small_fly_pine_to_hand"] = _pose_sequence(
        flight_sprite,
        flight_anchor,
        _curve((105, 169), small_minute_anchor, 8, 39),
        angles=(1, 0, -1, -1, 0, 1, 1, 0),
    )
    landing_points = _curve(
        (small_minute_anchor[0], small_minute_anchor[1] - 16),
        small_minute_anchor,
        7,
        3,
    )
    landing_frames = _pose_sequence(
        flight_sprite,
        flight_anchor,
        landing_points[:3],
        angles=(1, 0, 0),
    )
    landing_frames.extend(
        _pose_sequence(
            small_sprite,
            small_anchor,
            landing_points[3:],
            angles=(2, 1, 0, 0),
            scale_y=(0.94, 0.97, 1.02, 1.0),
            mirrors=(True, True, True, True),
        )
    )
    specs["magpie_small_land_on_hand"] = landing_frames
    small_walk = _curve((89, 354), (155, 336), 8)
    specs["magpie_small_walk_step"] = _pose_sequence(
        small_sprite,
        small_anchor,
        [
            (x, y - (2.2 if index in {2, 5} else 0))
            for index, (x, y) in enumerate(small_walk)
        ],
        angles=(0, -2, -4, -1, 1, 3, 1, 0),
    )
    specs["magpie_small_hop_to_tiger"] = _pose_sequence(
        small_sprite,
        small_anchor,
        _curve((284, 282), SMALL_TIGER_FOOT, 8, 25),
        angles=(0, 2, 4, 2, -2, -4, -2, 0),
        mirrors=(True,) * 8,
    )
    specs["magpie_small_head_scan"] = _pose_sequence(
        small_sprite,
        small_anchor,
        [SMALL_TIGER_FOOT] * 8,
        angles=(0, -3, -5, -2, 2, 5, 3, 0),
        mirrors=(True,) * 8,
    )
    specs["magpie_small_look_plum"] = _pose_sequence(
        small_sprite,
        small_anchor,
        [SMALL_TIGER_FOOT] * 7,
        angles=(0, 1, 4, 7, 5, 2, 0),
        mirrors=(True,) * 7,
    )
    specs["magpie_small_turn_hop"] = _pose_sequence(
        small_sprite,
        small_anchor,
        [
            (340, 241),
            (340, 239),
            (340, 236),
            (340, 236),
            (340, 239),
            (340, 241),
        ],
        scale_x=(1.0, 0.58, 0.16, 0.16, 0.58, 1.0),
        mirrors=(True, True, True, False, False, False),
    )
    specs["magpie_small_peck_tiger_ear"] = _pose_sequence(
        small_sprite,
        small_anchor,
        [
            (340, 241),
            (338, 243),
            (335, 247),
            (340, 241),
            (336, 246),
            (340, 241),
            (340, 241),
        ],
        angles=(0, 4, 10, 0, 9, 2, 0),
        mirrors=(True,) * 7,
    )
    return specs


def _plum_resources() -> list[dict[str, object]]:
    source_manifest_path = (
        REPO_ROOT / "assets/layers/source/environment/plum_battery_v23/manifest.json"
    )
    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    scale_x = FACE_SIZE / float(manifest["sourceCanvas"][0])
    scale_y = FACE_SIZE / float(manifest["sourceCanvas"][1])
    resources = []
    for entry in manifest["stages"]:
        stage = int(entry["stage"])
        resource_name = f"plum_battery_stage_{stage:02d}"
        asset = entry.get("asset")
        if asset:
            with Image.open(REPO_ROOT / str(asset)) as source:
                sprite = source.convert("RGBA")
            size = (
                max(1, round(sprite.width * scale_x)),
                max(1, round(sprite.height * scale_y)),
            )
            sprite = sprite.resize(size, Image.Resampling.LANCZOS)
            _save_png(sprite, DRAWABLE_DIR / f"{resource_name}.png")
        else:
            sprite = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            size = sprite.size
            _save_png(sprite, DRAWABLE_DIR / f"{resource_name}.png")
        position = entry["positionSource"]
        resources.append(
            {
                "stage": stage,
                "minimumPercent": int(entry["minimumPercent"]),
                "maximumPercent": int(entry["maximumPercent"]),
                "resource": f"{resource_name}.png",
                "placementLogical": [
                    round(float(position[0]) * scale_x),
                    round(float(position[1]) * scale_y),
                ],
                "sizeLogical": list(size),
            }
        )
    return resources


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    center_x: float = FACE_SIZE / 2,
) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    draw.text((center_x - width / 2, y), text, font=font, fill=fill)


def _build_battery_icon() -> None:
    icon = Image.new("RGBA", (22, 14), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    ink = (31, 24, 17, 255)
    draw.rounded_rectangle((1, 1, 18, 12), radius=2, outline=ink, width=2)
    draw.rectangle((19, 4, 21, 9), fill=ink)
    draw.rectangle((4, 4, 15, 9), fill=ink)
    _save_png(icon, DRAWABLE_DIR / "battery_icon.png")


def _build_readout_hanji_patch(background: Image.Image) -> dict[str, object]:
    """Build a final date backing that sits above every decorative layer."""
    x0, y0, x1, y1 = DATE_HANJI_OVERLAY_BOUNDS
    patch = background.crop(DATE_HANJI_OVERLAY_BOUNDS).convert("RGBA")
    height, width = patch.height, patch.width
    yy, xx = np.indices((height, width))
    edge_distance = np.minimum.reduce((xx, yy, width - 1 - xx, height - 1 - yy))
    alpha = np.clip(edge_distance.astype(np.float32) / 2.0, 0.0, 1.0)
    alpha = alpha * alpha * (3.0 - 2.0 * alpha)
    values = np.asarray(patch, dtype=np.uint8).copy()
    values[..., 3] = np.clip(alpha * 255, 0, 255).astype(np.uint8)
    patch = Image.fromarray(values, "RGBA")
    path = DRAWABLE_DIR / "hojakdo_v4_readout_hanji_patch.png"
    _save_png(patch, path)
    return {
        "resource": path.name,
        "placementLogical": [x0, y0],
        "sizeLogical": [x1 - x0, y1 - y0],
        "sha256": _sha256(path),
        "layer": "above_background_below_hands_and_decorations",
        "ambientBehavior": "hidden_clean_background_remains",
    }


def _compose_preview_face(
    background: Image.Image,
    hour_branch: Image.Image,
    minute_branch: Image.Image,
    tiger_head: Image.Image,
    tiger_pupils: Image.Image,
    small_flight: tuple[Image.Image, tuple[float, float]],
    plum: list[dict[str, object]],
    masks: list[dict[str, object]],
    hour: int,
    minute: int,
    battery_percent: int = 85,
) -> Image.Image:
    face = background.convert("RGBA")
    # The hanji backing belongs directly above the repaired background. Hands,
    # characters, masks, and live text must all remain visible above it.
    with Image.open(DRAWABLE_DIR / "hojakdo_v4_readout_hanji_patch.png") as source:
        face.alpha_composite(
            source.convert("RGBA"), DATE_HANJI_OVERLAY_BOUNDS[:2]
        )

    # Restore the plum branches and flowers first. Both clock hands must remain
    # above the complete bloom or they disappear through the left half-dial.
    masks_by_name = {str(mask["id"]): mask for mask in masks}
    plum_mask = masks_by_name["plum_foreground_mask"]
    with Image.open(DRAWABLE_DIR / str(plum_mask["resource"])) as source:
        face.alpha_composite(
            source.convert("RGBA"), tuple(plum_mask["placementLogical"])
        )
    selected_plum = next(
        item
        for item in plum
        if int(item["minimumPercent"])
        <= battery_percent
        <= int(item["maximumPercent"])
    )
    with Image.open(DRAWABLE_DIR / str(selected_plum["resource"])) as source:
        face.alpha_composite(
            source.convert("RGBA"), tuple(selected_plum["placementLogical"])
        )

    for name in ("pine_foreground_mask", "tiger_body_foreground_mask"):
        mask = masks_by_name[name]
        with Image.open(DRAWABLE_DIR / str(mask["resource"])) as source:
            face.alpha_composite(
                source.convert("RGBA"), tuple(mask["placementLogical"])
            )
    face.alpha_composite(tiger_head)
    face.alpha_composite(tiger_pupils)

    # Match production: every environmental mask and the tiger resolve below
    # the hands, so neither branch can disappear at any rotation.
    hour_angle = (hour * 60 + minute) * 0.5 - 50.232272878132
    minute_angle = (hour * 60 + minute) * 6.0 - 325.271003720479
    face.alpha_composite(
        hour_branch.rotate(
            -hour_angle,
            center=PIVOT,
            resample=Image.Resampling.BICUBIC,
            expand=False,
        )
    )
    face.alpha_composite(
        minute_branch.rotate(
            -minute_angle,
            center=PIVOT,
            resample=Image.Resampling.BICUBIC,
            expand=False,
        )
    )
    bird, anchor = small_flight
    face.alpha_composite(bird, (round(357 - anchor[0]), round(156 - anchor[1])))

    draw = ImageDraw.Draw(face)
    ink = (31, 24, 17, 255)
    _draw_centered(
        draw,
        READOUT_TIME_Y,
        f"{hour:02d}:{minute:02d}",
        _font(READOUT_TIME_FONT_SIZE, bold=True),
        ink,
        READOUT_CENTER_X,
    )
    _draw_centered(
        draw,
        READOUT_DATE_WEEKDAY_Y,
        f"07.15{READOUT_DATE_WEEKDAY_SEPARATOR}WED",
        _font(READOUT_DATE_WEEKDAY_FONT_SIZE, bold=True),
        ink,
        READOUT_CENTER_X,
    )
    battery_font = _font(12, bold=True)
    battery_text = f"{battery_percent}%"
    battery_box = draw.textbbox((0, 0), battery_text, font=battery_font)
    battery_width = battery_box[2] - battery_box[0]
    text_x = BATTERY_TEXT_CENTER_X - battery_width / 2
    icon_x, icon_y = BATTERY_ICON_POSITION
    draw.rounded_rectangle(
        (icon_x + 1, icon_y + 1, icon_x + 18, icon_y + 12),
        radius=2,
        outline=ink,
        width=2,
    )
    draw.rectangle((icon_x + 19, icon_y + 4, icon_x + 21, icon_y + 9), fill=ink)
    draw.rectangle((icon_x + 4, icon_y + 4, icon_x + 15, icon_y + 9), fill=ink)
    draw.text((text_x, BATTERY_TEXT_Y), battery_text, font=battery_font, fill=ink)
    return face


def _render_preview(
    background: Image.Image,
    hour_branch: Image.Image,
    minute_branch: Image.Image,
    tiger_head: Image.Image,
    tiger_pupils: Image.Image,
    small_flight: tuple[Image.Image, tuple[float, float]],
    plum: list[dict[str, object]],
    masks: list[dict[str, object]],
) -> None:
    face = _compose_preview_face(
        background,
        hour_branch,
        minute_branch,
        tiger_head,
        tiger_pupils,
        small_flight,
        plum,
        masks,
        14,
        18,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    static_path = OUTPUT_DIR / "hojakdo_v4_integrated_static.png"
    _save_rgb_png(face, static_path)

    # Dedicated cleanup inspection: both calibrated branch hands point to
    # twelve, leaving the complete live readout zone unobstructed.
    hands_up = _compose_preview_face(
        background,
        hour_branch,
        minute_branch,
        tiger_head,
        tiger_pupils,
        small_flight,
        plum,
        masks,
        12,
        0,
    )
    _save_rgb_png(
        hands_up, OUTPUT_DIR / "hojakdo_v4_readout_cleanup_review.png"
    )

    # Reproduce the first emulator report: 05:24, battery 100%. This single
    # frame exposes all three regressions (rear-leg ghost, clipped hands, and
    # the hidden full-bloom layer) without depending on an Android renderer.
    emulator_review = _compose_preview_face(
        background,
        hour_branch,
        minute_branch,
        tiger_head,
        tiger_pupils,
        small_flight,
        plum,
        masks,
        5,
        24,
        battery_percent=100,
    )
    _save_rgb_png(
        emulator_review,
        OUTPUT_DIR / "hojakdo_v4_emulator_regression_review.png",
    )

    board = Image.new("RGB", (940, 540), (20, 17, 13))
    board.paste(face.convert("RGB").resize((500, 500), Image.Resampling.LANCZOS), (20, 20))
    info = ImageDraw.Draw(board)
    info.text((555, 42), "HOJAKDO V4.3.1", font=_font(29, bold=True), fill=(246, 226, 180))
    info.text((555, 91), "TOP READOUT + HANDS", font=_font(15, bold=True), fill=(194, 76, 42))
    info.line((555, 126, 900, 126), fill=(87, 72, 50), width=1)
    lines = (
        "SMALL FLIGHT 70 x 54",
        "HOUR HAND +24% / -12%",
        "TITLE + SEAL INSIDE DIAL",
        "LIVE TIME / DATE / WEEKDAY",
        "LIVE BATTERY / 5 PLUM STAGES",
        "16 AGIF / 6 STATIC POSES / 3 MASKS",
        "DETERMINISTIC 43-MINUTE SCENE",
        "AMBIENT-SAFE STATIC FALLBACK",
    )
    y = 158
    for line in lines:
        info.ellipse((555, y + 5, 564, y + 14), fill=(181, 68, 41))
        info.text((578, y), line, font=_font(12), fill=(226, 207, 168))
        y += 39
    info.text((555, 485), "V4.3.1 VISIBILITY RESTORE", font=_font(11), fill=(129, 119, 101))
    _save_rgb_png(board, OUTPUT_DIR / "hojakdo_v4_review_board.png")


def _render_catalog(animations: list[dict[str, object]]) -> None:
    columns = 4
    tile_width = 260
    tile_height = 185
    rows = math.ceil(len(animations) / columns)
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), (24, 21, 17))
    draw = ImageDraw.Draw(sheet)
    for index, metadata in enumerate(animations):
        column = index % columns
        row = index // columns
        x0 = column * tile_width
        y0 = row * tile_height
        draw.rounded_rectangle(
            (x0 + 6, y0 + 6, x0 + tile_width - 6, y0 + tile_height - 6),
            radius=10,
            fill=(38, 33, 26),
            outline=(75, 62, 44),
        )
        name = str(metadata["id"])
        frames = sorted((FRAME_DIR / name).glob("frame_*.png"))
        picks = (frames[0], frames[len(frames) // 2], frames[-1])
        for pick_index, path in enumerate(picks):
            with Image.open(path) as source:
                frame = source.convert("RGBA")
            frame.thumbnail((70, 102), Image.Resampling.LANCZOS)
            px = x0 + 10 + pick_index * 81 + (70 - frame.width) // 2
            py = y0 + 42 + (102 - frame.height) // 2
            sheet.paste(frame, (px, py), frame)
        draw.text((x0 + 13, y0 + 14), name, font=_font(10, bold=True), fill=(235, 216, 177))
        draw.text(
            (x0 + 13, y0 + 156),
            f"{metadata['frameCount']}f / {metadata['sizeLogical'][0]}x{metadata['sizeLogical'][1]}",
            font=_font(9),
            fill=(151, 139, 118),
        )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _save_rgb_png(sheet, OUTPUT_DIR / "hojakdo_v4_animation_catalog.png")


def build() -> dict[str, object]:
    for directory in (DRAWABLE_DIR, ANIMATION_DIR, FRAME_DIR, OUTPUT_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    calculator = HojakdoSceneCalculator()
    renderer = PrototypeRenderer(calculator)
    background = _remove_embedded_ui(
        _repair_tiger_hind_leg_ghost(_polished_background(renderer.background))
    )
    hour_source = _polished_hour_hand(
        renderer.hour_branch, PIVOT, HOUR_POLISH_ANCHOR
    )
    hour_source = ImageEnhance.Brightness(hour_source).enhance(
        HOUR_HAND_BRIGHTNESS / V4_BASE_HOUR_BRIGHTNESS
    )
    hour_transform = _hand_length_transform(
        hour_source, HOUR_HAND_TARGET_LENGTH
    )
    minute_source = renderer.minute_branch.copy()
    minute_transform = _hand_length_transform(
        minute_source, MINUTE_HAND_TARGET_LENGTH
    )
    hour_branch = _apply_hand_length_transform(hour_source, hour_transform)
    minute_branch = _apply_hand_length_transform(minute_source, minute_transform)
    hand_perch_anchors = _mapped_hand_perch_anchors(
        hour_transform, minute_transform
    )
    tiger_head = renderer.tiger_head.copy()
    tiger_pupils = renderer.tiger_pupils.copy()

    _save_png(background.convert("RGBA"), DRAWABLE_DIR / "hojakdo_v4_background.png")
    _save_png(hour_branch, DRAWABLE_DIR / "hojakdo_v4_hour_branch.png")
    _save_png(minute_branch, DRAWABLE_DIR / "hojakdo_v4_minute_branch.png")
    _save_png(tiger_head, DRAWABLE_DIR / "hojakdo_v4_tiger_head.png")
    _save_png(tiger_pupils, DRAWABLE_DIR / "hojakdo_v4_tiger_pupils.png")
    _build_battery_icon()
    readout_hanji_patch = _build_readout_hanji_patch(background)

    large_sprite, large_anchor, _ = renderer.birds["LARGE"]
    small_sprite, small_anchor, _ = renderer.birds["SMALL"]
    old_flight, old_flight_anchor = renderer.small_exit_bird
    small_height = round(old_flight.height * SMALL_FLIGHT_WIDTH / old_flight.width)
    small_flight_sprite = old_flight.resize(
        (SMALL_FLIGHT_WIDTH, small_height), Image.Resampling.LANCZOS
    )
    small_flight_anchor = (
        old_flight_anchor[0] * SMALL_FLIGHT_WIDTH / old_flight.width,
        old_flight_anchor[1] * small_height / old_flight.height,
    )
    _save_png(small_flight_sprite, DRAWABLE_DIR / "magpie_small_flight_right_v4.png")

    static_poses = [
        _static_pose("magpie_large_perch_hand", large_sprite, large_anchor),
        _static_pose(
            "magpie_large_walk_idle", large_sprite, large_anchor, angle=1.8, scale_y=0.98
        ),
        _static_pose(
            "magpie_large_perch_tiger", large_sprite, large_anchor, angle=-2.0
        ),
        _static_pose(
            "magpie_small_perch_hand", small_sprite, small_anchor, mirror=True
        ),
        _static_pose(
            "magpie_small_walk_idle", small_sprite, small_anchor, angle=-1.8
        ),
        _static_pose(
            "magpie_small_perch_tiger", small_sprite, small_anchor, mirror=True, angle=2.0
        ),
    ]

    masks = [
        _foreground_mask(
            "plum_foreground_mask",
            background,
            (0, 226, 205, 450),
            ((0, 235), (180, 235), (205, 450), (0, 450)),
            158,
        ),
        _foreground_mask(
            "pine_foreground_mask",
            background,
            (0, 0, 220, 260),
            ((0, 0), (220, 0), (205, 200), (145, 260), (0, 260)),
            151,
        ),
        _foreground_mask(
            "tiger_body_foreground_mask",
            background,
            (184, 269, 450, 450),
            ((215, 300), (365, 275), (450, 300), (450, 450), (184, 450)),
            169,
        ),
    ]

    specs = _animation_specs(
        (large_sprite, large_anchor),
        (small_sprite, small_anchor),
        (small_flight_sprite, small_flight_anchor),
        hand_perch_anchors,
    )
    specs["tiger_head_eye_reaction"] = _build_tiger_reaction(
        tiger_head, tiger_pupils
    )
    animations = [_write_animation(name, frames) for name, frames in specs.items()]
    plum = _plum_resources()

    static_decoded = sum(
        _decoded_image_bytes(path) for path in DRAWABLE_DIR.glob("*.png")
    )
    animation_decoded = sum(int(item["decodedBytesEstimate"]) for item in animations)
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "version": "4.3.1",
        "status": "v4_3_1_stateless_visibility_reentry_fix",
        "logicalCanvas": [FACE_SIZE, FACE_SIZE],
        "smallFlight": {
            "resource": "magpie_small_flight_right_v4.png",
            "sizeLogical": list(small_flight_sprite.size),
            "anchorLogical": [round(value, 3) for value in small_flight_anchor],
            "source": "assets/layers/mvp/magpie_small_flight_right_v31.png",
            "motion": "fixed_whole_sprite_translation",
            "wingFlaps": 0,
        },
        "hourHandPolish": {
            "perpendicularThickness": 1.24,
            "brightness": HOUR_HAND_BRIGHTNESS,
            "pivot": list(PIVOT),
            "sourceRadialLength": round(hour_transform.source_length, 3),
            "targetRadialLength": HOUR_HAND_TARGET_LENGTH,
            "longitudinalScale": round(hour_transform.scale, 6),
            "landingAnchorsAtZero": {
                character: list(anchor)
                for character, anchor in hand_perch_anchors["HOUR"].items()
            },
        },
        "minuteHandPolish": {
            "perpendicularThickness": 1.0,
            "brightness": 1.0,
            "pivot": list(PIVOT),
            "sourceRadialLength": round(minute_transform.source_length, 3),
            "targetRadialLength": MINUTE_HAND_TARGET_LENGTH,
            "longitudinalScale": round(minute_transform.scale, 6),
            "landingAnchorsAtZero": {
                character: list(anchor)
                for character, anchor in hand_perch_anchors["MINUTE"].items()
            },
        },
        "titleSealShiftLogical": [-20, -3],
        "backgroundCleanup": {
            "pineSprigBoundsLogical": list(PINE_SPRIG_CLEANUP_BOUNDS),
            "tigerHindLegGhostBoundsLogical": list(
                TIGER_HIND_LEG_GHOST_BOUNDS
            ),
            "method": "color_matched_paper_texture_and_scaled_tiger_source",
        },
        "readoutHanjiPatch": readout_hanji_patch,
        "readoutLayout": {
            "layout": "top_two_rows_time_then_date_weekday",
            "centerXLogical": READOUT_CENTER_X,
            "zOrder": "above_hands_birds_and_animations",
            "time": {
                "yLogical": READOUT_TIME_Y,
                "fontSize": READOUT_TIME_FONT_SIZE,
                "wffBoundsLogical": list(READOUT_TIME_WFF_BOUNDS),
            },
            "dateWeekday": {
                "yLogical": READOUT_DATE_WEEKDAY_Y,
                "fontSize": READOUT_DATE_WEEKDAY_FONT_SIZE,
                "separator": READOUT_DATE_WEEKDAY_SEPARATOR,
                "wffBoundsLogical": list(READOUT_DATE_WEEKDAY_WFF_BOUNDS),
            },
        },
        "readoutQuietZone": {
            "sourceCleanupBoundsLogical": [175, 220, 275, 295],
            "dateCloudCleanupBoundsLogical": list(DATE_CLOUD_CLEANUP_BOUNDS),
            "dateFinalOverlayBoundsLogical": list(DATE_HANJI_OVERLAY_BOUNDS),
            "liveTextCenterXLogical": READOUT_CENTER_X,
            "removes": ["baked_time", "baked_date", "baked_weekday", "cloud_line"],
            "liveTextLayer": "topmost",
        },
        "staticPoses": static_poses,
        "foregroundMasks": masks,
        "animations": animations,
        "plumBatteryStages": plum,
        "plumBatteryLayer": "above_plum_foreground_mask_below_hands",
        "scene": {
            "cycleMinutes": 43,
            "cycleOffsetMinutes": 32,
            "characterAlternation": "cycle_index_mod_2",
            "handRouteSchedule": {
                "periodCycles": 11,
                "hourRouteRemainder": 0,
                "minuteRouteRemainder": 5,
                "otherRoute": "plum_walk",
                "estimatedHandLandingsPerDay": round(1440 / 43 * 2 / 11, 3),
            },
            "tigerPerchAnchors": {
                "LARGE": [round(value, 3) for value in LARGE_TIGER_FOOT],
                "SMALL": [round(value, 3) for value in SMALL_TIGER_FOOT],
            },
            "handPerchAnchorsAtZero": {
                hand: {
                    character: list(anchor)
                    for character, anchor in anchors.items()
                }
                for hand, anchors in hand_perch_anchors.items()
            },
            "layerOrder": [
                "background",
                "readout_hanji_patch",
                "plum_foreground_mask",
                "plum_battery_stage",
                "plum_birds",
                "pine_foreground_mask",
                "tiger_body_foreground_mask",
                "tiger_head_or_reaction",
                "hour_hand",
                "minute_hand",
                "tiger_birds_and_exit",
                "bird_animations",
                "live_text",
            ],
            "stateless": True,
        },
        "liveData": [
            "HOUR_0_23_Z",
            "MINUTE_Z",
            "MONTH_Z",
            "DAY_Z",
            "DAY_OF_WEEK_S",
            "BATTERY_PERCENT",
            "YEAR",
            "DAY_OF_YEAR",
            "HOUR_0_23",
            "MINUTE",
            "MINUTE_SECOND",
            "SECOND_MILLISECOND",
        ],
        "memoryEstimate": {
            "staticDecodedBytes": static_decoded,
            "animatedDecodedBytes": animation_decoded,
            "interactiveDecodedBytes": static_decoded + animation_decoded,
            "officialInteractiveBudgetBytes": 100 * 1024 * 1024,
            "officialAmbientBudgetBytes": 10 * 1024 * 1024,
        },
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _render_preview(
        background,
        hour_branch,
        minute_branch,
        tiger_head,
        tiger_pupils,
        (small_flight_sprite, small_flight_anchor),
        plum,
        masks,
    )
    _render_catalog(animations)
    return manifest


def main() -> None:
    manifest = build()
    memory = manifest["memoryEstimate"]
    print(MANIFEST_PATH)
    print(OUTPUT_DIR / "hojakdo_v4_integrated_static.png")
    print(OUTPUT_DIR / "hojakdo_v4_readout_cleanup_review.png")
    print(OUTPUT_DIR / "hojakdo_v4_emulator_regression_review.png")
    print(OUTPUT_DIR / "hojakdo_v4_review_board.png")
    print(OUTPUT_DIR / "hojakdo_v4_animation_catalog.png")
    print(
        f"animations={len(manifest['animations'])} "
        f"staticPoses={len(manifest['staticPoses'])} "
        f"masks={len(manifest['foregroundMasks'])} "
        f"decoded={memory['interactiveDecodedBytes'] / 1024 / 1024:.2f}MiB"
    )


if __name__ == "__main__":
    main()

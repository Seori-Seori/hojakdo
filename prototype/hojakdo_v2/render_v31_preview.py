from __future__ import annotations

import argparse
import math
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance
from scipy import ndimage

from .render_prototype import FONT_SMALL, FONT_TINY, PrototypeRenderer, _font
from .scene_calculator import CyclePlan, HojakdoSceneCalculator


PACKAGE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PACKAGE_DIR / "output"
DEFAULT_FINAL = OUTPUT_DIR / "hojakdo_v31_integrated_final.png"

FONT_HEADING = _font(26, bold=True)
FONT_STAGE = _font(18, bold=True)

HOUR_HAND_THICKNESS = 1.24
HOUR_HAND_BRIGHTNESS = 0.88
TITLE_SEAL_SHIFT = (-20, -3)


def _polished_hour_hand(
    layer: Image.Image,
    pivot: tuple[float, float],
    anchor: tuple[float, float],
) -> Image.Image:
    """Thicken only across the branch while keeping its length and anchor fixed."""
    dx = anchor[0] - pivot[0]
    dy = anchor[1] - pivot[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    vx, vy = -uy, ux
    inverse_scale = 1.0 / HOUR_HAND_THICKNESS

    # Inverse affine for a 1.24x stretch on the branch's perpendicular axis.
    a = ux * ux + inverse_scale * vx * vx
    b = ux * uy + inverse_scale * vx * vy
    d = uy * ux + inverse_scale * vy * vx
    e = uy * uy + inverse_scale * vy * vy
    c = pivot[0] - a * pivot[0] - b * pivot[1]
    f = pivot[1] - d * pivot[0] - e * pivot[1]

    darkened = ImageEnhance.Brightness(layer.convert("RGBA")).enhance(
        HOUR_HAND_BRIGHTNESS
    )
    return darkened.transform(
        darkened.size,
        Image.Transform.AFFINE,
        (a, b, c, d, e, f),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )


def _kept_dark_components(luminance: np.ndarray, box: tuple[int, ...]) -> np.ndarray:
    x0, y0, x1, y1 = box
    core = luminance[y0:y1, x0:x1] < 95.0
    labels, count = ndimage.label(core, structure=np.ones((3, 3), dtype=bool))
    kept = np.zeros_like(core)
    for index in range(1, count + 1):
        component = labels == index
        if int(component.sum()) < 2:
            continue
        if (
            component[0].any()
            or component[-1].any()
            or component[:, 0].any()
            or component[:, -1].any()
        ):
            continue
        kept |= component
    support = ndimage.binary_dilation(kept, iterations=2)
    result = np.zeros_like(luminance, dtype=np.float32)
    result[y0:y1, x0:x1] = support
    return result


def _polished_background(background: Image.Image) -> Image.Image:
    """Move the embedded title and seal left/up without covering nearby artwork."""
    rgb = np.asarray(background.convert("RGB"), dtype=np.uint8)
    values = rgb.astype(np.float32)
    luminance = (
        0.2126 * values[:, :, 0]
        + 0.7152 * values[:, :, 1]
        + 0.0722 * values[:, :, 2]
    )

    title_support = np.zeros_like(luminance, dtype=np.float32)
    for box in (
        (396, 265, 427, 294),
        (397, 291, 427, 320),
        (398, 317, 424, 343),
    ):
        title_support = np.maximum(
            title_support, _kept_dark_components(luminance, box)
        )
    yy, xx = np.indices(luminance.shape)
    inside_circle = (xx - 225.0) ** 2 + (yy - 225.0) ** 2 <= 224.0**2
    title_alpha = title_support * np.clip(
        (175.0 - luminance) / 22.0, 0.0, 1.0
    )
    title_alpha *= inside_circle

    red = values[:, :, 0]
    green = values[:, :, 1]
    blue = values[:, :, 2]
    seal_box = (394, 341, 425, 371)
    x0, y0, x1, y1 = seal_box
    seal_core = (
        (red[y0:y1, x0:x1] > 65.0)
        & (red[y0:y1, x0:x1] > green[y0:y1, x0:x1] * 1.5)
        & (red[y0:y1, x0:x1] > blue[y0:y1, x0:x1] * 1.8)
        & (luminance[y0:y1, x0:x1] < 150.0)
    )
    labels, count = ndimage.label(
        seal_core, structure=np.ones((3, 3), dtype=bool)
    )
    if count:
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        seal_core = labels == int(np.argmax(sizes))
    seal_support_local = ndimage.binary_dilation(seal_core, iterations=1)
    seal_support = np.zeros_like(luminance, dtype=np.float32)
    seal_support[y0:y1, x0:x1] = seal_support_local
    red_ratio = red / np.maximum(green, 1.0)
    seal_alpha = seal_support * np.clip(
        (red_ratio - 1.32) / 0.16, 0.0, 1.0
    )
    seal_alpha *= np.clip((175.0 - luminance) / 22.0, 0.0, 1.0)

    element_alpha = np.maximum(title_alpha, seal_alpha)

    # Transplant a clean strip from the same upper-right hanji field. It keeps
    # the original paper grain while removing the old embedded title and seal.
    source_patch = values[145:261, 393:430]
    target_x0, target_y0, target_x1, target_y1 = (393, 260, 430, 376)
    patch_canvas = values.copy()
    local_circle = np.clip(
        224.5
        - np.sqrt(
            (xx[target_y0:target_y1, target_x0:target_x1] - 225.0) ** 2
            + (yy[target_y0:target_y1, target_x0:target_x1] - 225.0) ** 2
        ),
        0.0,
        1.0,
    )
    patch_canvas[target_y0:target_y1, target_x0:target_x1] = (
        source_patch * local_circle[:, :, None]
    )
    patch_mask = np.zeros_like(luminance, dtype=np.float32)
    patch_mask[target_y0:target_y1, target_x0:target_x1] = 1.0
    patch_mask = ndimage.gaussian_filter(patch_mask, sigma=3.2)
    cleaned = np.clip(
        values * (1.0 - patch_mask[:, :, None])
        + patch_canvas * patch_mask[:, :, None],
        0,
        255,
    ).astype(np.uint8)

    element = Image.fromarray(rgb, "RGB").convert("RGBA")
    element.putalpha(
        Image.fromarray(np.clip(element_alpha * 255.0, 0, 255).astype(np.uint8), "L")
    )
    shift_x, shift_y = TITLE_SEAL_SHIFT
    moved = element.transform(
        element.size,
        Image.Transform.AFFINE,
        (1.0, 0.0, -shift_x, 0.0, 1.0, -shift_y),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )
    result = Image.fromarray(cleaned, "RGB").convert("RGBA")
    result.alpha_composite(moved)
    return result.convert("RGB")


def _small_exit_plan(
    calculator: HojakdoSceneCalculator, source_date: date
) -> CyclePlan:
    start = datetime.combine(source_date, datetime.min.time())
    first = calculator.cycle_index_at(start)
    return next(
        calculator.plan_cycle(first + offset)
        for offset in range(8)
        if calculator.character_for_cycle(first + offset) == "SMALL"
    )


def _review_timestamp(plan: CyclePlan) -> datetime:
    exit_phase = plan.phases[-1]
    # The accepted review pose is most legible just after takeoff. This is a
    # single still, not an integrated GIF; the full path is covered by tests.
    return plan.cycle_start + timedelta(
        minutes=exit_phase.start + exit_phase.duration * 0.24
    )


def render_final_combination(source_date: date, output_path: Path) -> None:
    calculator = HojakdoSceneCalculator()
    renderer = PrototypeRenderer(calculator)
    renderer.background = _polished_background(renderer.background)
    renderer.hour_branch = _polished_hour_hand(
        renderer.hour_branch,
        tuple(float(value) for value in renderer.geometry["clockPivot"]),
        tuple(
            float(value)
            for value in renderer.geometry["hourHandAnchorAtZero"]["SMALL"]
        ),
    )
    timestamp = _review_timestamp(_small_exit_plan(calculator, source_date))
    snapshot = calculator.snapshot(timestamp)
    if snapshot.character != "SMALL" or snapshot.state != "EXIT_RIGHT":
        raise RuntimeError("V3.1 review timestamp is not a small-magpie exit")

    face = renderer.render_face(
        timestamp,
        snapshot,
        guides=False,
        clock_label=False,
        battery_percent=85,
    ).convert("RGB")

    board = Image.new("RGB", (900, 520), (22, 19, 15))
    draw = ImageDraw.Draw(board)
    board.paste(face.resize((480, 480), Image.Resampling.LANCZOS), (20, 20))

    draw.text((535, 38), "HOJAKDO V3.1", font=FONT_HEADING, fill=(246, 226, 180))
    draw.text((535, 80), "85% / FULL BLOOM", font=FONT_STAGE, fill=(202, 83, 47))
    draw.line((535, 118, 862, 118), fill=(85, 72, 52), width=1)
    lines = (
        "FIXED SMALL-MAGPIE FLIGHT",
        "ZERO WING FLAPS",
        "48PX ARC / SMOOTHSTEP",
        "5 STATIC PLUM STAGES",
        "TIME + WEEKDAY LAYOUT KEPT",
        "BATTERY NUMBER KEPT",
    )
    y = 148
    for line in lines:
        draw.ellipse((535, y + 3, 545, y + 13), fill=(181, 68, 41))
        draw.text((560, y), line, font=FONT_SMALL, fill=(225, 205, 165))
        y += 43
    draw.text(
        (535, 446),
        "STATIC INTEGRATION / 16 AGIF + WFF NOT CONNECTED",
        font=FONT_TINY,
        fill=(126, 117, 100),
    )
    draw.text(
        (535, 466),
        "NO INTEGRATED GIF PRODUCED",
        font=FONT_TINY,
        fill=(126, 117, 100),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    board.save(output_path, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the approved Hojakdo V3.1 integrated still"
    )
    parser.add_argument("--date", default="2026-07-15")
    parser.add_argument("--final", type=Path, default=DEFAULT_FINAL)
    args = parser.parse_args()
    render_final_combination(date.fromisoformat(args.date), args.final)
    print(args.final)


if __name__ == "__main__":
    main()

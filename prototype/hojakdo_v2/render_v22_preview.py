from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from .render_prototype import (
    FONT_BODY_BOLD,
    FONT_SMALL,
    FONT_TINY,
    PrototypeRenderer,
    _find_detail_plans,
    _font,
)
from .scene_calculator import HojakdoSceneCalculator


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = PACKAGE_DIR / "output" / "hojakdo_v22_final_combination.png"
BOARD_SIZE = (1280, 760)
FONT_BOARD_TITLE = _font(24, bold=True)
FONT_CARD_TITLE = _font(16, bold=True)


def _render_at(
    renderer: PrototypeRenderer, timestamp: datetime
) -> tuple[Image.Image, tuple[float, float] | None]:
    snapshot = renderer.calculator.snapshot(timestamp)
    return (
        renderer.render_face(
            timestamp, snapshot, guides=False, clock_label=False
        ).convert("RGB"),
        snapshot.foot_position,
    )


def _crop_around(
    image: Image.Image,
    center: tuple[float, float],
    size: tuple[int, int],
    vertical_bias: int = 0,
) -> Image.Image:
    width, height = size
    x = int(round(center[0] - width / 2))
    y = int(round(center[1] - height / 2 + vertical_bias))
    x = max(0, min(image.width - width, x))
    y = max(0, min(image.height - height, y))
    return image.crop((x, y, x + width, y + height))


def _card(
    board: Image.Image,
    box: tuple[int, int, int, int],
    title: str,
    subtitle: str,
    visual: Image.Image,
) -> None:
    draw = ImageDraw.Draw(board)
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=16, fill=(38, 34, 28), outline=(85, 72, 52), width=1)
    draw.text((left + 16, top + 12), title, font=FONT_CARD_TITLE, fill=(246, 226, 180))
    draw.text((left + 16, top + 34), subtitle, font=FONT_TINY, fill=(173, 163, 145))
    available = (right - left - 24, bottom - top - 66)
    fitted = visual.copy()
    fitted.thumbnail(available, Image.Resampling.LANCZOS)
    x = left + (right - left - fitted.width) // 2
    y = top + 56 + (bottom - top - 56 - fitted.height) // 2
    board.paste(fitted, (x, y))


def render_preview(source_date: date, output_path: Path) -> None:
    calculator = HojakdoSceneCalculator()
    renderer = PrototypeRenderer(calculator)
    large, small = _find_detail_plans(
        calculator, datetime.combine(source_date, datetime.min.time())
    )

    small_hour, small_hour_foot = _render_at(
        renderer, small.cycle_start + timedelta(minutes=9)
    )
    small_minute, _ = _render_at(
        renderer, small.cycle_start + timedelta(minutes=24)
    )
    large_minute, large_minute_foot = _render_at(
        renderer, large.cycle_start + timedelta(minutes=24)
    )
    if small_hour_foot is None or large_minute_foot is None:
        raise RuntimeError("Preview sample did not place a magpie on a hand")

    board = Image.new("RGB", BOARD_SIZE, (22, 19, 15))
    draw = ImageDraw.Draw(board)
    draw.text(
        (30, 22),
        "HOJAKDO V2.2  /  ONE FINAL COMBINATION",
        font=FONT_BOARD_TITLE,
        fill=(246, 226, 180),
    )
    draw.text(
        (30, 51),
        "TIGER 94%   |   LARGE MAGPIE 96%   |   SMALL MAGPIE: 2 px HAND-TIP CONTACT",
        font=FONT_SMALL,
        fill=(176, 165, 145),
    )

    main_box = (30, 82, 654, 706)
    draw.rounded_rectangle(
        main_box, radius=18, fill=(8, 8, 7), outline=(85, 72, 52), width=1
    )
    main = small_minute.resize((600, 600), Image.Resampling.LANCZOS)
    board.paste(main, (42, 94))
    draw.text(
        (46, 674),
        "MAIN STATE  /  SMALL MAGPIE ON MINUTE HAND",
        font=FONT_BODY_BOLD,
        fill=(239, 226, 195),
    )

    small_hour_crop = _crop_around(
        small_hour, small_hour_foot, (130, 130), vertical_bias=-18
    )
    large_crop = _crop_around(
        large_minute, large_minute_foot, (165, 165), vertical_bias=-24
    )
    tiger_crop = small_minute.crop((190, 200, 430, 440))

    _card(
        board,
        (680, 82, 952, 362),
        "SMALL / HOUR HAND",
        "Individual end anchor; 2 px overlap",
        small_hour_crop,
    )
    _card(
        board,
        (972, 82, 1244, 362),
        "LARGE / 96%",
        "Same perch geometry; size only",
        large_crop,
    )
    _card(
        board,
        (680, 382, 1244, 706),
        "TIGER GROUP / 94%",
        "Body, head, pupils, approach and perch aligned as one group",
        tiger_crop,
    )

    draw.text(
        (30, 727),
        "LOCAL REVIEW ONLY  /  no timing, route, motion, or remote GitHub changes",
        font=FONT_TINY,
        fill=(124, 117, 105),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    board.save(output_path, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render one Hojakdo V2.2 geometry candidate")
    parser.add_argument("--date", default="2026-07-15")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    render_preview(date.fromisoformat(args.date), args.output)
    print(args.output)


if __name__ == "__main__":
    main()

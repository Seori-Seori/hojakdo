from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from .render_prototype import FONT_SMALL, FONT_TINY, PrototypeRenderer, _font
from .scene_calculator import CyclePlan, HojakdoSceneCalculator


PACKAGE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PACKAGE_DIR / "output"
DEFAULT_FINAL = OUTPUT_DIR / "hojakdo_v31_integrated_final.png"

FONT_HEADING = _font(26, bold=True)
FONT_STAGE = _font(18, bold=True)


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

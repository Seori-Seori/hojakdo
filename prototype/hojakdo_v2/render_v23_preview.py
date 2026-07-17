from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from .render_prototype import (
    FONT_SMALL,
    FONT_TINY,
    PrototypeRenderer,
    _font,
)
from .scene_calculator import HojakdoSceneCalculator


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
OUTPUT_DIR = PACKAGE_DIR / "output"
DEFAULT_GIF = OUTPUT_DIR / "hojakdo_v23_plum_battery_preview.gif"
DEFAULT_SHEET = OUTPUT_DIR / "hojakdo_v23_plum_battery_stages.png"
DEFAULT_FINAL = OUTPUT_DIR / "hojakdo_v23_final_combination.png"

CROP_SIZE = (450, 720)
PANEL_WIDTH = 270
FRAME_SIZE = (CROP_SIZE[0] + PANEL_WIDTH, CROP_SIZE[1])
FONT_HEADING = _font(22, bold=True)
FONT_PERCENT = _font(36, bold=True)
FONT_STAGE = _font(18, bold=True)

STAGES = (
    ("01 / 05", "0-15%", "BARE + FEW BUDS", "plum_stage_01_bare.png"),
    (
        "02 / 05",
        "16-35%",
        "BUDS + FIRST BLOOMS",
        "plum_stage_02_first_blooms.png",
    ),
    ("03 / 05", "36-55%", "EARLY BLOOM", "plum_stage_03_early_bloom.png"),
    ("04 / 05", "56-80%", "RICH BLOOM", "plum_stage_04_rich_bloom.png"),
    ("05 / 05", "81-100%", "FULL BLOOM", "plum_stage_05_full_bloom.png"),
)


def _source_stage(filename: str) -> Image.Image:
    path = (
        REPO_ROOT
        / "assets/layers/source/environment/plum_battery_v23"
        / filename
    )
    with Image.open(path) as source:
        return source.convert("RGB")


def _panel(stage_index: int) -> Image.Image:
    stage_no, percent, name, _ = STAGES[stage_index]
    panel = Image.new("RGB", (PANEL_WIDTH, CROP_SIZE[1]), (34, 29, 21))
    draw = ImageDraw.Draw(panel)
    accent = (194, 72, 43)
    paper = (226, 194, 136)
    muted = (142, 125, 96)

    draw.text((28, 34), "HOJAKDO", font=FONT_HEADING, fill=paper)
    draw.text((28, 63), "PLUM BATTERY", font=FONT_STAGE, fill=muted)
    draw.line((28, 101, PANEL_WIDTH - 28, 101), fill=(91, 76, 55), width=1)
    draw.text((28, 139), stage_no, font=FONT_STAGE, fill=accent)
    draw.text((28, 181), percent, font=FONT_PERCENT, fill=(244, 224, 181))
    draw.multiline_text(
        (28, 242),
        name.replace(" + ", " +\n"),
        font=FONT_STAGE,
        fill=paper,
        spacing=7,
    )

    y = 355
    for index, (_, item_percent, _, _) in enumerate(STAGES):
        active = index == stage_index
        draw.ellipse(
            (28, y, 42, y + 14), fill=accent if active else (83, 73, 57)
        )
        draw.text(
            (54, y - 3),
            item_percent,
            font=_font(14, bold=active),
            fill=(233, 209, 163) if active else muted,
        )
        y += 46

    draw.line((28, 616, PANEL_WIDTH - 28, 616), fill=(91, 76, 55), width=1)
    draw.text((28, 638), "STATIC LAYER SWAP", font=FONT_TINY, fill=muted)
    draw.text((28, 660), "NUMERIC INDICATOR KEPT", font=FONT_TINY, fill=muted)
    draw.text((28, 682), "NO BLOOM ANIMATION", font=FONT_TINY, fill=muted)
    return panel


def _preview_frames() -> list[Image.Image]:
    frames: list[Image.Image] = []
    for index, (_, _, _, filename) in enumerate(STAGES):
        frame = Image.new("RGB", FRAME_SIZE, (15, 13, 10))
        frame.paste(_source_stage(filename), (0, 0))
        frame.paste(_panel(index), (CROP_SIZE[0], 0))
        frames.append(frame)
    return frames


def render_gif(output_path: Path) -> None:
    frames = _preview_frames()
    sequence = [0, 1, 2, 3, 4, 3, 2, 1]
    durations = [1300, 900, 900, 900, 1500, 900, 900, 900]
    selected = [
        frames[index].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        for index in sequence
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected[0].save(
        output_path,
        save_all=True,
        append_images=selected[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )


def render_stage_sheet(output_path: Path) -> None:
    width = 250
    height = 400
    sheet = Image.new("RGB", (width * len(STAGES), height + 56), (22, 19, 15))
    draw = ImageDraw.Draw(sheet)
    for index, (_, percent, _, filename) in enumerate(STAGES):
        stage = _source_stage(filename).resize((width, height), Image.Resampling.LANCZOS)
        x = index * width
        sheet.paste(stage, (x, 0))
        draw.text((x + 12, height + 15), percent, font=FONT_STAGE, fill=(239, 215, 168))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, optimize=True)


def _hidden_timestamp(calculator: HojakdoSceneCalculator, source_date: date) -> datetime:
    start = datetime.combine(source_date, datetime.min.time())
    for minute in range(24 * 60):
        timestamp = start + timedelta(minutes=minute)
        if calculator.snapshot(timestamp).state == "HIDDEN":
            return timestamp
    raise RuntimeError("Could not find a hidden phase for the final combination")


def render_final_combination(source_date: date, output_path: Path) -> None:
    calculator = HojakdoSceneCalculator()
    renderer = PrototypeRenderer(calculator)
    timestamp = _hidden_timestamp(calculator, source_date)
    snapshot = calculator.snapshot(timestamp)
    face = renderer.render_face(
        timestamp,
        snapshot,
        guides=False,
        clock_label=False,
        battery_percent=85,
    ).convert("RGB")

    board = Image.new("RGB", (900, 520), (22, 19, 15))
    draw = ImageDraw.Draw(board)
    face_large = face.resize((480, 480), Image.Resampling.LANCZOS)
    board.paste(face_large, (20, 20))
    draw.text((535, 38), "HOJAKDO V2.3", font=_font(26, bold=True), fill=(246, 226, 180))
    draw.text((535, 80), "85% / FULL BLOOM", font=FONT_STAGE, fill=(202, 83, 47))
    draw.line((535, 118, 862, 118), fill=(85, 72, 52), width=1)
    lines = (
        "5 STATIC PLUM STAGES",
        "NUMERIC BATTERY KEPT",
        "NO BLOOM ANIMATION",
        "AOD KEEPS DIMMED STAGE",
        "V2.2 MOTION UNCHANGED",
    )
    y = 156
    for line in lines:
        draw.ellipse((535, y + 3, 545, y + 13), fill=(181, 68, 41))
        draw.text((560, y), line, font=FONT_SMALL, fill=(225, 205, 165))
        y += 48
    draw.text(
        (535, 446),
        "STATIC SIMULATION / AGIF + WFF NOT CONNECTED",
        font=FONT_TINY,
        fill=(126, 117, 100),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    board.save(output_path, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Hojakdo V2.3 plum battery previews")
    parser.add_argument("--date", default="2026-07-15")
    parser.add_argument("--gif", type=Path, default=DEFAULT_GIF)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    parser.add_argument("--final", type=Path, default=DEFAULT_FINAL)
    args = parser.parse_args()
    render_gif(args.gif)
    render_stage_sheet(args.sheet)
    render_final_combination(date.fromisoformat(args.date), args.final)
    print(args.gif)
    print(args.sheet)
    print(args.final)


if __name__ == "__main__":
    main()

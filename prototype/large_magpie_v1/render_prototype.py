from __future__ import annotations

import argparse
import gc
import json
import math
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from .scene_calculator import CyclePlan, LargeMagpieSceneCalculator, SceneSnapshot


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "output"
FACE_SIZE = 450
PANEL_WIDTH = 240
FRAME_SIZE = (FACE_SIZE + PANEL_WIDTH, FACE_SIZE)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        if bold
        else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")
        if bold
        else Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


FONT_SMALL = _font(12)
FONT_BODY = _font(14)
FONT_BODY_BOLD = _font(14, bold=True)
FONT_TITLE = _font(18, bold=True)
FONT_CLOCK = _font(17, bold=True)


class PrototypeRenderer:
    def __init__(self, calculator: LargeMagpieSceneCalculator) -> None:
        self.calculator = calculator
        self.config = calculator.config
        self.geometry = calculator.geometry
        self.background = self._load_layer("assets/layers/mvp/clean_background.png", "RGB")
        self.hour_branch = self._load_layer("assets/layers/mvp/hour_branch.png")
        self.minute_branch = self._load_layer("assets/layers/mvp/minute_branch.png")
        self.tiger_head = self._load_layer("assets/layers/mvp/tiger_head.png")
        self.tiger_pupils = self._load_layer("assets/layers/mvp/tiger_pupils.png")
        self.bird, self.bird_anchor = self._load_bird()

    @staticmethod
    def _source_path(relative: str) -> Path:
        return REPO_ROOT / relative

    def _load_layer(self, relative: str, mode: str = "RGBA") -> Image.Image:
        with Image.open(self._source_path(relative)) as source:
            return source.convert(mode).resize((FACE_SIZE, FACE_SIZE), Image.Resampling.LANCZOS)

    def _load_bird(self) -> tuple[Image.Image, tuple[float, float]]:
        path = self._source_path("assets/layers/source/characters/magpie_large_base_master.png")
        with Image.open(path) as source:
            full = source.convert("RGBA").resize(
                (FACE_SIZE, FACE_SIZE), Image.Resampling.LANCZOS
            )
        alpha = full.getchannel("A")
        bounds = alpha.getbbox()
        if bounds is None:
            raise ValueError("Large magpie master has no visible pixels")
        padding = 3
        left = max(0, bounds[0] - padding)
        top = max(0, bounds[1] - padding)
        right = min(FACE_SIZE, bounds[2] + padding)
        bottom = min(FACE_SIZE, bounds[3] + padding)
        anchor_x, anchor_y = self.geometry["magpieAnchorAtZero"]
        return full.crop((left, top, right, bottom)), (anchor_x - left, anchor_y - top)

    @staticmethod
    def _rotate_layer(
        layer: Image.Image, clockwise_degrees: float, pivot: Iterable[float]
    ) -> Image.Image:
        return layer.rotate(
            -clockwise_degrees,
            resample=Image.Resampling.BICUBIC,
            center=tuple(pivot),
            expand=False,
        )

    def _paste_bird(self, target: Image.Image, foot: tuple[float, float] | None) -> None:
        if foot is None:
            return
        x = int(round(foot[0] - self.bird_anchor[0]))
        y = int(round(foot[1] - self.bird_anchor[1]))
        target.alpha_composite(self.bird, (x, y))

    def _tiger_group(self, reacting: bool) -> tuple[Image.Image, Image.Image]:
        if not reacting:
            return self.tiger_head, self.tiger_pupils
        pivot = tuple(self.geometry["tigerPerchLarge"])
        head = self.tiger_head.rotate(
            1.8,
            resample=Image.Resampling.BICUBIC,
            center=pivot,
            expand=False,
        )
        pupils = self.tiger_pupils.rotate(
            1.8,
            resample=Image.Resampling.BICUBIC,
            center=pivot,
            expand=False,
        )
        translated_head = Image.new("RGBA", head.size)
        translated_pupils = Image.new("RGBA", pupils.size)
        translated_head.alpha_composite(head, (-2, -1))
        translated_pupils.alpha_composite(pupils, (-2, -1))
        return translated_head, translated_pupils

    def _draw_guides(
        self, face: Image.Image, timestamp: datetime, snapshot: SceneSnapshot
    ) -> None:
        overlay = Image.new("RGBA", face.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        pivot = tuple(self.geometry["clockPivot"])
        hour = self.calculator.hand_anchor("hour", timestamp)
        minute = self.calculator.hand_anchor("minute", timestamp)
        draw.line((pivot, hour), fill=(76, 157, 255, 115), width=1)
        draw.line((pivot, minute), fill=(255, 192, 76, 125), width=1)
        draw.ellipse((hour[0] - 3, hour[1] - 3, hour[0] + 3, hour[1] + 3), fill=(76, 157, 255, 185))
        draw.ellipse(
            (minute[0] - 3, minute[1] - 3, minute[0] + 3, minute[1] + 3),
            fill=(255, 192, 76, 195),
        )
        tiger_approach = tuple(self.geometry["tigerApproachLarge"])
        tiger_perch = tuple(self.geometry["tigerPerchLarge"])
        draw.ellipse(
            (
                tiger_approach[0] - 4,
                tiger_approach[1] - 4,
                tiger_approach[0] + 4,
                tiger_approach[1] + 4,
            ),
            outline=(255, 115, 80, 210),
            width=2,
        )
        draw.ellipse(
            (
                tiger_perch[0] - 4,
                tiger_perch[1] - 4,
                tiger_perch[0] + 4,
                tiger_perch[1] + 4,
            ),
            outline=(117, 235, 143, 220),
            width=2,
        )
        if snapshot.route == "PLUM_WALK":
            points = [tuple(point) for point in self.geometry["plumWalkWaypointsLarge"]]
            draw.line(points, fill=(117, 235, 143, 115), width=2)
        if snapshot.foot_position is not None:
            x, y = snapshot.foot_position
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(255, 255, 255, 220))
        face.alpha_composite(overlay)

    def render_face(
        self, timestamp: datetime, snapshot: SceneSnapshot, guides: bool = True
    ) -> Image.Image:
        face = self.background.convert("RGBA")
        hour_angle = self.calculator.hand_group_angle("hour", timestamp)
        minute_angle = self.calculator.hand_group_angle("minute", timestamp)
        hour_branch = self._rotate_layer(
            self.hour_branch, hour_angle, self.geometry["clockPivot"]
        )
        minute_branch = self._rotate_layer(
            self.minute_branch, minute_angle, self.geometry["clockPivot"]
        )
        tiger_head, tiger_pupils = self._tiger_group(snapshot.tiger_reacting)

        if snapshot.render_slot == "GROUND":
            self._paste_bird(face, snapshot.foot_position)
        face.alpha_composite(hour_branch)
        face.alpha_composite(minute_branch)
        if snapshot.render_slot == "HAND":
            self._paste_bird(face, snapshot.foot_position)
        face.alpha_composite(tiger_head)
        if snapshot.render_slot == "TIGER":
            self._paste_bird(face, snapshot.foot_position)
        face.alpha_composite(tiger_pupils)

        if guides:
            self._draw_guides(face, timestamp, snapshot)
        draw = ImageDraw.Draw(face)
        label = timestamp.strftime("%H:%M:%S")
        box = draw.textbbox((0, 0), label, font=FONT_CLOCK)
        width = box[2] - box[0]
        draw.rounded_rectangle(
            (FACE_SIZE // 2 - width // 2 - 7, 8, FACE_SIZE // 2 + width // 2 + 7, 34),
            radius=7,
            fill=(16, 13, 10, 185),
        )
        draw.text((FACE_SIZE // 2 - width // 2, 11), label, font=FONT_CLOCK, fill=(244, 225, 178, 255))
        return face

    @staticmethod
    def _route_color(route: str) -> tuple[int, int, int]:
        return {
            "MINUTE_DIRECT": (255, 190, 70),
            "HOUR_TO_MINUTE": (80, 165, 255),
            "PLUM_WALK": (108, 215, 132),
        }.get(route, (210, 210, 210))

    def _draw_panel(self, frame: Image.Image, snapshot: SceneSnapshot) -> None:
        draw = ImageDraw.Draw(frame)
        x0 = FACE_SIZE
        draw.rectangle((x0, 0, FRAME_SIZE[0], FRAME_SIZE[1]), fill=(17, 19, 22))
        route_color = self._route_color(snapshot.route)
        x = x0 + 16
        y = 18
        draw.text((x, y), "LARGE MAGPIE V1", font=FONT_TITLE, fill=(245, 240, 226))
        y += 27
        draw.text((x, y), "STATIC PROTOTYPE", font=FONT_SMALL, fill=(160, 166, 174))
        y += 29
        draw.text((x, y), snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S"), font=FONT_BODY, fill=(222, 225, 230))
        y += 25
        draw.text((x, y), f"Cycle  #{snapshot.cycle_index}", font=FONT_BODY, fill=(185, 191, 199))
        y += 23
        draw.text((x, y), "ROUTE", font=FONT_SMALL, fill=(130, 136, 145))
        y += 16
        draw.text((x, y), snapshot.route, font=FONT_BODY_BOLD, fill=route_color)
        y += 29
        draw.text((x, y), "STATE", font=FONT_SMALL, fill=(130, 136, 145))
        y += 16
        draw.text((x, y), snapshot.state, font=FONT_BODY_BOLD, fill=(245, 240, 226))
        y += 20
        draw.text((x, y), f"next  {snapshot.next_state}", font=FONT_SMALL, fill=(160, 166, 174))
        y += 29
        hand = snapshot.selected_hand.upper() if snapshot.selected_hand else "NONE"
        draw.text((x, y), f"Selected hand   {hand}", font=FONT_BODY, fill=(214, 218, 225))
        y += 25
        hour_flag = "OK" if snapshot.hour_eligible else "--"
        minute_flag = "OK" if snapshot.minute_eligible else "--"
        draw.text(
            (x, y),
            f"Hour   {snapshot.hour_score:7.1f}  {hour_flag}",
            font=FONT_BODY,
            fill=(105, 180, 255),
        )
        y += 21
        draw.text(
            (x, y),
            f"Minute {snapshot.minute_score:7.1f}  {minute_flag}",
            font=FONT_BODY,
            fill=(255, 197, 91),
        )
        y += 31
        draw.text((x, y), "CYCLE", font=FONT_SMALL, fill=(130, 136, 145))
        y += 17
        bar_width = PANEL_WIDTH - 32
        draw.rounded_rectangle((x, y, x + bar_width, y + 9), radius=4, fill=(48, 52, 58))
        draw.rounded_rectangle(
            (x, y, x + int(bar_width * snapshot.cycle_progress), y + 9),
            radius=4,
            fill=route_color,
        )
        y += 15
        draw.text((x, y), f"{snapshot.cycle_progress * 100:5.1f}%", font=FONT_SMALL, fill=(184, 189, 197))
        y += 26
        draw.text((x, y), "STATE", font=FONT_SMALL, fill=(130, 136, 145))
        y += 17
        draw.rounded_rectangle((x, y, x + bar_width, y + 9), radius=4, fill=(48, 52, 58))
        draw.rounded_rectangle(
            (x, y, x + int(bar_width * snapshot.state_progress), y + 9),
            radius=4,
            fill=(226, 229, 233),
        )
        y += 21
        y = 402
        reaction_color = (255, 99, 88) if snapshot.tiger_reacting else (140, 145, 153)
        reaction_label = "TIGER REACTION  NOW" if snapshot.tiger_reacting else "Tiger reaction reserved"
        draw.text((x, y), reaction_label, font=FONT_BODY_BOLD if snapshot.tiger_reacting else FONT_BODY, fill=reaction_color)
        y += 20
        draw.text(
            (x, y),
            f"{snapshot.reaction_state} @ {snapshot.reaction_minute:.2f}m",
            font=FONT_SMALL,
            fill=(148, 153, 161),
        )

    def render_debug_frame(self, timestamp: datetime) -> Image.Image:
        snapshot = self.calculator.snapshot(timestamp)
        face = self.render_face(timestamp, snapshot, guides=True)
        frame = Image.new("RGB", FRAME_SIZE, (17, 19, 22))
        frame.paste(face.convert("RGB"), (0, 0))
        self._draw_panel(frame, snapshot)
        return frame


def _unique_times(values: Iterable[datetime]) -> list[datetime]:
    by_second = {value.replace(microsecond=0): value.replace(microsecond=0) for value in values}
    return sorted(by_second.values())


def _day_frame_times(
    calculator: LargeMagpieSceneCalculator, day_start: datetime, step_minutes: float
) -> list[datetime]:
    day_end = day_start + timedelta(days=1)
    values: list[datetime] = []
    cursor = day_start
    while cursor < day_end:
        values.append(cursor)
        cursor += timedelta(minutes=step_minutes)
    for plan in calculator.plans_intersecting(day_start, day_end):
        for phase in plan.phases:
            if phase.state in {"SPAWN_PINE", "SPAWN_PLUM", "LAND_ON_TIGER", "FLY_OUT_RIGHT"}:
                values.append(plan.cycle_start + timedelta(minutes=phase.start + 0.05))
        values.append(plan.cycle_start + timedelta(minutes=plan.reaction_minute))
    return [value for value in _unique_times(values) if day_start <= value < day_end]


def _detail_frame_times(plan: CyclePlan, step_minutes: float) -> list[datetime]:
    values: list[datetime] = []
    cursor = 0.0
    cycle_minutes = plan.phases[-1].end
    while cursor < cycle_minutes:
        values.append(plan.cycle_start + timedelta(minutes=cursor))
        cursor += step_minutes
    for phase in plan.phases:
        values.append(plan.cycle_start + timedelta(minutes=phase.start + 0.02))
        values.append(plan.cycle_start + timedelta(minutes=max(phase.start, phase.end - 0.02)))
    values.append(plan.cycle_start + timedelta(minutes=plan.reaction_minute))
    return _unique_times(values)


def _save_gif(
    frames: list[Image.Image], path: Path, duration_ms: int, colors: int
) -> None:
    if not frames:
        raise ValueError("Cannot save an empty GIF")
    palette = frames[0].convert("P", palette=Image.Palette.ADAPTIVE, colors=colors)
    quantized = [
        frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames
    ]
    quantized[0].save(
        path,
        save_all=True,
        append_images=quantized[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
        disposal=1,
    )


def _find_detail_plan(
    calculator: LargeMagpieSceneCalculator, source_day: datetime
) -> CyclePlan:
    search_start = source_day - timedelta(days=7)
    search_end = source_day + timedelta(days=8)
    plans = calculator.plans_intersecting(search_start, search_end)
    hour_plans = [plan for plan in plans if plan.route == "HOUR_TO_MINUTE"]
    candidates = hour_plans or [plan for plan in plans if plan.route == "MINUTE_DIRECT"] or plans
    target = source_day + timedelta(hours=12)
    return min(candidates, key=lambda plan: abs((plan.cycle_start - target).total_seconds()))


def _contact_sheet(
    renderer: PrototypeRenderer, plan: CyclePlan, output_path: Path
) -> None:
    samples: list[tuple[str, datetime]] = []
    for phase in plan.phases:
        samples.append(
            (
                phase.state,
                plan.cycle_start + timedelta(minutes=(phase.start + phase.end) / 2.0),
            )
        )
    columns = 3
    cell_width = 300
    cell_height = 326
    rows = math.ceil(len(samples) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (20, 21, 23))
    draw = ImageDraw.Draw(sheet)
    for index, (state, timestamp) in enumerate(samples):
        face = renderer.render_face(timestamp, renderer.calculator.snapshot(timestamp), guides=False)
        thumb = face.convert("RGB").resize((300, 300), Image.Resampling.LANCZOS)
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        sheet.paste(thumb, (x, y))
        draw.rectangle((x, y + 300, x + cell_width, y + cell_height), fill=(20, 21, 23))
        draw.text((x + 8, y + 305), state, font=FONT_BODY_BOLD, fill=(238, 234, 222))
        clock = timestamp.strftime("%m-%d %H:%M")
        text_box = draw.textbbox((0, 0), clock, font=FONT_SMALL)
        draw.text(
            (x + cell_width - (text_box[2] - text_box[0]) - 8, y + 307),
            clock,
            font=FONT_SMALL,
            fill=(154, 160, 168),
        )
    sheet.save(output_path, optimize=True)


def _write_report(
    calculator: LargeMagpieSceneCalculator,
    source_day: datetime,
    detail_plan: CyclePlan,
    day_frame_count: int,
    detail_frame_count: int,
    output_dir: Path,
) -> None:
    day_end = source_day + timedelta(days=1)
    week_start = source_day - timedelta(days=3)
    week_end = source_day + timedelta(days=4)
    day_plans = calculator.plans_intersecting(source_day, day_end)
    week_plans = calculator.plans_intersecting(week_start, week_end)
    report = {
        "schemaVersion": 1,
        "status": "static_prototype_generated",
        "sourceDate": source_day.date().isoformat(),
        "cycleMinutes": calculator.cycle_minutes,
        "dayFrameCount": day_frame_count,
        "detailFrameCount": detail_frame_count,
        "dayRouteCounts": dict(Counter(plan.route for plan in day_plans)),
        "sevenDayRouteCounts": dict(Counter(plan.route for plan in week_plans)),
        "detailCycle": {
            "cycleIndex": detail_plan.cycle_index,
            "cycleStart": detail_plan.cycle_start.isoformat(),
            "route": detail_plan.route,
            "selectedHand": detail_plan.selected_hand,
            "reactionMinute": detail_plan.reaction_minute,
            "reactionState": detail_plan.reaction_state,
            "hourScore": detail_plan.hour_evaluation.score,
            "minuteScore": detail_plan.minute_evaluation.score,
            "phases": [
                {
                    "state": phase.state,
                    "startMinute": phase.start,
                    "endMinute": phase.end,
                    "hand": phase.hand,
                }
                for phase in detail_plan.phases
            ],
        },
        "outputs": [
            "large_magpie_v1_24h_debug.gif",
            "large_magpie_v1_hour_transfer_detail.gif",
            "large_magpie_v1_hour_transfer_contact_sheet.png",
            "prototype_report.json",
        ],
        "completionLevel": "static_simulation_prototype",
        "wffConnected": False,
    }
    (output_dir / "prototype_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_all(source_date: date, output_dir: Path) -> None:
    calculator = LargeMagpieSceneCalculator()
    renderer = PrototypeRenderer(calculator)
    output_dir.mkdir(parents=True, exist_ok=True)
    render_config = calculator.config["render"]
    day_start = datetime.combine(source_date, time.min)

    day_times = _day_frame_times(
        calculator, day_start, float(render_config["dayStepMinutes"])
    )
    day_frames = [renderer.render_debug_frame(timestamp) for timestamp in day_times]
    _save_gif(
        day_frames,
        output_dir / "large_magpie_v1_24h_debug.gif",
        int(render_config["dayFrameDurationMs"]),
        int(render_config["gifColors"]),
    )
    day_frame_count = len(day_frames)
    del day_frames
    gc.collect()

    detail_plan = _find_detail_plan(calculator, day_start)
    detail_times = _detail_frame_times(
        detail_plan, float(render_config["detailStepMinutes"])
    )
    detail_frames = [renderer.render_debug_frame(timestamp) for timestamp in detail_times]
    _save_gif(
        detail_frames,
        output_dir / "large_magpie_v1_hour_transfer_detail.gif",
        int(render_config["detailFrameDurationMs"]),
        int(render_config["gifColors"]),
    )
    detail_frame_count = len(detail_frames)
    del detail_frames
    gc.collect()

    _contact_sheet(
        renderer,
        detail_plan,
        output_dir / "large_magpie_v1_hour_transfer_contact_sheet.png",
    )
    _write_report(
        calculator,
        day_start,
        detail_plan,
        day_frame_count,
        detail_frame_count,
        output_dir,
    )


def main() -> None:
    calculator = LargeMagpieSceneCalculator()
    parser = argparse.ArgumentParser(description="Render the deterministic large-magpie V1 prototype")
    parser.add_argument(
        "--date",
        default=calculator.config["render"]["sourceDate"],
        help="Source day in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for GIF, contact sheet, and report",
    )
    args = parser.parse_args()
    render_all(date.fromisoformat(args.date), args.output_dir)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import gc
import json
import math
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from .scene_calculator import CyclePlan, HojakdoSceneCalculator, SceneSnapshot


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "output"
FACE_SIZE = 450
PANEL_WIDTH = 270
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


FONT_TINY = _font(10)
FONT_SMALL = _font(12)
FONT_BODY = _font(14)
FONT_BODY_BOLD = _font(14, bold=True)
FONT_TITLE = _font(18, bold=True)
FONT_CLOCK = _font(17, bold=True)


class PrototypeRenderer:
    def __init__(self, calculator: HojakdoSceneCalculator) -> None:
        self.calculator = calculator
        self.config = calculator.config
        self.geometry = calculator.geometry
        self.background = self._load_layer("assets/layers/mvp/clean_background.png", "RGB")
        self.hour_branch = self._load_layer("assets/layers/mvp/hour_branch.png")
        self.minute_branch = self._load_layer("assets/layers/mvp/minute_branch.png")
        self.tiger_head = self._load_layer("assets/layers/mvp/tiger_head.png")
        self.tiger_pupils = self._load_layer("assets/layers/mvp/tiger_pupils.png")
        self.birds = {
            "LARGE": self._load_large_bird(),
            "SMALL": self._load_small_bird_draft(),
        }

    @staticmethod
    def _source_path(relative: str) -> Path:
        return REPO_ROOT / relative

    def _load_layer(self, relative: str, mode: str = "RGBA") -> Image.Image:
        with Image.open(self._source_path(relative)) as source:
            return source.convert(mode).resize(
                (FACE_SIZE, FACE_SIZE), Image.Resampling.LANCZOS
            )

    @staticmethod
    def _crop_asset(
        full: Image.Image, anchor: tuple[float, float], padding: int = 3
    ) -> tuple[Image.Image, tuple[float, float]]:
        bounds = full.getchannel("A").getbbox()
        if bounds is None:
            raise ValueError("Bird asset has no visible pixels")
        left = max(0, bounds[0] - padding)
        top = max(0, bounds[1] - padding)
        right = min(full.width, bounds[2] + padding)
        bottom = min(full.height, bounds[3] + padding)
        return full.crop((left, top, right, bottom)), (
            anchor[0] - left,
            anchor[1] - top,
        )

    def _load_large_bird(self) -> tuple[Image.Image, tuple[float, float], str]:
        path = self._source_path(
            "assets/layers/source/characters/magpie_large_base_master.png"
        )
        with Image.open(path) as source:
            full = source.convert("RGBA").resize(
                (FACE_SIZE, FACE_SIZE), Image.Resampling.LANCZOS
            )
        anchor = tuple(self.geometry["birdAssetAnchorAtZero"]["LARGE"])
        sprite, local_anchor = self._crop_asset(full, anchor)
        return sprite, local_anchor, "RIGHT"

    def _load_small_bird_draft(self) -> tuple[Image.Image, tuple[float, float], str]:
        # The legacy small-magpie layer also contains a branch and red ornament.
        # This render-only silhouette mask removes those obvious attachments while
        # preserving the source file untouched. A clean master remains a V3/AGIF
        # production prerequisite.
        path = self._source_path("assets/layers/mvp/hour_magpie.png")
        with Image.open(path) as source:
            full = source.convert("RGBA").resize(
                (FACE_SIZE, FACE_SIZE), Image.Resampling.LANCZOS
            )
        silhouette = Image.new("L", full.size, 0)
        draw = ImageDraw.Draw(silhouette)
        draw.polygon(
            [
                (304, 110),
                (326, 110),
                (337, 124),
                (338, 142),
                (335, 169),
                (320, 172),
                (313, 154),
                (307, 153),
                (301, 145),
                (298, 133),
                (300, 120),
            ],
            fill=255,
        )
        full.putalpha(ImageChops.multiply(full.getchannel("A"), silhouette))
        anchor = tuple(self.geometry["birdAssetAnchorAtZero"]["SMALL"])
        sprite, local_anchor = self._crop_asset(full, anchor, padding=2)
        return sprite, local_anchor, "LEFT"

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

    @staticmethod
    def _pose_pulse(progress: float) -> float:
        progress = min(1.0, max(0.0, progress))
        if progress < 0.28:
            return progress / 0.28
        if progress < 0.54:
            return 1.0
        if progress < 0.72:
            return 1.0 - 1.16 * ((progress - 0.54) / 0.18)
        return -0.16 * (1.0 - (progress - 0.72) / 0.28)

    @staticmethod
    def _rotate_upper(
        sprite: Image.Image,
        anchor: tuple[float, float],
        clockwise_degrees: float,
        cutoff_offset: float,
    ) -> Image.Image:
        cutoff = int(max(2, min(sprite.height - 2, anchor[1] - cutoff_offset)))
        upper = Image.new("RGBA", sprite.size, (0, 0, 0, 0))
        upper.alpha_composite(sprite)
        ImageDraw.Draw(upper).rectangle(
            (0, cutoff, sprite.width, sprite.height), fill=(0, 0, 0, 0)
        )
        lower = sprite.copy()
        ImageDraw.Draw(lower).rectangle((0, 0, sprite.width, cutoff), fill=(0, 0, 0, 0))
        posed_upper = upper.rotate(
            -clockwise_degrees,
            resample=Image.Resampling.BICUBIC,
            center=(anchor[0], cutoff),
            expand=False,
        )
        lower.alpha_composite(posed_upper)
        return lower

    def _posed_bird(
        self, snapshot: SceneSnapshot
    ) -> tuple[Image.Image, tuple[float, float], float]:
        sprite, source_anchor, base_facing = self.birds[snapshot.character]
        image = sprite.copy()
        anchor = source_anchor
        if snapshot.facing != base_facing:
            image = ImageOps.mirror(image)
            anchor = (image.width - 1 - anchor[0], anchor[1])

        y_offset = 0.0
        action = snapshot.micro_action
        progress = snapshot.micro_progress
        direction = 1.0 if snapshot.facing == "RIGHT" else -1.0
        if action == "HEAD_TILT":
            image = self._rotate_upper(
                image, anchor, direction * 3.0 * self._pose_pulse(progress), 24
            )
        elif action == "HEAD_SCAN":
            angle = direction * 4.2 * math.sin(progress * math.pi * 2.0)
            image = self._rotate_upper(image, anchor, angle, 12)
        elif action == "LOOK_PLUM":
            image = self._rotate_upper(
                image, anchor, -direction * 5.0 * math.sin(progress * math.pi), 10
            )
        elif action == "CHECK_TARGET":
            image = self._rotate_upper(
                image, anchor, direction * 4.0 * self._pose_pulse(progress), 10
            )
        elif action == "TURN":
            y_offset += 3.0 * math.sin(progress * math.pi)
        elif action == "PECK_TIGER_EAR":
            peck = max(0.0, math.sin(progress * math.pi * 4.0))
            image = self._rotate_upper(image, anchor, -direction * 10.0 * peck, 7)
            y_offset += 2.2 * peck

        if snapshot.state == "EXIT_RIGHT":
            if snapshot.character == "LARGE":
                crouch = math.sin(min(1.0, snapshot.state_progress * 1.7) * math.pi)
                image = self._rotate_upper(image, anchor, -2.2 * crouch, 15)
                y_offset += 2.0 * crouch
            else:
                flap = math.sin(snapshot.wing_flap_progress * math.pi)
                image = self._rotate_upper(image, anchor, 3.2 * flap, 7)
                y_offset -= 2.0 * flap
        return image, anchor, y_offset

    @staticmethod
    def _draw_small_wing(
        target: Image.Image, foot: tuple[float, float], snapshot: SceneSnapshot
    ) -> None:
        if snapshot.character != "SMALL" or snapshot.state != "EXIT_RIGHT":
            return
        amplitude = math.sin(snapshot.wing_flap_progress * math.pi)
        x, y = foot
        shoulder = (x - 4, y - 23)
        reach = 12 + 18 * amplitude
        overlay = Image.new("RGBA", target.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.polygon(
            [
                shoulder,
                (x - 12 - reach * 0.45, y - 20 - reach),
                (x - 15, y - 13),
            ],
            fill=(20, 42, 48, 215),
            outline=(155, 126, 63, 220),
        )
        draw.line(
            (shoulder, (x - 10 - reach * 0.35, y - 18 - reach * 0.82)),
            fill=(222, 208, 167, 175),
            width=1,
        )
        target.alpha_composite(overlay)

    def _paste_bird(
        self,
        target: Image.Image,
        foot: tuple[float, float] | None,
        snapshot: SceneSnapshot,
    ) -> None:
        if foot is None:
            return
        self._draw_small_wing(target, foot, snapshot)
        bird, anchor, y_offset = self._posed_bird(snapshot)
        x = int(round(foot[0] - anchor[0]))
        y = int(round(foot[1] - anchor[1] + y_offset))
        target.alpha_composite(bird, (x, y))

    @staticmethod
    def _reaction_curve(progress: float) -> float:
        progress = min(1.0, max(0.0, progress))
        if progress < 0.28:
            return progress / 0.28
        if progress < 0.48:
            return 1.0
        if progress < 0.68:
            return 1.0 - 1.18 * ((progress - 0.48) / 0.20)
        return -0.18 * (1.0 - (progress - 0.68) / 0.32)

    @staticmethod
    def _translate(layer: Image.Image, dx: int, dy: int) -> Image.Image:
        result = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        result.alpha_composite(layer, (dx, dy))
        return result

    def _tiger_group(self, snapshot: SceneSnapshot) -> tuple[Image.Image, Image.Image]:
        if not snapshot.tiger_reacting:
            return self.tiger_head, self.tiger_pupils
        progress = snapshot.tiger_reaction_progress
        head_pose = self._reaction_curve(progress)
        pupil_progress = max(0.0, (progress - 0.20) / 0.80)
        pupil_pose = self._reaction_curve(pupil_progress)
        amplitude = 1.65 if snapshot.character == "LARGE" else 0.9
        pivot = tuple(self.geometry["tigerPerch"]["LARGE"])
        head = self.tiger_head.rotate(
            amplitude * head_pose,
            resample=Image.Resampling.BICUBIC,
            center=pivot,
            expand=False,
        )
        pupils = self.tiger_pupils.rotate(
            amplitude * 0.55 * pupil_pose,
            resample=Image.Resampling.BICUBIC,
            center=pivot,
            expand=False,
        )
        head = self._translate(
            head, int(round(-1.5 * head_pose)), int(round(-0.8 * head_pose))
        )
        pupils = self._translate(
            pupils, int(round(-1.8 * pupil_pose)), int(round(-0.4 * pupil_pose))
        )
        return head, pupils

    def _draw_guides(
        self, face: Image.Image, timestamp: datetime, snapshot: SceneSnapshot
    ) -> None:
        overlay = Image.new("RGBA", face.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        pivot = tuple(self.geometry["clockPivot"])
        hour = self.calculator.hand_anchor("hour", timestamp, snapshot.character)
        minute = self.calculator.hand_anchor("minute", timestamp, snapshot.character)
        draw.line((pivot, hour), fill=(76, 157, 255, 105), width=1)
        draw.line((pivot, minute), fill=(255, 192, 76, 115), width=1)
        draw.ellipse(
            (hour[0] - 3, hour[1] - 3, hour[0] + 3, hour[1] + 3),
            fill=(76, 157, 255, 185),
        )
        draw.ellipse(
            (minute[0] - 3, minute[1] - 3, minute[0] + 3, minute[1] + 3),
            fill=(255, 192, 76, 195),
        )
        tiger_approach = tuple(self.geometry["tigerApproach"][snapshot.character])
        tiger_perch = tuple(self.geometry["tigerPerch"][snapshot.character])
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
            points = [
                tuple(point)
                for point in self.geometry["plumWalkWaypoints"][snapshot.character]
            ]
            draw.line(points, fill=(117, 235, 143, 110), width=2)
        if snapshot.foot_position is not None:
            x, y = snapshot.foot_position
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(255, 255, 255, 220))
        face.alpha_composite(overlay)

    def render_face(
        self,
        timestamp: datetime,
        snapshot: SceneSnapshot,
        guides: bool = True,
        clock_label: bool = True,
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
        tiger_head, tiger_pupils = self._tiger_group(snapshot)

        if snapshot.render_slot == "GROUND":
            self._paste_bird(face, snapshot.foot_position, snapshot)
        face.alpha_composite(hour_branch)
        face.alpha_composite(minute_branch)
        if snapshot.render_slot == "HAND":
            self._paste_bird(face, snapshot.foot_position, snapshot)
        face.alpha_composite(tiger_head)
        if snapshot.render_slot == "TIGER":
            self._paste_bird(face, snapshot.foot_position, snapshot)
        face.alpha_composite(tiger_pupils)

        if guides:
            self._draw_guides(face, timestamp, snapshot)
        if clock_label:
            draw = ImageDraw.Draw(face)
            label = timestamp.strftime("%H:%M:%S")
            box = draw.textbbox((0, 0), label, font=FONT_CLOCK)
            width = box[2] - box[0]
            draw.rounded_rectangle(
                (
                    FACE_SIZE // 2 - width // 2 - 7,
                    8,
                    FACE_SIZE // 2 + width // 2 + 7,
                    34,
                ),
                radius=7,
                fill=(16, 13, 10, 185),
            )
            draw.text(
                (FACE_SIZE // 2 - width // 2, 11),
                label,
                font=FONT_CLOCK,
                fill=(244, 225, 178, 255),
            )
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
        character_color = (
            (237, 184, 84) if snapshot.character == "LARGE" else (110, 205, 225)
        )
        x = x0 + 16
        y = 16
        draw.text((x, y), "HOJAKDO V2", font=FONT_TITLE, fill=(245, 240, 226))
        y += 25
        asset_note = (
            "CLEAN LARGE MASTER" if snapshot.character == "LARGE" else "SMALL MASTER: MASKED DRAFT"
        )
        draw.text((x, y), asset_note, font=FONT_TINY, fill=(147, 153, 161))
        y += 25
        draw.text(
            (x, y), snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            font=FONT_BODY, fill=(222, 225, 230)
        )
        y += 22
        draw.text((x, y), f"Cycle  #{snapshot.cycle_index}", font=FONT_SMALL, fill=(170, 176, 184))
        y += 20
        draw.text((x, y), snapshot.character, font=FONT_BODY_BOLD, fill=character_color)
        y += 22
        draw.text((x, y), snapshot.route, font=FONT_BODY_BOLD, fill=route_color)
        y += 25
        draw.text((x, y), "STATE", font=FONT_TINY, fill=(130, 136, 145))
        y += 13
        draw.text((x, y), snapshot.state, font=FONT_BODY_BOLD, fill=(245, 240, 226))
        y += 18
        draw.text((x, y), f"next  {snapshot.next_state}", font=FONT_SMALL, fill=(160, 166, 174))
        y += 23
        hand = snapshot.selected_hand.upper() if snapshot.selected_hand else "NONE"
        draw.text(
            (x, y), f"Hand {hand}   Facing {snapshot.facing}",
            font=FONT_SMALL, fill=(214, 218, 225)
        )
        y += 20
        hour_flag = "OK" if snapshot.hour_eligible else "--"
        minute_flag = "OK" if snapshot.minute_eligible else "--"
        draw.text(
            (x, y), f"Hour    {snapshot.hour_score:7.1f}  {hour_flag}",
            font=FONT_SMALL, fill=(105, 180, 255)
        )
        y += 17
        draw.text(
            (x, y), f"Minute  {snapshot.minute_score:7.1f}  {minute_flag}",
            font=FONT_SMALL, fill=(255, 197, 91)
        )
        y += 23
        action = snapshot.micro_action or "IDLE"
        action_color = (255, 220, 118) if snapshot.micro_action else (149, 155, 163)
        draw.text((x, y), f"ACTION  {action}", font=FONT_BODY_BOLD, fill=action_color)
        y += 18
        if snapshot.wing_flap_beat:
            draw.text(
                (x, y), f"WING FLAP {snapshot.wing_flap_beat}/2",
                font=FONT_BODY_BOLD, fill=(116, 219, 239)
            )
        else:
            draw.text(
                (x, y), f"Ear peck  {'YES' if snapshot.ear_peck else 'NO'}",
                font=FONT_SMALL, fill=(166, 171, 180)
            )
        y += 24
        bar_width = PANEL_WIDTH - 32
        draw.text((x, y), "CYCLE", font=FONT_TINY, fill=(130, 136, 145))
        y += 13
        draw.rounded_rectangle((x, y, x + bar_width, y + 8), radius=4, fill=(48, 52, 58))
        draw.rounded_rectangle(
            (x, y, x + int(bar_width * snapshot.cycle_progress), y + 8),
            radius=4, fill=route_color
        )
        y += 15
        draw.text((x, y), f"{snapshot.cycle_progress * 100:5.1f}%", font=FONT_TINY, fill=(184, 189, 197))
        y += 18
        draw.text((x, y), "STATE", font=FONT_TINY, fill=(130, 136, 145))
        y += 13
        draw.rounded_rectangle((x, y, x + bar_width, y + 8), radius=4, fill=(48, 52, 58))
        draw.rounded_rectangle(
            (x, y, x + int(bar_width * snapshot.state_progress), y + 8),
            radius=4, fill=(226, 229, 233)
        )
        reaction_color = (255, 99, 88) if snapshot.tiger_reacting else (145, 150, 158)
        y = 405
        reaction_label = "TIGER REACTION  NOW" if snapshot.tiger_reacting else "Tiger reaction reserved"
        draw.text(
            (x, y), reaction_label,
            font=FONT_BODY_BOLD if snapshot.tiger_reacting else FONT_BODY,
            fill=reaction_color
        )
        y += 18
        draw.text(
            (x, y),
            f"{snapshot.reaction_source} / {snapshot.reaction_state} @ {snapshot.reaction_minute:.2f}m",
            font=FONT_TINY,
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
    by_second = {
        value.replace(microsecond=0): value.replace(microsecond=0) for value in values
    }
    return sorted(by_second.values())


def _day_frame_times(
    calculator: HojakdoSceneCalculator, day_start: datetime, step_minutes: float
) -> list[datetime]:
    day_end = day_start + timedelta(days=1)
    values: list[datetime] = []
    cursor = day_start
    while cursor < day_end:
        values.append(cursor)
        cursor += timedelta(minutes=step_minutes)
    for plan in calculator.plans_intersecting(day_start, day_end):
        for phase in plan.phases:
            if phase.state in {
                "SPAWN_PINE",
                "SPAWN_PLUM",
                "LAND_ON_TIGER",
                "EXIT_RIGHT",
            }:
                values.append(plan.cycle_start + timedelta(minutes=phase.start + 0.08))
        day_actions = [
            action for action in plan.micro_actions if action.kind != "PECK_TIGER_EAR"
        ][:1]
        day_actions.extend(
            action for action in plan.micro_actions if action.kind == "PECK_TIGER_EAR"
        )
        for action in day_actions:
            values.append(
                plan.cycle_start + timedelta(minutes=(action.start + action.end) / 2.0)
            )
        values.append(plan.cycle_start + timedelta(minutes=plan.reaction_minute + 0.12))
        if plan.character == "SMALL":
            exit_phase = plan.phases[-1]
            for fraction in (0.24, 0.66):
                values.append(
                    plan.cycle_start
                    + timedelta(minutes=exit_phase.start + exit_phase.duration * fraction)
                )
    return [value for value in _unique_times(values) if day_start <= value < day_end]


def _detail_frame_times(plan: CyclePlan, step_minutes: float) -> list[datetime]:
    values: list[datetime] = []
    cursor = 0.0
    while cursor < plan.phases[-1].end:
        values.append(plan.cycle_start + timedelta(minutes=cursor))
        cursor += step_minutes
    for phase in plan.phases:
        values.append(plan.cycle_start + timedelta(minutes=phase.start + 0.02))
        values.append(
            plan.cycle_start + timedelta(minutes=max(phase.start, phase.end - 0.02))
        )
    for action in plan.micro_actions:
        for fraction in (0.05, 0.22, 0.42, 0.58, 0.78, 0.95):
            values.append(
                plan.cycle_start
                + timedelta(minutes=action.start + action.duration * fraction)
            )
    values.append(plan.cycle_start + timedelta(minutes=plan.reaction_minute + 0.15))
    return _unique_times(values)


def _peck_frame_times(plan: CyclePlan) -> list[datetime]:
    peck = next(action for action in plan.micro_actions if action.kind == "PECK_TIGER_EAR")
    start = max(0.0, peck.start - 0.55)
    end = min(plan.phases[-1].end, peck.end + 1.0)
    values: list[datetime] = []
    cursor = start
    while cursor <= end:
        values.append(plan.cycle_start + timedelta(minutes=cursor))
        cursor += 0.055
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


def _find_detail_plans(
    calculator: HojakdoSceneCalculator, source_day: datetime
) -> tuple[CyclePlan, CyclePlan]:
    plans = calculator.plans_intersecting(
        source_day - timedelta(days=40), source_day + timedelta(days=41)
    )

    def score(plan: CyclePlan, character: str) -> tuple[int, float]:
        value = 0
        if plan.route == "HOUR_TO_MINUTE":
            value += 8
        elif plan.route == "MINUTE_DIRECT":
            value += 5
        if any(action.kind == "TURN" for action in plan.micro_actions):
            value += 3
        if character == "SMALL" and plan.ear_peck:
            value += 6
        distance = abs((plan.cycle_start - (source_day + timedelta(hours=12))).total_seconds())
        return value, -distance

    large = max(
        (plan for plan in plans if plan.character == "LARGE"),
        key=lambda plan: score(plan, "LARGE"),
    )
    small = max(
        (plan for plan in plans if plan.character == "SMALL" and plan.ear_peck),
        key=lambda plan: score(plan, "SMALL"),
    )
    return large, small


def _action_time(plan: CyclePlan, kind: str, fallback: float) -> datetime:
    action = next((item for item in plan.micro_actions if item.kind == kind), None)
    local = fallback if action is None else (action.start + action.end) / 2.0
    return plan.cycle_start + timedelta(minutes=local)


def _comparison_sheet(
    renderer: PrototypeRenderer,
    large: CyclePlan,
    small: CyclePlan,
    output_path: Path,
) -> None:
    large_exit = large.phases[-1]
    small_exit = small.phases[-1]
    large_samples = [
        (
            "LONG RIDE",
            large.cycle_start
            + timedelta(
                minutes=max(
                    0.0,
                    next(
                        (
                            action.start - 0.8
                            for action in large.micro_actions
                            if action.kind == "HEAD_TILT"
                        ),
                        18.0,
                    ),
                )
            ),
        ),
        ("HEAD TILT", _action_time(large, "HEAD_TILT", 18.0)),
        ("TURN / SETTLE", _action_time(large, "TURN", 28.0)),
        (
            "TIGER RESPONSE",
            large.cycle_start + timedelta(minutes=large.reaction_minute + 0.28),
        ),
        (
            "FOLDED-WING JUMP",
            large.cycle_start
            + timedelta(minutes=large_exit.start + large_exit.duration * 0.58),
        ),
    ]
    small_samples = [
        ("HEAD SCAN", _action_time(small, "HEAD_SCAN", 13.0)),
        ("LOOK TO PLUM", _action_time(small, "LOOK_PLUM", 22.0)),
        ("TWO EAR PECKS", _action_time(small, "PECK_TIGER_EAR", 40.0)),
        (
            "WING FLAP 1/2",
            small.cycle_start
            + timedelta(minutes=small_exit.start + small_exit.duration * 0.24),
        ),
        (
            "WING FLAP 2/2",
            small.cycle_start
            + timedelta(minutes=small_exit.start + small_exit.duration * 0.66),
        ),
    ]
    rows = [("LARGE / CALM", large_samples), ("SMALL / ACTIVE", small_samples)]
    cell_width = 230
    face_height = 230
    label_height = 44
    sheet = Image.new(
        "RGB", (cell_width * 5, (face_height + label_height) * 2), (18, 20, 22)
    )
    draw = ImageDraw.Draw(sheet)
    for row_index, (row_label, samples) in enumerate(rows):
        for column, (label, timestamp) in enumerate(samples):
            snapshot = renderer.calculator.snapshot(timestamp)
            face = renderer.render_face(
                timestamp, snapshot, guides=False, clock_label=False
            ).convert("RGB")
            thumb = face.resize((cell_width, face_height), Image.Resampling.LANCZOS)
            x = column * cell_width
            y = row_index * (face_height + label_height)
            sheet.paste(thumb, (x, y))
            draw.rectangle(
                (x, y + face_height, x + cell_width, y + face_height + label_height),
                fill=(18, 20, 22),
            )
            draw.text(
                (x + 8, y + face_height + 6),
                label,
                font=FONT_BODY_BOLD,
                fill=(238, 234, 222),
            )
            draw.text(
                (x + 8, y + face_height + 25),
                row_label,
                font=FONT_TINY,
                fill=(146, 153, 162),
            )
    sheet.save(output_path, optimize=True)


def _landing_events(
    calculator: HojakdoSceneCalculator, start: datetime, end: datetime
) -> list[tuple[datetime, CyclePlan]]:
    plans = calculator.plans_intersecting(
        start - timedelta(minutes=calculator.cycle_minutes), end
    )
    result: list[tuple[datetime, CyclePlan]] = []
    for plan in plans:
        if plan.route == "PLUM_WALK":
            continue
        landing = next(phase for phase in plan.phases if phase.state == "LAND_ON_HAND")
        timestamp = plan.cycle_start + timedelta(minutes=landing.end)
        if start <= timestamp < end:
            result.append((timestamp, plan))
    return result


def _plan_report(plan: CyclePlan) -> dict[str, object]:
    return {
        "cycleIndex": plan.cycle_index,
        "cycleStart": plan.cycle_start.isoformat(),
        "character": plan.character,
        "route": plan.route,
        "selectedHand": plan.selected_hand,
        "initialFacing": plan.initial_facing,
        "earPeck": plan.ear_peck,
        "reactionMinute": round(plan.reaction_minute, 3),
        "reactionState": plan.reaction_state,
        "reactionSource": plan.reaction_source,
        "hourScore": plan.hour_evaluation.score,
        "minuteScore": plan.minute_evaluation.score,
        "phases": [
            {
                "state": phase.state,
                "startMinute": phase.start,
                "endMinute": phase.end,
                "hand": phase.hand,
            }
            for phase in plan.phases
        ],
        "microActions": [
            {
                "kind": action.kind,
                "startMinute": round(action.start, 3),
                "endMinute": round(action.end, 3),
                "sourceState": action.source_state,
            }
            for action in plan.micro_actions
        ],
    }


def _write_report(
    calculator: HojakdoSceneCalculator,
    source_day: datetime,
    large: CyclePlan,
    small: CyclePlan,
    frame_counts: dict[str, int],
    output_dir: Path,
) -> None:
    report_start = source_day
    report_end = report_start + timedelta(days=30)
    events = _landing_events(calculator, report_start, report_end)
    daily_counts: dict[str, int] = {}
    for offset in range(30):
        day = report_start + timedelta(days=offset)
        daily_counts[day.date().isoformat()] = sum(
            day <= timestamp < day + timedelta(days=1) for timestamp, _ in events
        )
    counts = list(daily_counts.values())
    route_counts = Counter(plan.route for _, plan in events)
    character_counts = Counter(plan.character for _, plan in events)
    combinations = Counter(
        f"{plan.character}:{plan.route}" for _, plan in events
    )
    cycle_plans = calculator.plans_intersecting(report_start, report_end)
    small_cycles = [plan for plan in cycle_plans if plan.character == "SMALL"]
    report = {
        "schemaVersion": 2,
        "status": "integrated_v2_simulation_generated",
        "sourceDate": source_day.date().isoformat(),
        "cycleMinutes": calculator.cycle_minutes,
        "hiddenMinutes": calculator.hidden_minutes,
        "handLandingWindow": {
            "start": report_start.isoformat(),
            "endExclusive": report_end.isoformat(),
            "days": 30,
            "countingRule": "actual LAND_ON_HAND completion timestamp",
            "total": len(events),
            "averagePerDay": round(sum(counts) / len(counts), 3),
            "minimumPerDay": min(counts),
            "maximumPerDay": max(counts),
            "dailyCounts": daily_counts,
        },
        "routeCounts": dict(route_counts),
        "characterCounts": dict(character_counts),
        "characterRouteCounts": dict(combinations),
        "smallEarPeck": {
            "smallCycleCount": len(small_cycles),
            "peckCycleCount": sum(plan.ear_peck for plan in small_cycles),
            "rule": "exactly two of every three consecutive small-magpie cycles",
        },
        "frameCounts": frame_counts,
        "largeDetailCycle": _plan_report(large),
        "smallDetailCycle": _plan_report(small),
        "outputs": [
            "hojakdo_v2_24h_debug.gif",
            "hojakdo_v2_large_cycle_detail.gif",
            "hojakdo_v2_small_cycle_detail.gif",
            "hojakdo_v2_small_ear_peck_detail.gif",
            "hojakdo_v2_motion_comparison.png",
            "route_report_30d.json",
        ],
        "assetStatus": {
            "largeMagpie": "clean approved V1 master",
            "smallMagpie": "legacy layer with render-only silhouette mask; clean master pending",
            "tiger": "existing separated head and pupil layers",
        },
        "completionLevel": "integrated_static_simulation_prototype",
        "wffConnected": False,
        "agifProduced": False,
    }
    (output_dir / "route_report_30d.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def render_all(source_date: date, output_dir: Path) -> None:
    calculator = HojakdoSceneCalculator()
    renderer = PrototypeRenderer(calculator)
    output_dir.mkdir(parents=True, exist_ok=True)
    render_config = calculator.config["render"]
    day_start = datetime.combine(source_date, time.min)
    large, small = _find_detail_plans(calculator, day_start)
    frame_counts: dict[str, int] = {}

    day_times = _day_frame_times(
        calculator, day_start, float(render_config["dayStepMinutes"])
    )
    day_frames = [renderer.render_debug_frame(timestamp) for timestamp in day_times]
    _save_gif(
        day_frames,
        output_dir / "hojakdo_v2_24h_debug.gif",
        int(render_config["dayFrameDurationMs"]),
        int(render_config["dayGifColors"]),
    )
    frame_counts["day24h"] = len(day_frames)
    del day_frames
    gc.collect()

    for label, plan, filename in (
        ("largeCycle", large, "hojakdo_v2_large_cycle_detail.gif"),
        ("smallCycle", small, "hojakdo_v2_small_cycle_detail.gif"),
    ):
        detail_times = _detail_frame_times(
            plan, float(render_config["detailStepMinutes"])
        )
        frames = [renderer.render_debug_frame(timestamp) for timestamp in detail_times]
        _save_gif(
            frames,
            output_dir / filename,
            int(render_config["detailFrameDurationMs"]),
            int(render_config["gifColors"]),
        )
        frame_counts[label] = len(frames)
        del frames
        gc.collect()

    peck_times = _peck_frame_times(small)
    peck_frames = [renderer.render_debug_frame(timestamp) for timestamp in peck_times]
    _save_gif(
        peck_frames,
        output_dir / "hojakdo_v2_small_ear_peck_detail.gif",
        90,
        int(render_config["gifColors"]),
    )
    frame_counts["smallEarPeck"] = len(peck_frames)
    del peck_frames
    gc.collect()

    _comparison_sheet(
        renderer, large, small, output_dir / "hojakdo_v2_motion_comparison.png"
    )
    _write_report(
        calculator, day_start, large, small, frame_counts, output_dir
    )


def main() -> None:
    calculator = HojakdoSceneCalculator()
    parser = argparse.ArgumentParser(
        description="Render the deterministic two-magpie Hojakdo V2 prototype"
    )
    parser.add_argument(
        "--date",
        default=calculator.config["render"]["sourceDate"],
        help="Source day in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for GIFs, comparison sheet, and report",
    )
    args = parser.parse_args()
    render_all(date.fromisoformat(args.date), args.output_dir)


if __name__ == "__main__":
    main()

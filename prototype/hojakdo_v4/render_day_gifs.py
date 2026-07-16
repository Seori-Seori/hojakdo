from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
V4_ROOT = REPO_ROOT / "assets/layers/v4"
DRAWABLE_DIR = V4_ROOT / "drawable"
FRAME_DIR = V4_ROOT / "frames"
MANIFEST_PATH = V4_ROOT / "manifest.json"
OUTPUT_DIR = PACKAGE_DIR / "output"

FACE_SIZE = 450
PIVOT = (224.0, 207.0)
READOUT_CENTER_X = 225
DEFAULT_DATE = date(2026, 7, 13)
DEFAULT_BATTERY_PERCENT = 100
GIF_FPS = 20
CHUNK_HOURS = 6
CHUNK_MINUTES = CHUNK_HOURS * 60
EVENT_FRAME_COUNT = 8


@dataclass(frozen=True)
class TimelineState:
    timestamp: datetime
    minute_key: int
    cycle_index: int
    cycle_local: int
    character: str
    route: str
    action: str
    animation: str | None

    def serializable(self) -> dict[str, object]:
        value = asdict(self)
        value["timestamp"] = self.timestamp.isoformat(timespec="minutes")
        return value


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSerif-Bold.ttf" if bold else "DejaVuSerif.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    return ImageFont.truetype(str(path), size=size)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    center_x: float = READOUT_CENTER_X,
) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text((center_x - (box[2] - box[0]) / 2, y), text, font=font, fill=fill)


def timeline_state(timestamp: datetime) -> TimelineState:
    """Evaluate the same stateless minute expressions used by watchface.xml."""
    day_of_year = timestamp.timetuple().tm_yday
    minute_key = (
        timestamp.year * 527_040
        + day_of_year * 1_440
        + timestamp.hour * 60
        + timestamp.minute
        - 32
    )
    cycle_index, cycle_local = divmod(minute_key, 43)
    character = "LARGE" if cycle_index % 2 == 0 else "SMALL"
    route_remainder = cycle_index % 11
    if route_remainder == 0:
        route = "HOUR"
    elif route_remainder == 5:
        route = "MINUTE"
    else:
        route = "PLUM"

    prefix = "magpie_large" if character == "LARGE" else "magpie_small"
    animation: str | None = None
    action = "HIDDEN"
    if cycle_local == 2:
        if route in {"HOUR", "MINUTE"}:
            animation = f"{prefix}_fly_pine_to_hand"
            action = "FLY_TO_HAND"
        else:
            animation = f"{prefix}_walk_step"
            action = "WALK_PLUM"
    elif cycle_local == 3:
        if route in {"HOUR", "MINUTE"}:
            animation = f"{prefix}_land_on_hand"
            action = "LAND_HAND"
        else:
            action = "PLUM_IDLE"
    elif 4 <= cycle_local <= 8:
        action = "HAND_RIDE" if route in {"HOUR", "MINUTE"} else "PLUM_IDLE"
    elif cycle_local == 9:
        animation = f"{prefix}_hop_to_tiger"
        action = "HOP_TIGER"
    elif cycle_local == 10:
        animation = "tiger_head_eye_reaction"
        action = "TIGER_REACT"
    elif cycle_local == 11:
        animation = (
            "magpie_large_head_tilt"
            if character == "LARGE"
            else "magpie_small_head_scan"
        )
        action = "HEAD_ACTION"
    elif cycle_local == 12:
        animation = (
            "magpie_large_turn_perch"
            if character == "LARGE"
            else "magpie_small_look_plum"
        )
        action = "TURN_OR_LOOK"
    elif cycle_local == 13 and character == "SMALL":
        animation = "magpie_small_turn_hop"
        action = "TURN_HOP"
    elif cycle_local == 14 and character == "SMALL":
        animation = "magpie_small_peck_tiger_ear"
        action = "PECK_EAR"
    elif (
        character == "LARGE" and 13 <= cycle_local <= 40
    ) or (
        character == "SMALL" and 15 <= cycle_local <= 40
    ):
        action = "TIGER_IDLE"
    elif cycle_local == 41:
        if character == "LARGE":
            animation = "magpie_large_exit_right_jump"
        action = "EXIT_RIGHT"

    return TimelineState(
        timestamp=timestamp,
        minute_key=minute_key,
        cycle_index=cycle_index,
        cycle_local=cycle_local,
        character=character,
        route=route,
        action=action,
        animation=animation,
    )


def _rotate_point(
    point: tuple[float, float], clockwise_degrees: float
) -> tuple[float, float]:
    radians = math.radians(clockwise_degrees)
    dx = point[0] - PIVOT[0]
    dy = point[1] - PIVOT[1]
    return (
        PIVOT[0] + dx * math.cos(radians) - dy * math.sin(radians),
        PIVOT[1] + dx * math.sin(radians) + dy * math.cos(radians),
    )


class DayReviewRenderer:
    """Rasterize the current WFF scene order for fast full-day review."""

    def __init__(self, battery_percent: int = DEFAULT_BATTERY_PERCENT) -> None:
        if not 0 <= battery_percent <= 100:
            raise ValueError("battery_percent must be between 0 and 100")
        self.battery_percent = battery_percent
        self.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.poses = {item["id"]: item for item in self.manifest["staticPoses"]}
        self.animations = {item["id"]: item for item in self.manifest["animations"]}
        self.tiger_anchors = {
            name: tuple(float(value) for value in point)
            for name, point in self.manifest["scene"]["tigerPerchAnchors"].items()
        }
        self.layers = {
            path.stem: self._load(path)
            for path in DRAWABLE_DIR.glob("*.png")
        }
        self.animation_frames: dict[str, tuple[Image.Image, ...]] = {}
        self.full_bloom = next(
            item
            for item in self.manifest["plumBatteryStages"]
            if int(item["minimumPercent"])
            <= battery_percent
            <= int(item["maximumPercent"])
        )
        self.time_font = _font(25, bold=True)
        self.date_font = _font(11, bold=True)
        self.weekday_font = _font(9, bold=True)
        self.battery_font = _font(12, bold=True)
        self.debug_font = _font(9, bold=True)

    @staticmethod
    def _load(path: Path) -> Image.Image:
        with Image.open(path) as source:
            return source.convert("RGBA")

    def _frames(self, animation: str) -> tuple[Image.Image, ...]:
        if animation not in self.animation_frames:
            paths = sorted((FRAME_DIR / animation).glob("frame_*.png"))
            self.animation_frames[animation] = tuple(self._load(path) for path in paths)
        return self.animation_frames[animation]

    def _composite_pose(
        self,
        face: Image.Image,
        pose_id: str,
        foot: tuple[float, float],
    ) -> None:
        pose = self.poses[pose_id]
        anchor_x, anchor_y = (float(value) for value in pose["anchorLogical"])
        face.alpha_composite(
            self.layers[pose_id],
            (round(foot[0] - anchor_x), round(foot[1] - anchor_y)),
        )

    def _hand_angle(self, hand: str, timestamp: datetime) -> float:
        minute_of_day = (
            timestamp.hour * 60
            + timestamp.minute
            + timestamp.second / 60
            + timestamp.microsecond / 60_000_000
        )
        if hand == "hour":
            return minute_of_day * 0.5 - 50.232272878132
        return minute_of_day * 6.0 - 325.271003720479

    def _composite_hand(
        self,
        face: Image.Image,
        hand: str,
        timestamp: datetime,
        state: TimelineState,
    ) -> None:
        angle = self._hand_angle(hand, timestamp)
        branch = self.layers[f"hojakdo_v4_{hand}_branch"].rotate(
            -angle,
            center=PIVOT,
            resample=Image.Resampling.BICUBIC,
            expand=False,
        )
        face.alpha_composite(branch)
        if state.route != hand.upper() or not 4 <= state.cycle_local <= 8:
            return

        if hand == "hour":
            anchors = {"LARGE": (305.0, 143.0), "SMALL": (302.0, 148.0)}
        else:
            anchors = {"LARGE": (159.0, 118.0), "SMALL": (171.0, 122.0)}
        foot = _rotate_point(anchors[state.character], angle)
        pose_id = (
            "magpie_large_perch_hand"
            if state.character == "LARGE"
            else "magpie_small_perch_hand"
        )
        self._composite_pose(face, pose_id, foot)

    def _composite_plum_bird(
        self, face: Image.Image, state: TimelineState
    ) -> None:
        if state.action != "PLUM_IDLE":
            return
        if state.character == "LARGE":
            self._composite_pose(face, "magpie_large_walk_idle", (151, 337))
        else:
            self._composite_pose(face, "magpie_small_walk_idle", (155, 336))

    def _composite_tiger_bird(
        self,
        face: Image.Image,
        state: TimelineState,
        exit_progress: float | None,
    ) -> None:
        if state.action in {"TIGER_IDLE", "TIGER_REACT"}:
            if state.character == "LARGE":
                self._composite_pose(
                    face,
                    "magpie_large_perch_tiger",
                    self.tiger_anchors["LARGE"],
                )
            else:
                self._composite_pose(
                    face,
                    "magpie_small_perch_tiger",
                    self.tiger_anchors["SMALL"],
                )
        elif state.action == "EXIT_RIGHT" and state.character == "SMALL":
            progress = 0.0 if exit_progress is None else exit_progress
            flight = self.manifest["smallFlight"]
            anchor_x, anchor_y = (
                float(value) for value in flight["anchorLogical"]
            )
            start_x = round(self.tiger_anchors["SMALL"][0] - anchor_x)
            start_y = round(self.tiger_anchors["SMALL"][1] - anchor_y)
            x = round(start_x + 204 * progress)
            y = round(start_y - 163 * progress + 96 * progress * progress)
            face.alpha_composite(self.layers["magpie_small_flight_right_v4"], (x, y))

    def _composite_animation(
        self,
        face: Image.Image,
        state: TimelineState,
        animation_frame: int | None,
    ) -> None:
        if state.animation is None:
            return
        frames = self._frames(state.animation)
        if not frames:
            return
        index = 0 if animation_frame is None else min(animation_frame, len(frames) - 1)
        metadata = self.animations[state.animation]
        placement = tuple(int(value) for value in metadata["placementLogical"])
        face.alpha_composite(frames[index], placement)

    def _composite_plum_foreground(self, face: Image.Image) -> None:
        masks = {item["id"]: item for item in self.manifest["foregroundMasks"]}
        plum_mask = masks["plum_foreground_mask"]
        face.alpha_composite(
            self.layers["plum_foreground_mask"],
            tuple(int(value) for value in plum_mask["placementLogical"]),
        )

        bloom_placement = tuple(
            int(value) for value in self.full_bloom["placementLogical"]
        )
        bloom_name = Path(str(self.full_bloom["resource"])).stem
        face.alpha_composite(self.layers[bloom_name], bloom_placement)

    def _composite_pine_and_tiger(
        self,
        face: Image.Image,
        state: TimelineState,
        animation_frame: int | None,
    ) -> None:
        masks = {item["id"]: item for item in self.manifest["foregroundMasks"]}
        for name in ("pine_foreground_mask", "tiger_body_foreground_mask"):
            metadata = masks[name]
            placement = tuple(int(value) for value in metadata["placementLogical"])
            face.alpha_composite(self.layers[name], placement)
        if state.animation == "tiger_head_eye_reaction":
            # The moving head replaces the static head for this slot. Drawing
            # both versions at once visually averaged the motion into a
            # frozen-looking tiger.
            self._composite_animation(face, state, animation_frame)
        else:
            face.alpha_composite(self.layers["hojakdo_v4_tiger_head"])
            face.alpha_composite(self.layers["hojakdo_v4_tiger_pupils"])

    def _draw_live_data(
        self, face: Image.Image, timestamp: datetime, state: TimelineState
    ) -> None:
        draw = ImageDraw.Draw(face)
        ink = (31, 24, 17, 255)
        _draw_centered(
            draw,
            250,
            timestamp.strftime("%H:%M"),
            self.time_font,
            ink,
        )
        _draw_centered(
            draw,
            278,
            timestamp.strftime("%m.%d"),
            self.date_font,
            ink,
        )
        _draw_centered(
            draw,
            293,
            timestamp.strftime("%a").upper(),
            self.weekday_font,
            ink,
        )
        face.alpha_composite(self.layers["battery_icon"], (186, 418))
        draw.text(
            (208, 416),
            f"{self.battery_percent}%",
            font=self.battery_font,
            fill=ink,
        )

        # This label lives in the black corner outside the circular dial. It is
        # review-only and makes a bad frame traceable to the exact WFF minute.
        debug = (
            f"{state.character[0]} {state.route[:3]} "
            f"C{state.cycle_local:02d} {state.action}"
        )
        draw.text((7, 7), debug, font=self.debug_font, fill=(225, 212, 187, 255))

    def render(
        self,
        timestamp: datetime,
        *,
        animation_frame: int | None = None,
        exit_progress: float | None = None,
    ) -> Image.Image:
        state = timeline_state(timestamp)
        face = self.layers["hojakdo_v4_background"].copy()
        patch = self.manifest["readoutHanjiPatch"]
        face.alpha_composite(
            self.layers["hojakdo_v4_readout_hanji_patch"],
            tuple(int(value) for value in patch["placementLogical"]),
        )
        # Mirror the production WFF order: resolve every environmental mask
        # and the tiger before either hand, then keep active birds above them.
        self._composite_plum_bird(face, state)
        if state.animation is not None and state.animation.endswith("_walk_step"):
            self._composite_animation(face, state, animation_frame)
        self._composite_plum_foreground(face)
        self._composite_pine_and_tiger(face, state, animation_frame)
        self._composite_hand(face, "hour", timestamp, state)
        self._composite_hand(face, "minute", timestamp, state)
        self._composite_tiger_bird(face, state, exit_progress)
        if state.animation is not None and not (
            state.animation.endswith("_walk_step")
            or state.animation == "tiger_head_eye_reaction"
        ):
            self._composite_animation(face, state, animation_frame)
        self._draw_live_data(face, timestamp, state)
        return face.convert("RGB")

    def review_frames(
        self, timestamp: datetime
    ) -> list[tuple[Image.Image, TimelineState]]:
        state = timeline_state(timestamp)
        if state.animation is not None:
            frames = self._frames(state.animation)
            count = max(1, len(frames))
            return [
                (
                    self.render(
                        timestamp + timedelta(seconds=index * 0.125),
                        animation_frame=index,
                    ),
                    state,
                )
                for index in range(count)
            ]
        if state.action == "EXIT_RIGHT" and state.character == "SMALL":
            return [
                (
                    self.render(
                        timestamp + timedelta(seconds=59.9 * index / (EVENT_FRAME_COUNT - 1)),
                        exit_progress=index / (EVENT_FRAME_COUNT - 1),
                    ),
                    state,
                )
                for index in range(EVENT_FRAME_COUNT)
            ]
        return [(self.render(timestamp), state)]


class _GifWriter:
    """Stream frames through one FFmpeg palette graph without staging video."""

    def __init__(self, output: Path, fps: int = GIF_FPS) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required to render the day-review GIFs")
        self.ffmpeg = ffmpeg
        self.output = output
        self.fps = fps
        output.parent.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pixel_format",
                "rgb24",
                "-video_size",
                f"{FACE_SIZE}x{FACE_SIZE}",
                "-framerate",
                str(fps),
                "-i",
                "pipe:0",
                "-filter_complex",
                (
                    "[0:v]split[a][b];"
                    "[a]palettegen=max_colors=192:stats_mode=diff[p];"
                    "[b][p]paletteuse=dither=bayer:bayer_scale=3:"
                    "diff_mode=rectangle"
                ),
                "-loop",
                "0",
                str(self.output),
            ],
            stdin=subprocess.PIPE,
        )
        self.frame_count = 0

    def append(self, frame: Image.Image) -> None:
        if self.process.stdin is None:
            raise RuntimeError("GIF encoder stdin is unavailable")
        self.process.stdin.write(frame.convert("RGB").tobytes())
        self.frame_count += 1

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        if self.process.wait() != 0:
            raise RuntimeError("FFmpeg GIF encode failed")


def render_day(
    review_date: date = DEFAULT_DATE,
    battery_percent: int = DEFAULT_BATTERY_PERCENT,
) -> dict[str, object]:
    renderer = DayReviewRenderer(battery_percent=battery_percent)
    chunks: list[dict[str, object]] = []
    day_start = datetime.combine(review_date, datetime.min.time())
    for start_hour in range(0, 24, CHUNK_HOURS):
        end_hour = start_hour + CHUNK_HOURS
        output = OUTPUT_DIR / f"hojakdo_v4_day_{start_hour:02d}_{end_hour:02d}.gif"
        writer = _GifWriter(output)
        events: list[dict[str, object]] = []
        for minute_offset in range(CHUNK_MINUTES):
            timestamp = day_start + timedelta(
                hours=start_hour, minutes=minute_offset
            )
            frames = renderer.review_frames(timestamp)
            state = frames[0][1]
            if len(frames) > 1 or state.action not in {
                "HIDDEN",
                "PLUM_IDLE",
                "HAND_RIDE",
                "TIGER_IDLE",
            }:
                events.append(state.serializable())
            for frame, _ in frames:
                writer.append(frame)
        writer.close()
        chunks.append(
            {
                "start": f"{start_hour:02d}:00",
                "endExclusive": f"{end_hour:02d}:00",
                "resource": output.name,
                "size": [FACE_SIZE, FACE_SIZE],
                "fps": GIF_FPS,
                "frameCount": writer.frame_count,
                "durationSeconds": round(writer.frame_count / GIF_FPS, 3),
                "sha256": _sha256(output),
                "events": events,
            }
        )
        print(
            f"{output} frames={writer.frame_count} "
            f"duration={writer.frame_count / GIF_FPS:.2f}s"
        )

    emulator_reference = timeline_state(datetime(2026, 7, 13, 6, 5))
    review_manifest: dict[str, object] = {
        "schemaVersion": 1,
        "date": review_date.isoformat(),
        "batteryPercent": battery_percent,
        "chunkHours": CHUNK_HOURS,
        "sampling": "every simulated minute; full AGIF frames at active minutes",
        "sceneOrder": (
            "environment and tiger below both hands; tiger reaction replaces "
            "the static head; active birds remain above the hands"
        ),
        "emulatorReference": emulator_reference.serializable(),
        "chunks": chunks,
    }
    manifest_path = OUTPUT_DIR / "hojakdo_v4_day_review_manifest.json"
    manifest_path.write_text(
        json.dumps(review_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(manifest_path)
    return review_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the current Hojakdo V4 WFF timeline as four 6-hour GIFs."
    )
    parser.add_argument(
        "--date",
        default=DEFAULT_DATE.isoformat(),
        help="local review date in YYYY-MM-DD form",
    )
    parser.add_argument(
        "--battery",
        type=int,
        default=DEFAULT_BATTERY_PERCENT,
        help="fixed battery percent for the complete review",
    )
    args = parser.parse_args()
    render_day(date.fromisoformat(args.date), args.battery)


if __name__ == "__main__":
    main()

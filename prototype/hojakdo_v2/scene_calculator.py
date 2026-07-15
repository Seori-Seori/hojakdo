from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


CONFIG_PATH = Path(__file__).with_name("config.json")
CHARACTERS = ("LARGE", "SMALL")


@dataclass(frozen=True)
class Phase:
    state: str
    start: float
    end: float
    hand: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class MicroAction:
    kind: str
    start: float
    end: float
    source_state: str

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class HandEvaluation:
    hand: str
    eligible: bool
    score: float
    landing_angle: float
    landing_point: tuple[float, float]
    screen_margin: float
    tiger_approach_minute: float | None
    tiger_distance: float
    meeting_minute: float | None
    meeting_distance: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CyclePlan:
    cycle_index: int
    cycle_start: datetime
    character: str
    route: str
    selected_hand: str | None
    phases: tuple[Phase, ...]
    micro_actions: tuple[MicroAction, ...]
    initial_facing: str
    ear_peck: bool
    reaction_minute: float
    reaction_state: str
    reaction_source: str
    hour_evaluation: HandEvaluation
    minute_evaluation: HandEvaluation
    selection_pick: int
    opportunity_accepted: bool

    @property
    def cycle_end(self) -> datetime:
        return self.cycle_start + timedelta(minutes=self.phases[-1].end)


@dataclass(frozen=True)
class SceneSnapshot:
    timestamp: datetime
    cycle_index: int
    cycle_start: datetime
    cycle_progress: float
    character: str
    route: str
    selected_hand: str | None
    state: str
    next_state: str
    state_progress: float
    render_slot: str
    visible: bool
    foot_position: tuple[float, float] | None
    facing: str
    micro_action: str | None
    micro_progress: float
    tiger_reacting: bool
    tiger_reaction_progress: float
    reaction_state: str
    reaction_source: str
    reaction_minute: float
    ear_peck: bool
    wing_flap_beat: int
    wing_flap_progress: float
    hour_score: float
    minute_score: float
    hour_eligible: bool
    minute_eligible: bool
    opportunity_accepted: bool

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("timestamp", "cycle_start"):
            result[key] = result[key].isoformat()
        return result


class HojakdoSceneCalculator:
    """Stateless deterministic scene calculator for the approved V2 behavior."""

    def __init__(self, config_path: Path | str = CONFIG_PATH) -> None:
        self.config_path = Path(config_path)
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.epoch = datetime.fromisoformat(self.config["timeline"]["epoch"])
        self.cycle_minutes = float(self.config["timeline"]["cycleMinutes"])
        self.cycle_offset = float(self.config["timeline"]["cycleOffsetMinutes"])
        self.hidden_minutes = float(self.config["timeline"]["hiddenMinutes"])
        self.duration = self.config["durationsMinutes"]
        self.geometry = self.config["geometry"]
        self.selection = self.config["selection"]
        self.motion = self.config["motion"]

    def absolute_minute(self, timestamp: datetime) -> float:
        return (timestamp - self.epoch).total_seconds() / 60.0

    def cycle_index_at(self, timestamp: datetime) -> int:
        value = self.absolute_minute(timestamp) - self.cycle_offset
        return math.floor(value / self.cycle_minutes)

    def cycle_start_for_index(self, cycle_index: int) -> datetime:
        minute = self.cycle_offset + cycle_index * self.cycle_minutes
        return self.epoch + timedelta(minutes=minute)

    def cycle_local_minute(
        self, timestamp: datetime, cycle_index: int | None = None
    ) -> float:
        index = self.cycle_index_at(timestamp) if cycle_index is None else cycle_index
        return (timestamp - self.cycle_start_for_index(index)).total_seconds() / 60.0

    @staticmethod
    def character_for_cycle(cycle_index: int) -> str:
        return "LARGE" if cycle_index % 2 == 0 else "SMALL"

    @staticmethod
    def _rotate_point(
        point: Iterable[float], pivot: Iterable[float], clockwise_degrees: float
    ) -> tuple[float, float]:
        px, py = pivot
        x, y = point
        radians = math.radians(clockwise_degrees)
        dx = x - px
        dy = y - py
        return (
            px + dx * math.cos(radians) - dy * math.sin(radians),
            py + dx * math.sin(radians) + dy * math.cos(radians),
        )

    def hand_group_angle(self, hand: str, timestamp: datetime) -> float:
        minute_of_day = (
            timestamp.hour * 60
            + timestamp.minute
            + timestamp.second / 60.0
            + timestamp.microsecond / 60_000_000.0
        )
        if hand == "minute":
            return minute_of_day * 6.0 + float(self.geometry["minuteHandAngleOffset"])
        if hand == "hour":
            return minute_of_day * 0.5 + float(self.geometry["hourHandAngleOffset"])
        raise ValueError(f"Unknown hand: {hand}")

    def hand_anchor(
        self, hand: str, timestamp: datetime, character: str = "LARGE"
    ) -> tuple[float, float]:
        if character not in CHARACTERS:
            raise ValueError(f"Unknown character: {character}")
        key = "minuteHandAnchorAtZero" if hand == "minute" else "hourHandAnchorAtZero"
        return self._rotate_point(
            self.geometry[key][character],
            self.geometry["clockPivot"],
            self.hand_group_angle(hand, timestamp),
        )

    def _selection_hand_anchor(
        self, hand: str, timestamp: datetime, character: str
    ) -> tuple[float, float]:
        """Evaluate routes with V2.1 geometry while V2.2 adjusts rendering only."""
        key = "minuteHandAnchorAtZero" if hand == "minute" else "hourHandAnchorAtZero"
        reference = self.geometry.get("selectionReference", {})
        points = reference.get(key, self.geometry[key])
        return self._rotate_point(
            points[character],
            self.geometry["clockPivot"],
            self.hand_group_angle(hand, timestamp),
        )

    def hand_clock_angle(
        self, hand: str, timestamp: datetime, character: str
    ) -> float:
        x, y = self.hand_anchor(hand, timestamp, character)
        pivot_x, pivot_y = self.geometry["clockPivot"]
        return math.degrees(math.atan2(x - pivot_x, pivot_y - y)) % 360.0

    def _selection_hand_clock_angle(
        self, hand: str, timestamp: datetime, character: str
    ) -> float:
        x, y = self._selection_hand_anchor(hand, timestamp, character)
        pivot_x, pivot_y = self.geometry["clockPivot"]
        return math.degrees(math.atan2(x - pivot_x, pivot_y - y)) % 360.0

    @staticmethod
    def angular_distance(a: float, b: float) -> float:
        return abs((a - b + 180.0) % 360.0 - 180.0)

    @staticmethod
    def distance(a: Iterable[float], b: Iterable[float]) -> float:
        ax, ay = a
        bx, by = b
        return math.hypot(ax - bx, ay - by)

    def _stable_pick(self, cycle_index: int, salt: int, modulo: int) -> int:
        day = self.cycle_start_for_index(cycle_index).toordinal()
        mixed = (day * 97 + cycle_index * 53 + salt * 31 + 17) % 1_000_003
        return mixed % modulo

    def _in_quadrant(self, angle: float) -> bool:
        return (
            float(self.selection["quadrantStartAngle"])
            <= angle
            <= float(self.selection["quadrantEndAngle"])
        )

    def _bird_screen_margin(
        self, foot: tuple[float, float], character: str
    ) -> float:
        reference = self.geometry.get("selectionReference", {})
        bounds = reference.get(
            "birdLogicalBoundsAtZero", self.geometry["birdLogicalBoundsAtZero"]
        )
        left, top, right, bottom = bounds[character]
        anchor_x, anchor_y = self.geometry["birdAssetAnchorAtZero"][character]
        shifted = (
            foot[0] + left - anchor_x,
            foot[1] + top - anchor_y,
            foot[0] + right - anchor_x,
            foot[1] + bottom - anchor_y,
        )
        width = float(self.config["logicalCanvas"]["width"])
        height = float(self.config["logicalCanvas"]["height"])
        return min(shifted[0], shifted[1], width - shifted[2], height - shifted[3])

    def _nominal_land_minute(self) -> float:
        return (
            self.cycle_minutes
            - float(self.duration["exitRight"])
            - float(self.duration["perchTiger"])
            - float(self.duration["landOnTiger"])
        )

    def _hand_ride_start(self) -> float:
        return (
            self.hidden_minutes
            + float(self.duration["spawnPine"])
            + float(self.duration["flyPineToHand"])
            + float(self.duration["landOnHand"])
            + float(self.duration["perchHand"])
        )

    def _find_minute_tiger_approach(
        self, cycle_start: datetime, earliest: float, character: str
    ) -> tuple[float, float]:
        nominal = self._nominal_land_minute()
        early = float(self.selection["tigerArrivalEarlyToleranceMinutes"])
        first = max(math.ceil(earliest), math.ceil(nominal - early))
        last = math.floor(nominal)
        reference = self.geometry.get("selectionReference", {})
        target = reference.get("tigerApproach", self.geometry["tigerApproach"])[
            character
        ]
        best_minute: float | None = None
        best_distance = math.inf
        for local_minute in range(first, last + 1):
            timestamp = cycle_start + timedelta(minutes=local_minute)
            current_distance = self.distance(
                self._selection_hand_anchor("minute", timestamp, character), target
            )
            if current_distance < best_distance:
                best_distance = current_distance
                best_minute = float(local_minute)
        if best_minute is None:
            raise AssertionError("Tiger approach search window is empty")
        return best_minute, best_distance

    def _find_hand_meeting(
        self,
        cycle_start: datetime,
        ride_start: float,
        target_minute: float,
        character: str,
    ) -> tuple[float | None, float]:
        first = math.ceil(ride_start + float(self.duration["minimumHourRide"]))
        last = math.floor(
            target_minute
            - float(self.duration["hopHandToHand"])
            - float(self.duration["minimumMinuteRideAfterTransfer"])
        )
        best_minute: float | None = None
        best_distance = math.inf
        for local_minute in range(first, last + 1):
            timestamp = cycle_start + timedelta(minutes=local_minute)
            current_distance = self.distance(
                self._selection_hand_anchor("hour", timestamp, character),
                self._selection_hand_anchor("minute", timestamp, character),
            )
            if current_distance < best_distance:
                best_distance = current_distance
                best_minute = float(local_minute)
        if best_distance > float(self.selection["handMeetingMaxDistance"]):
            return None, best_distance
        return best_minute, best_distance

    def _evaluate_hand(
        self, cycle_index: int, hand: str, character: str
    ) -> HandEvaluation:
        cycle_start = self.cycle_start_for_index(cycle_index)
        ride_start = self._hand_ride_start()
        landing_time = cycle_start + timedelta(minutes=ride_start)
        landing_point = self._selection_hand_anchor(hand, landing_time, character)
        landing_angle = self._selection_hand_clock_angle(
            hand, landing_time, character
        )
        reasons: list[str] = []

        if not self._in_quadrant(landing_angle):
            reasons.append("landing_outside_upper_left_quadrant")
        margin = self._bird_screen_margin(landing_point, character)
        if margin < 0:
            reasons.append("bird_crop_outside_screen")

        tiger_minute, tiger_distance = self._find_minute_tiger_approach(
            cycle_start, ride_start, character
        )
        base_distance = float(self.selection["tigerApproachBaseDistance"])
        extended_distance = float(self.selection["tigerApproachExtendedDistance"])
        borderline_pick = self._stable_pick(cycle_index, salt=97, modulo=100)
        tiger_accepted = tiger_distance <= base_distance or (
            tiger_distance <= extended_distance
            and borderline_pick < int(self.selection["borderlineOpportunityPercent"])
        )
        if not tiger_accepted:
            tiger_minute = None
            reasons.append("minute_hand_misses_tiger_arrival_window")

        meeting_minute: float | None = None
        meeting_distance: float | None = None
        if hand == "hour" and tiger_minute is not None:
            meeting_minute, raw_meeting_distance = self._find_hand_meeting(
                cycle_start, ride_start, tiger_minute, character
            )
            meeting_distance = raw_meeting_distance
            if meeting_minute is None:
                reasons.append("no_natural_hour_to_minute_meeting")

        eligible = not reasons
        weights = self.selection["weights"]
        ideal_distance = self.angular_distance(
            landing_angle, float(self.selection["idealQuadrantAngle"])
        )
        ideal_component = max(0.0, 1.0 - ideal_distance / 50.0)
        pine_distance = self.distance(
            self.geometry["pineSpawn"][character], landing_point
        )
        pine_component = max(0.0, 1.0 - pine_distance / 220.0)
        margin_component = max(0.0, min(1.0, margin / 40.0))
        nominal = self._nominal_land_minute()
        arrival_component = (
            0.0
            if tiger_minute is None
            else max(0.0, 1.0 - abs(nominal - tiger_minute) / 4.0)
        )
        character_bias = 0.0
        if character == "LARGE" and hand == "hour":
            character_bias = float(weights["largeHourBias"])
        elif character == "SMALL" and hand == "minute":
            character_bias = float(weights["smallMinuteBias"])

        score = (
            (float(weights["quadrant"]) if self._in_quadrant(landing_angle) else 0.0)
            + float(weights["idealAngle"]) * ideal_component
            + float(weights["pineAccess"]) * pine_component
            + float(weights["screenMargin"]) * margin_component
            + (float(weights["cycleCompletion"]) if tiger_minute is not None else 0.0)
            + float(weights["arrivalTiming"]) * arrival_component
            + character_bias
        )
        if meeting_distance is not None and meeting_minute is not None:
            score += max(0.0, 12.0 - meeting_distance / 8.0)
        if tiger_minute is not None:
            score += max(0.0, 8.0 - tiger_distance / 5.0)
        if not eligible:
            score -= 200.0

        return HandEvaluation(
            hand=hand,
            eligible=eligible,
            score=round(score, 3),
            landing_angle=round(landing_angle, 3),
            landing_point=(round(landing_point[0], 3), round(landing_point[1], 3)),
            screen_margin=round(margin, 3),
            tiger_approach_minute=tiger_minute,
            tiger_distance=round(tiger_distance, 3),
            meeting_minute=meeting_minute,
            meeting_distance=(
                None if meeting_distance is None else round(meeting_distance, 3)
            ),
            reasons=tuple(reasons),
        )

    def _choose_route(
        self, cycle_index: int, character: str
    ) -> tuple[
        str,
        str | None,
        HandEvaluation,
        HandEvaluation,
        int,
        bool,
    ]:
        hour = self._evaluate_hand(cycle_index, "hour", character)
        minute = self._evaluate_hand(cycle_index, "minute", character)
        selection_pick = self._stable_pick(cycle_index, salt=11, modulo=100)

        if hour.eligible and minute.eligible:
            hour_percent = float(
                self.selection[
                    "largeHourPreferencePercent"
                    if character == "LARGE"
                    else "smallHourPreferencePercent"
                ]
            )
            hand = "hour" if selection_pick < hour_percent else "minute"
        elif hour.eligible:
            hand = "hour"
        elif minute.eligible:
            hand = "minute"
        else:
            hand = None

        accepted = hand is not None

        if hand == "hour":
            return "HOUR_TO_MINUTE", hand, hour, minute, selection_pick, True
        if hand == "minute":
            return "MINUTE_DIRECT", hand, hour, minute, selection_pick, True
        return "PLUM_WALK", None, hour, minute, selection_pick, False

    def _build_phases(
        self,
        route: str,
        hour: HandEvaluation,
        minute: HandEvaluation,
    ) -> tuple[Phase, ...]:
        hidden_end = self.hidden_minutes
        exit_start = self.cycle_minutes - float(self.duration["exitRight"])
        nominal_land = self._nominal_land_minute()

        if route == "PLUM_WALK":
            spawn_end = hidden_end + float(self.duration["spawnPlum"])
            return (
                Phase("HIDDEN", 0.0, hidden_end),
                Phase("SPAWN_PLUM", hidden_end, spawn_end),
                Phase("WALK_FROM_PLUM", spawn_end, nominal_land),
                Phase(
                    "LAND_ON_TIGER",
                    nominal_land,
                    nominal_land + float(self.duration["landOnTiger"]),
                ),
                Phase(
                    "PERCH_TIGER",
                    nominal_land + float(self.duration["landOnTiger"]),
                    exit_start,
                ),
                Phase("EXIT_RIGHT", exit_start, self.cycle_minutes),
            )

        spawn_end = hidden_end + float(self.duration["spawnPine"])
        fly_end = spawn_end + float(self.duration["flyPineToHand"])
        land_end = fly_end + float(self.duration["landOnHand"])
        perch_end = land_end + float(self.duration["perchHand"])
        evaluation = hour if route == "HOUR_TO_MINUTE" else minute
        tiger_minute = evaluation.tiger_approach_minute
        if tiger_minute is None:
            raise AssertionError("Eligible hand route has no tiger approach")

        phases: list[Phase] = [
            Phase("HIDDEN", 0.0, hidden_end),
            Phase("SPAWN_PINE", hidden_end, spawn_end),
            Phase("FLY_PINE_TO_HAND", spawn_end, fly_end, evaluation.hand),
            Phase("LAND_ON_HAND", fly_end, land_end, evaluation.hand),
            Phase("PERCH_HAND", land_end, perch_end, evaluation.hand),
        ]
        if route == "MINUTE_DIRECT":
            phases.append(Phase("RIDE_MINUTE", perch_end, tiger_minute, "minute"))
        else:
            meet = hour.meeting_minute
            if meet is None:
                raise AssertionError("Eligible hour route has no hand meeting")
            wait_start = meet - float(self.duration["waitHandMeet"])
            hop_end = meet + float(self.duration["hopHandToHand"])
            phases.extend(
                [
                    Phase("RIDE_HOUR", perch_end, wait_start, "hour"),
                    Phase("WAIT_HAND_MEET", wait_start, meet, "hour"),
                    Phase("HOP_HAND_TO_HAND", meet, hop_end, "minute"),
                    Phase("RIDE_MINUTE", hop_end, tiger_minute, "minute"),
                ]
            )
        phases.extend(
            [
                Phase(
                    "LAND_ON_TIGER",
                    tiger_minute,
                    tiger_minute + float(self.duration["landOnTiger"]),
                ),
                Phase(
                    "PERCH_TIGER",
                    tiger_minute + float(self.duration["landOnTiger"]),
                    exit_start,
                ),
                Phase("EXIT_RIGHT", exit_start, self.cycle_minutes),
            ]
        )
        return tuple(phases)

    def _action_window(self, phases: tuple[Phase, ...]) -> Phase | None:
        candidates = [
            phase
            for phase in phases
            if phase.state in {"RIDE_HOUR", "RIDE_MINUTE", "WALK_FROM_PLUM"}
            and phase.duration >= float(self.duration["longRideThreshold"])
        ]
        return max(candidates, key=lambda phase: phase.duration, default=None)

    @staticmethod
    def _action_start(phase: Phase, fraction: float, duration: float) -> float:
        center = phase.start + phase.duration * fraction
        if phase.state == "WALK_FROM_PLUM":
            center = math.floor(center) + 0.56
        start = center - duration / 2.0
        return min(max(start, phase.start + 0.15), phase.end - duration - 0.15)

    def _build_micro_actions(
        self, cycle_index: int, character: str, phases: tuple[Phase, ...]
    ) -> tuple[tuple[MicroAction, ...], bool, str]:
        result: list[MicroAction] = []
        window = self._action_window(phases)
        initial_facing = "RIGHT"
        if window is not None:
            turn_needed = self._stable_pick(cycle_index, salt=43, modulo=100) < int(
                self.motion["turnNeedPercent"][character]
            )

            duration = float(self.motion["microActionDurationMinutes"][character])
            if character == "LARGE":
                kinds = [("HEAD_TILT", 0.35)]
                if turn_needed:
                    kinds.append(("TURN", 0.72))
            else:
                kinds = [
                    ("HEAD_SCAN", 0.25),
                    ("LOOK_PLUM", 0.50),
                    (("TURN" if turn_needed else "CHECK_TARGET"), 0.75),
                ]
            for kind, fraction in kinds:
                start = self._action_start(window, fraction, duration)
                result.append(
                    MicroAction(kind, start, start + duration, window.state)
                )

        if character == "SMALL":
            # The small magpie lands in its direction of travel, then performs
            # one visible hop-turn before settling toward the tiger's ear.
            perch = next(phase for phase in phases if phase.state == "PERCH_TIGER")
            duration = float(self.motion["smallTigerTurnDurationMinutes"])
            start = perch.start + 0.08
            result.append(
                MicroAction(
                    "TURN_TO_TIGER", start, start + duration, perch.state
                )
            )

        # Odd cycle indices are the strict small-magpie sequence. Using its own
        # ordinal (rather than a random percentage) guarantees exactly two
        # ear-peck cycles in every consecutive group of three small cycles.
        small_ordinal = cycle_index // 2
        ear_peck = character == "SMALL" and small_ordinal % 3 != 0
        if ear_peck:
            perch = next(phase for phase in phases if phase.state == "PERCH_TIGER")
            duration = float(
                self.motion["microActionDurationMinutes"]["PECK_TIGER_EAR"]
            )
            start = min(
                perch.start + max(0.45, perch.duration * 0.34),
                perch.end - duration - 0.18,
            )
            result.append(
                MicroAction("PECK_TIGER_EAR", start, start + duration, perch.state)
            )

        return tuple(sorted(result, key=lambda action: action.start)), ear_peck, initial_facing

    def _reaction_candidates(self, phases: tuple[Phase, ...]) -> list[tuple[float, str]]:
        result: list[tuple[float, str]] = []
        for phase in phases:
            if phase.state == "FLY_PINE_TO_HAND":
                result.append((phase.start + phase.duration * 0.55, phase.state))
            elif phase.state == "LAND_ON_HAND":
                result.append((phase.start + phase.duration * 0.35, phase.state))
            elif phase.state in {"RIDE_HOUR", "RIDE_MINUTE"} and phase.duration >= 1:
                result.append((phase.start + phase.duration * 0.37, phase.state))
            elif phase.state == "HOP_HAND_TO_HAND":
                result.append((phase.start + phase.duration * 0.35, phase.state))
            elif phase.state == "WALK_FROM_PLUM":
                for fraction in (0.25, 0.55, 0.8):
                    result.append((phase.start + phase.duration * fraction, phase.state))
            elif phase.state == "LAND_ON_TIGER":
                result.append((phase.start + phase.duration * 0.25, phase.state))
        return result

    def plan_cycle(self, cycle_index: int) -> CyclePlan:
        character = self.character_for_cycle(cycle_index)
        route, hand, hour, minute, selection_pick, accepted = self._choose_route(
            cycle_index, character
        )
        phases = self._build_phases(route, hour, minute)
        micro_actions, ear_peck, initial_facing = self._build_micro_actions(
            cycle_index, character, phases
        )
        if ear_peck:
            peck = next(
                action for action in micro_actions if action.kind == "PECK_TIGER_EAR"
            )
            reaction_minute = peck.start + peck.duration * 0.22
            reaction_state = "PERCH_TIGER"
            reaction_source = "EAR_PECK"
        else:
            candidates = self._reaction_candidates(phases)
            candidate_index = self._stable_pick(
                cycle_index, salt=29, modulo=len(candidates)
            )
            reaction_minute, reaction_state = candidates[candidate_index]
            reaction_source = "MOTION"
        return CyclePlan(
            cycle_index=cycle_index,
            cycle_start=self.cycle_start_for_index(cycle_index),
            character=character,
            route=route,
            selected_hand=hand,
            phases=phases,
            micro_actions=micro_actions,
            initial_facing=initial_facing,
            ear_peck=ear_peck,
            reaction_minute=reaction_minute,
            reaction_state=reaction_state,
            reaction_source=reaction_source,
            hour_evaluation=hour,
            minute_evaluation=minute,
            selection_pick=selection_pick,
            opportunity_accepted=accepted,
        )

    @staticmethod
    def _phase_at(plan: CyclePlan, local_minute: float) -> tuple[int, Phase]:
        for index, phase in enumerate(plan.phases):
            if phase.start <= local_minute < phase.end:
                return index, phase
        return len(plan.phases) - 1, plan.phases[-1]

    @staticmethod
    def _puppet_progress(progress: float) -> float:
        progress = min(1.0, max(0.0, progress))
        if progress < 0.58:
            return progress / 0.58
        if progress < 0.76:
            return 1.0
        if progress < 0.9:
            return 1.0 - 0.045 * ((progress - 0.76) / 0.14)
        return 0.955 + 0.045 * ((progress - 0.9) / 0.1)

    @staticmethod
    def _quadratic_arc(
        start: tuple[float, float],
        end: tuple[float, float],
        progress: float,
        arc_height: float,
    ) -> tuple[float, float]:
        midpoint = (
            (start[0] + end[0]) / 2.0,
            (start[1] + end[1]) / 2.0 - arc_height,
        )
        inverse = 1.0 - progress
        return (
            inverse * inverse * start[0]
            + 2.0 * inverse * progress * midpoint[0]
            + progress * progress * end[0],
            inverse * inverse * start[1]
            + 2.0 * inverse * progress * midpoint[1]
            + progress * progress * end[1],
        )

    @staticmethod
    def _polyline_point(points: list[list[float]], progress: float) -> tuple[float, float]:
        progress = min(1.0, max(0.0, progress))
        if len(points) == 1:
            return float(points[0][0]), float(points[0][1])
        scaled = progress * (len(points) - 1)
        index = min(len(points) - 2, int(math.floor(scaled)))
        local = scaled - index
        ax, ay = points[index]
        bx, by = points[index + 1]
        return ax + (bx - ax) * local, ay + (by - ay) * local

    def _position_for_phase(
        self,
        plan: CyclePlan,
        phase: Phase,
        timestamp: datetime,
        progress: float,
    ) -> tuple[float, float] | None:
        character = plan.character
        if phase.state == "HIDDEN":
            return None
        if phase.state == "SPAWN_PINE":
            x, y = self.geometry["pineSpawn"][character]
            eased = self._puppet_progress(progress)
            lead = 14.0 if character == "LARGE" else 9.0
            return x - lead * (1.0 - eased), y + 5.0 * (1.0 - eased)
        if phase.state == "FLY_PINE_TO_HAND":
            end_time = plan.cycle_start + timedelta(minutes=phase.end)
            end = self.hand_anchor(phase.hand or "minute", end_time, character)
            return self._quadratic_arc(
                tuple(self.geometry["pineSpawn"][character]),
                end,
                self._puppet_progress(progress),
                float(self.motion["flightArcHeight"][character]),
            )
        if phase.state in {
            "LAND_ON_HAND",
            "PERCH_HAND",
            "RIDE_MINUTE",
            "RIDE_HOUR",
            "WAIT_HAND_MEET",
        }:
            hand = phase.hand or (plan.selected_hand or "minute")
            return self.hand_anchor(hand, timestamp, character)
        if phase.state == "HOP_HAND_TO_HAND":
            start_time = plan.cycle_start + timedelta(minutes=phase.start)
            end_time = plan.cycle_start + timedelta(minutes=phase.end)
            start = self.hand_anchor("hour", start_time, character)
            end = self.hand_anchor("minute", end_time, character)
            return self._quadratic_arc(
                start,
                end,
                self._puppet_progress(progress),
                float(self.motion["hopArcHeight"][character]),
            )
        if phase.state == "SPAWN_PLUM":
            x, y = self.geometry["plumSpawn"][character]
            eased = self._puppet_progress(progress)
            lead = 12.0 if character == "LARGE" else 8.0
            return x - lead * (1.0 - eased), y + 4.0 * (1.0 - eased)
        if phase.state == "WALK_FROM_PLUM":
            step_count = max(1, int(math.ceil(phase.duration)))
            scaled = progress * step_count
            whole_step = min(step_count - 1, int(math.floor(scaled)))
            step_fraction = scaled - whole_step
            motion_fraction = float(self.motion["walkStepMotionFraction"][character])
            move_progress = min(1.0, step_fraction / motion_fraction)
            snapped_progress = (
                whole_step + self._puppet_progress(move_progress)
            ) / step_count
            return self._polyline_point(
                self.geometry["plumWalkWaypoints"][character], snapped_progress
            )
        if phase.state == "LAND_ON_TIGER":
            start_time = plan.cycle_start + timedelta(minutes=phase.start)
            if plan.route == "PLUM_WALK":
                start = tuple(self.geometry["plumWalkWaypoints"][character][-1])
            else:
                start = self.hand_anchor("minute", start_time, character)
            return self._quadratic_arc(
                start,
                tuple(self.geometry["tigerPerch"][character]),
                self._puppet_progress(progress),
                float(self.motion["hopArcHeight"][character]),
            )
        if phase.state == "PERCH_TIGER":
            return tuple(self.geometry["tigerPerch"][character])
        if phase.state == "EXIT_RIGHT":
            if character == "SMALL":
                # Keep both wing beats on screen, then accelerate through the
                # boundary at the end of the second beat.
                exit_progress = progress**2.35
            else:
                # The large bird first lowers its body, then makes one long,
                # low jump with folded wings.
                launch = max(0.0, (progress - 0.14) / 0.86)
                exit_progress = launch * launch * (3.0 - 2.0 * launch)
            return self._quadratic_arc(
                tuple(self.geometry["tigerPerch"][character]),
                tuple(self.geometry["screenExitRight"][character]),
                exit_progress,
                float(self.motion["exitArcHeight"][character]),
            )
        raise ValueError(f"Unhandled state: {phase.state}")

    @staticmethod
    def _render_slot(state: str) -> str:
        if state == "HIDDEN":
            return "NONE"
        if state in {"SPAWN_PLUM", "WALK_FROM_PLUM"}:
            return "GROUND"
        if state in {"LAND_ON_TIGER", "PERCH_TIGER", "EXIT_RIGHT"}:
            return "TIGER"
        return "HAND"

    @staticmethod
    def _active_micro_action(
        actions: tuple[MicroAction, ...], local: float
    ) -> tuple[MicroAction | None, float]:
        for action in actions:
            if action.start <= local < action.end:
                return action, (local - action.start) / action.duration
        return None, 0.0

    @staticmethod
    def _facing_at(plan: CyclePlan, local: float) -> str:
        facing = plan.initial_facing
        for action in plan.micro_actions:
            if action.kind != "TURN_TO_TIGER":
                continue
            if local >= action.start + action.duration * 0.52:
                facing = "LEFT"
        return facing

    def _movement_facing(
        self,
        plan: CyclePlan,
        phase: Phase,
        timestamp: datetime,
        phase_progress: float,
        fallback: str,
    ) -> str:
        """Face the horizontal direction produced by the actual motion path."""
        if phase.state in {"HIDDEN", "PERCH_TIGER"}:
            return fallback
        sample = float(self.motion["movementFacingSampleMinutes"])
        center = phase.start + phase.duration * phase_progress
        before = max(phase.start, center - sample)
        after = min(phase.end, center + sample)
        if after - before < 1e-6:
            return fallback

        def position(local: float) -> tuple[float, float] | None:
            progress = (local - phase.start) / phase.duration
            sample_time = plan.cycle_start + timedelta(minutes=local)
            return self._position_for_phase(plan, phase, sample_time, progress)

        start = position(before)
        end = position(after)
        if start is None or end is None:
            return fallback
        delta_x = end[0] - start[0]
        if delta_x > 0.05:
            return "RIGHT"
        if delta_x < -0.05:
            return "LEFT"
        return fallback

    def snapshot(self, timestamp: datetime, aod: bool = False) -> SceneSnapshot:
        cycle_index = self.cycle_index_at(timestamp)
        plan = self.plan_cycle(cycle_index)
        local = self.cycle_local_minute(timestamp, cycle_index)
        phase_index, phase = self._phase_at(plan, local)
        phase_progress = (
            0.0 if phase.duration <= 0 else (local - phase.start) / phase.duration
        )
        phase_progress = min(1.0, max(0.0, phase_progress))
        next_state = (
            plan.phases[phase_index + 1].state
            if phase_index + 1 < len(plan.phases)
            else "HIDDEN"
        )
        reaction_duration = float(self.motion["reactionDurationMinutes"])
        reaction_progress = (local - plan.reaction_minute) / reaction_duration
        tiger_reacting = 0.0 <= reaction_progress < 1.0 and not aod
        action, micro_progress = self._active_micro_action(plan.micro_actions, local)
        position = self._position_for_phase(plan, phase, timestamp, phase_progress)
        facing = self._movement_facing(
            plan,
            phase,
            timestamp,
            phase_progress,
            self._facing_at(plan, local),
        )
        if phase.state == "EXIT_RIGHT":
            facing = "RIGHT"

        wing_beat = 0
        wing_progress = 0.0
        if plan.character == "SMALL" and phase.state == "EXIT_RIGHT":
            total = int(self.motion["smallExitWingFlaps"])
            scaled = min(total - 1e-9, phase_progress * total)
            wing_beat = min(total, int(scaled) + 1)
            wing_progress = scaled - math.floor(scaled)

        visible = phase.state != "HIDDEN" and not aod
        return SceneSnapshot(
            timestamp=timestamp,
            cycle_index=cycle_index,
            cycle_start=plan.cycle_start,
            cycle_progress=min(1.0, max(0.0, local / self.cycle_minutes)),
            character=plan.character,
            route=plan.route,
            selected_hand=plan.selected_hand,
            state=phase.state,
            next_state=next_state,
            state_progress=phase_progress,
            render_slot=(self._render_slot(phase.state) if visible else "NONE"),
            visible=visible,
            foot_position=(
                None
                if position is None or not visible
                else (round(position[0], 3), round(position[1], 3))
            ),
            facing=facing,
            micro_action=(None if action is None or aod else action.kind),
            micro_progress=(0.0 if action is None or aod else round(micro_progress, 4)),
            tiger_reacting=tiger_reacting,
            tiger_reaction_progress=(
                round(min(1.0, max(0.0, reaction_progress)), 4)
                if tiger_reacting
                else 0.0
            ),
            reaction_state=plan.reaction_state,
            reaction_source=plan.reaction_source,
            reaction_minute=round(plan.reaction_minute, 3),
            ear_peck=plan.ear_peck,
            wing_flap_beat=wing_beat,
            wing_flap_progress=round(wing_progress, 4),
            hour_score=plan.hour_evaluation.score,
            minute_score=plan.minute_evaluation.score,
            hour_eligible=plan.hour_evaluation.eligible,
            minute_eligible=plan.minute_evaluation.eligible,
            opportunity_accepted=plan.opportunity_accepted,
        )

    def plans_intersecting(self, start: datetime, end: datetime) -> list[CyclePlan]:
        first = self.cycle_index_at(start)
        last = self.cycle_index_at(end - timedelta(microseconds=1))
        return [self.plan_cycle(index) for index in range(first, last + 1)]

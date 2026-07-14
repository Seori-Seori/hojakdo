from __future__ import annotations

import unittest
from collections import Counter
from datetime import datetime, timedelta

from .scene_calculator import HojakdoSceneCalculator


class HojakdoSceneCalculatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calculator = HojakdoSceneCalculator()
        cls.day_start = datetime(2026, 7, 14)
        cls.day_end = cls.day_start + timedelta(days=1)

    def test_same_timestamp_is_deterministic(self) -> None:
        timestamp = datetime(2026, 7, 14, 10, 8, 30)
        self.assertEqual(
            self.calculator.snapshot(timestamp),
            self.calculator.snapshot(timestamp),
        )

    def test_characters_alternate_and_only_one_is_visible(self) -> None:
        first = self.calculator.cycle_index_at(self.day_start)
        plans = [self.calculator.plan_cycle(first + offset) for offset in range(100)]
        for previous, current in zip(plans, plans[1:]):
            self.assertNotEqual(previous.character, current.character)
        timestamp = self.day_start
        while timestamp < self.day_end:
            snapshot = self.calculator.snapshot(timestamp)
            self.assertIn(snapshot.character, {"LARGE", "SMALL"})
            if snapshot.state == "HIDDEN":
                self.assertFalse(snapshot.visible)
                self.assertEqual("NONE", snapshot.render_slot)
                self.assertIsNone(snapshot.foot_position)
            else:
                self.assertTrue(snapshot.visible)
                self.assertIn(snapshot.render_slot, {"GROUND", "HAND", "TIGER"})
                self.assertIsNotNone(snapshot.foot_position)
            timestamp += timedelta(minutes=1)

    def test_every_cycle_is_complete_with_generic_exit(self) -> None:
        for plan in self.calculator.plans_intersecting(self.day_start, self.day_end):
            self.assertEqual(0.0, plan.phases[0].start)
            self.assertEqual("HIDDEN", plan.phases[0].state)
            self.assertEqual(2.0, plan.phases[0].end)
            self.assertEqual("EXIT_RIGHT", plan.phases[-1].state)
            self.assertAlmostEqual(self.calculator.cycle_minutes, plan.phases[-1].end)
            self.assertNotIn("FLY_OUT_RIGHT", {phase.state for phase in plan.phases})
            for previous, current in zip(plan.phases, plan.phases[1:]):
                self.assertAlmostEqual(previous.end, current.start)
                self.assertGreater(previous.duration, 0.0)

    def test_hand_landings_average_six_with_no_daily_quota(self) -> None:
        start = datetime(2026, 1, 1)
        daily_counts: list[int] = []
        for offset in range(365):
            day = start + timedelta(days=offset)
            plans = self.calculator.plans_intersecting(
                day - timedelta(minutes=self.calculator.cycle_minutes),
                day + timedelta(days=1),
            )
            landing_count = 0
            for plan in plans:
                if plan.route == "PLUM_WALK":
                    continue
                landing_phase = next(
                    phase for phase in plan.phases if phase.state == "LAND_ON_HAND"
                )
                landing_time = plan.cycle_start + timedelta(minutes=landing_phase.end)
                landing_count += day <= landing_time < day + timedelta(days=1)
            daily_counts.append(landing_count)
        average = sum(daily_counts) / len(daily_counts)
        self.assertGreaterEqual(average, 5.9)
        self.assertLessEqual(average, 6.1)
        self.assertGreaterEqual(min(daily_counts), 4)
        self.assertLessEqual(max(daily_counts), 8)
        self.assertGreater(len(set(daily_counts)), 1)

    def test_both_characters_can_use_both_hands(self) -> None:
        start = datetime(2026, 1, 1)
        plans = self.calculator.plans_intersecting(start, start + timedelta(days=365))
        combinations = Counter((plan.character, plan.route) for plan in plans)
        for character in ("LARGE", "SMALL"):
            self.assertGreater(combinations[(character, "MINUTE_DIRECT")], 0)
            self.assertGreater(combinations[(character, "HOUR_TO_MINUTE")], 0)
            self.assertGreater(combinations[(character, "PLUM_WALK")], 0)

    def test_small_magpie_pecks_in_exactly_two_of_three_small_cycles(self) -> None:
        first = self.calculator.cycle_index_at(self.day_start)
        first_small = first if first % 2 else first + 1
        small_plans = [
            self.calculator.plan_cycle(first_small + offset * 2) for offset in range(12)
        ]
        for index in range(0, len(small_plans), 3):
            group = small_plans[index : index + 3]
            self.assertEqual(2, sum(plan.ear_peck for plan in group))
        for plan in small_plans:
            pecks = [
                action for action in plan.micro_actions if action.kind == "PECK_TIGER_EAR"
            ]
            self.assertEqual(int(plan.ear_peck), len(pecks))
            if plan.ear_peck:
                self.assertEqual("EAR_PECK", plan.reaction_source)

    def test_every_cycle_reserves_exactly_one_valid_tiger_reaction(self) -> None:
        first = self.calculator.cycle_index_at(self.day_start)
        for offset in range(200):
            plan = self.calculator.plan_cycle(first + offset)
            self.assertGreaterEqual(plan.reaction_minute, 0.0)
            self.assertLess(plan.reaction_minute, self.calculator.cycle_minutes)
            self.assertNotEqual("EXIT_RIGHT", plan.reaction_state)
            if plan.ear_peck:
                self.assertEqual("EAR_PECK", plan.reaction_source)
                self.assertEqual("PERCH_TIGER", plan.reaction_state)
            else:
                self.assertEqual("MOTION", plan.reaction_source)

    def test_ride_micro_actions_are_bounded(self) -> None:
        first = self.calculator.cycle_index_at(self.day_start)
        plans = [self.calculator.plan_cycle(first + offset) for offset in range(120)]
        for plan in plans:
            ride_actions = [
                action
                for action in plan.micro_actions
                if action.kind not in {"PECK_TIGER_EAR", "TURN_TO_TIGER"}
            ]
            if plan.character == "SMALL":
                self.assertLessEqual(len(ride_actions), 3)
            else:
                self.assertLessEqual(len(ride_actions), 2)
            self.assertEqual("RIGHT", plan.initial_facing)

    def test_motion_facing_matches_horizontal_velocity(self) -> None:
        first = self.calculator.cycle_index_at(self.day_start)
        sample = timedelta(
            minutes=float(
                self.calculator.motion["movementFacingSampleMinutes"]
            )
        )
        compared = 0
        for offset in range(12):
            plan = self.calculator.plan_cycle(first + offset)
            timestamp = plan.cycle_start + timedelta(seconds=10)
            while timestamp < plan.cycle_end - timedelta(seconds=10):
                center = self.calculator.snapshot(timestamp)
                before = self.calculator.snapshot(timestamp - sample)
                after = self.calculator.snapshot(timestamp + sample)
                if (
                    center.visible
                    and center.state not in {"HIDDEN", "PERCH_TIGER"}
                    and before.cycle_index == center.cycle_index == after.cycle_index
                    and before.state == center.state == after.state
                    and before.foot_position is not None
                    and after.foot_position is not None
                ):
                    delta_x = after.foot_position[0] - before.foot_position[0]
                    if abs(delta_x) > 0.05:
                        expected = "RIGHT" if delta_x > 0 else "LEFT"
                        self.assertEqual(expected, center.facing)
                        compared += 1
                timestamp += timedelta(seconds=10)
        self.assertGreater(compared, 500)

    def test_lookback_action_does_not_reverse_travel_facing(self) -> None:
        first = self.calculator.cycle_index_at(self.day_start)
        plan = next(
            plan
            for plan in (
                self.calculator.plan_cycle(first + offset) for offset in range(120)
            )
            if any(action.kind == "TURN" for action in plan.micro_actions)
        )
        turn = next(action for action in plan.micro_actions if action.kind == "TURN")
        timestamp = plan.cycle_start + timedelta(
            minutes=turn.start + turn.duration * 0.5
        )
        sample = timedelta(
            minutes=float(
                self.calculator.motion["movementFacingSampleMinutes"]
            )
        )
        before = self.calculator.snapshot(timestamp - sample)
        center = self.calculator.snapshot(timestamp)
        after = self.calculator.snapshot(timestamp + sample)
        assert before.foot_position is not None
        assert after.foot_position is not None
        delta_x = after.foot_position[0] - before.foot_position[0]
        self.assertGreater(abs(delta_x), 0.05)
        self.assertEqual("TURN", center.micro_action)
        self.assertEqual("RIGHT" if delta_x > 0 else "LEFT", center.facing)

    def test_small_turns_toward_tiger_after_landing(self) -> None:
        first = self.calculator.cycle_index_at(self.day_start)
        plan = next(
            self.calculator.plan_cycle(first + offset)
            for offset in range(4)
            if self.calculator.character_for_cycle(first + offset) == "SMALL"
        )
        turn = next(
            action for action in plan.micro_actions if action.kind == "TURN_TO_TIGER"
        )
        before = self.calculator.snapshot(
            plan.cycle_start
            + timedelta(minutes=turn.start + turn.duration * 0.25)
        )
        after = self.calculator.snapshot(
            plan.cycle_start
            + timedelta(minutes=turn.start + turn.duration * 0.75)
        )
        self.assertEqual("PERCH_TIGER", before.state)
        self.assertEqual("TURN_TO_TIGER", before.micro_action)
        self.assertEqual("TURN_TO_TIGER", after.micro_action)
        self.assertEqual("RIGHT", before.facing)
        self.assertEqual("LEFT", after.facing)
        self.assertEqual(before.foot_position, after.foot_position)

    def test_small_exit_has_two_flaps_and_large_exit_has_none(self) -> None:
        first = self.calculator.cycle_index_at(self.day_start)
        plans = [self.calculator.plan_cycle(first + offset) for offset in range(4)]
        for plan in plans:
            exit_phase = plan.phases[-1]
            samples = []
            for fraction in (0.1, 0.4, 0.6, 0.9):
                samples.append(
                    self.calculator.snapshot(
                        plan.cycle_start
                        + timedelta(
                            minutes=exit_phase.start + exit_phase.duration * fraction
                        )
                    ).wing_flap_beat
                )
            if plan.character == "SMALL":
                self.assertEqual([1, 1, 2, 2], samples)
            else:
                self.assertEqual([0, 0, 0, 0], samples)

    def test_aod_hides_bird_and_reaction(self) -> None:
        timestamp = self.day_start + timedelta(hours=12)
        aod = self.calculator.snapshot(timestamp, aod=True)
        self.assertFalse(aod.visible)
        self.assertEqual("NONE", aod.render_slot)
        self.assertIsNone(aod.foot_position)
        self.assertIsNone(aod.micro_action)
        self.assertFalse(aod.tiger_reacting)

    def test_route_and_hand_are_locked_for_cycle(self) -> None:
        for plan in self.calculator.plans_intersecting(self.day_start, self.day_end):
            snapshots = [
                self.calculator.snapshot(plan.cycle_start + timedelta(minutes=offset))
                for offset in range(int(self.calculator.cycle_minutes))
            ]
            self.assertEqual({plan.character}, {item.character for item in snapshots})
            self.assertEqual({plan.route}, {item.route for item in snapshots})
            self.assertEqual(
                {plan.selected_hand}, {item.selected_hand for item in snapshots}
            )

    def test_midnight_is_continuous(self) -> None:
        before = self.calculator.snapshot(datetime(2026, 7, 14, 23, 59, 59))
        after = self.calculator.snapshot(datetime(2026, 7, 15, 0, 0, 0))
        if before.cycle_index == after.cycle_index:
            self.assertEqual(before.character, after.character)
            self.assertEqual(before.route, after.route)
            self.assertEqual(before.selected_hand, after.selected_hand)
            self.assertGreaterEqual(after.cycle_progress, before.cycle_progress)


if __name__ == "__main__":
    unittest.main()

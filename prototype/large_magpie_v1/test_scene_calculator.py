from __future__ import annotations

import unittest
from collections import Counter
from datetime import datetime, timedelta

from .scene_calculator import LargeMagpieSceneCalculator


class LargeMagpieSceneCalculatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calculator = LargeMagpieSceneCalculator()
        cls.day_start = datetime(2026, 7, 14)
        cls.day_end = cls.day_start + timedelta(days=1)

    def test_same_timestamp_is_deterministic(self) -> None:
        timestamp = datetime(2026, 7, 14, 10, 8, 30)
        self.assertEqual(
            self.calculator.snapshot(timestamp),
            self.calculator.snapshot(timestamp),
        )

    def test_every_cycle_has_contiguous_complete_phases(self) -> None:
        for plan in self.calculator.plans_intersecting(self.day_start, self.day_end):
            self.assertEqual(0.0, plan.phases[0].start)
            self.assertAlmostEqual(self.calculator.cycle_minutes, plan.phases[-1].end)
            for previous, current in zip(plan.phases, plan.phases[1:]):
                self.assertAlmostEqual(previous.end, current.start)
                self.assertGreater(previous.duration, 0.0)
            self.assertGreater(plan.phases[-1].duration, 0.0)
            self.assertEqual("HIDDEN", plan.phases[0].state)
            self.assertEqual("FLY_OUT_RIGHT", plan.phases[-1].state)

    def test_every_cycle_has_exactly_one_reaction_reservation(self) -> None:
        for plan in self.calculator.plans_intersecting(self.day_start, self.day_end):
            self.assertGreaterEqual(plan.reaction_minute, 0.0)
            self.assertLess(plan.reaction_minute, self.calculator.cycle_minutes)
            self.assertNotEqual("FLY_OUT_RIGHT", plan.reaction_state)

    def test_route_and_hand_are_locked_for_whole_cycle(self) -> None:
        for plan in self.calculator.plans_intersecting(self.day_start, self.day_end):
            samples = [
                plan.cycle_start + timedelta(minutes=offset)
                for offset in range(0, int(self.calculator.cycle_minutes))
            ]
            snapshots = [self.calculator.snapshot(sample) for sample in samples]
            self.assertEqual({plan.route}, {snapshot.route for snapshot in snapshots})
            self.assertEqual(
                {plan.selected_hand},
                {snapshot.selected_hand for snapshot in snapshots},
            )

    def test_visible_snapshot_uses_exactly_one_render_slot(self) -> None:
        timestamp = self.day_start
        while timestamp < self.day_end:
            snapshot = self.calculator.snapshot(timestamp)
            if snapshot.state == "HIDDEN":
                self.assertEqual("NONE", snapshot.render_slot)
                self.assertIsNone(snapshot.foot_position)
            else:
                self.assertIn(snapshot.render_slot, {"GROUND", "HAND", "TIGER"})
                self.assertIsNotNone(snapshot.foot_position)
            timestamp += timedelta(minutes=1)

    def test_all_three_routes_appear_in_tuning_window(self) -> None:
        routes: Counter[str] = Counter()
        start = self.day_start - timedelta(days=3)
        end = self.day_end + timedelta(days=3)
        for plan in self.calculator.plans_intersecting(start, end):
            routes[plan.route] += 1
        self.assertGreater(routes["MINUTE_DIRECT"], 0)
        self.assertGreater(routes["HOUR_TO_MINUTE"], 0)
        self.assertGreater(routes["PLUM_WALK"], 0)

    def test_midnight_is_continuous(self) -> None:
        before = self.calculator.snapshot(datetime(2026, 7, 14, 23, 59, 59))
        after = self.calculator.snapshot(datetime(2026, 7, 15, 0, 0, 0))
        if before.cycle_index == after.cycle_index:
            self.assertEqual(before.route, after.route)
            self.assertEqual(before.selected_hand, after.selected_hand)
            self.assertGreaterEqual(after.cycle_progress, before.cycle_progress)


if __name__ == "__main__":
    unittest.main()

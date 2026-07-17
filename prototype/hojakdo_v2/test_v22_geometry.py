from __future__ import annotations

import unittest
from datetime import datetime, timedelta

import numpy as np
from PIL import Image, ImageChops

from .render_prototype import FACE_SIZE, PrototypeRenderer
from .scene_calculator import HojakdoSceneCalculator


class HojakdoV22GeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calculator = HojakdoSceneCalculator()
        cls.renderer = PrototypeRenderer(cls.calculator)
        first = cls.calculator.cycle_index_at(datetime(2026, 7, 15))
        cls.small_transfer = next(
            cls.calculator.plan_cycle(first + offset)
            for offset in range(500)
            if cls.calculator.character_for_cycle(first + offset) == "SMALL"
            and cls.calculator.plan_cycle(first + offset).route == "HOUR_TO_MINUTE"
        )

    def _hand_overlap(self, state: str) -> int:
        phase = next(item for item in self.small_transfer.phases if item.state == state)
        timestamp = self.small_transfer.cycle_start + timedelta(
            minutes=(phase.start + phase.end) / 2.0
        )
        snapshot = self.calculator.snapshot(timestamp)
        assert snapshot.foot_position is not None
        hand = "hour" if state == "RIDE_HOUR" else "minute"
        branch = self.renderer.hour_branch if hand == "hour" else self.renderer.minute_branch
        branch = self.renderer._rotate_layer(
            branch,
            self.calculator.hand_group_angle(hand, timestamp),
            self.renderer.geometry["clockPivot"],
        )
        bird, anchor, y_offset = self.renderer._posed_bird(snapshot)
        foot = (snapshot.foot_position[0], snapshot.foot_position[1] + y_offset)
        bird_layer = Image.new("L", (FACE_SIZE, FACE_SIZE), 0)
        bird_layer.paste(
            bird.getchannel("A"),
            (
                int(round(foot[0] - anchor[0])),
                int(round(foot[1] - anchor[1])),
            ),
        )
        bird_alpha = np.asarray(bird_layer) > 64
        branch_alpha = np.asarray(branch.getchannel("A")) > 64
        return int(np.count_nonzero(bird_alpha & branch_alpha))

    def test_small_magpie_contacts_both_individual_hand_ends(self) -> None:
        geometry = self.calculator.geometry
        self.assertEqual([302, 148], geometry["hourHandAnchorAtZero"]["SMALL"])
        self.assertEqual([171, 122], geometry["minuteHandAnchorAtZero"]["SMALL"])
        self.assertGreaterEqual(self._hand_overlap("RIDE_HOUR"), 5)
        self.assertGreaterEqual(self._hand_overlap("RIDE_MINUTE"), 5)

    def test_visual_scales_match_the_approved_combination(self) -> None:
        render = self.calculator.config["render"]
        self.assertAlmostEqual(0.85728, render["largeBirdScale"])
        self.assertAlmostEqual(0.94, render["tigerScale"])

    def test_tiger_head_and_pupils_are_scaled_as_one_group(self) -> None:
        pairs = (
            (
                "assets/layers/source/characters/tiger_head_v21.png",
                "assets/layers/source/characters/tiger_head_v22.png",
            ),
            (
                "assets/layers/mvp/tiger_pupils.png",
                "assets/layers/source/characters/tiger_pupils_v22.png",
            ),
        )
        for original_path, scaled_path in pairs:
            with Image.open(self.renderer._source_path(original_path)) as source:
                original_bounds = source.convert("RGBA").getchannel("A").getbbox()
            with Image.open(self.renderer._source_path(scaled_path)) as source:
                scaled_bounds = source.convert("RGBA").getchannel("A").getbbox()
            assert original_bounds is not None and scaled_bounds is not None
            original_size = (
                original_bounds[2] - original_bounds[0],
                original_bounds[3] - original_bounds[1],
            )
            scaled_size = (
                scaled_bounds[2] - scaled_bounds[0],
                scaled_bounds[3] - scaled_bounds[1],
            )
            for original, scaled in zip(original_size, scaled_size):
                self.assertAlmostEqual(0.94, scaled / original, delta=0.02)

    def test_tiger_scale_does_not_move_battery_or_percentage(self) -> None:
        original_path = self.renderer._source_path(
            "assets/layers/mvp/clean_background.png"
        )
        scaled_path = self.renderer._source_path(
            "assets/layers/mvp/clean_background_v22.png"
        )
        with Image.open(original_path) as source:
            original = source.convert("RGB")
        with Image.open(scaled_path) as source:
            scaled = source.convert("RGB")
        sx = original.width / 450.0
        sy = original.height / 450.0
        box = (
            int(round(194 * sx)),
            int(round(420 * sy)),
            int(round(276 * sx)),
            int(round(446 * sy)),
        )
        self.assertIsNone(
            ImageChops.difference(original.crop(box), scaled.crop(box)).getbbox()
        )


if __name__ == "__main__":
    unittest.main()

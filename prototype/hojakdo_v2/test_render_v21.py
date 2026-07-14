from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from PIL import Image, ImageChops

from .render_prototype import FACE_SIZE, PrototypeRenderer
from .scene_calculator import HojakdoSceneCalculator


class HojakdoV21RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calculator = HojakdoSceneCalculator()
        cls.renderer = PrototypeRenderer(cls.calculator)
        first = cls.calculator.cycle_index_at(datetime(2026, 7, 14))
        cls.small_plan = next(
            cls.calculator.plan_cycle(first + offset)
            for offset in range(4)
            if cls.calculator.character_for_cycle(first + offset) == "SMALL"
        )

    def _small_exit_snapshot(self, fraction: float):
        phase = self.small_plan.phases[-1]
        return self.calculator.snapshot(
            self.small_plan.cycle_start
            + timedelta(minutes=phase.start + phase.duration * fraction)
        )

    def test_clean_small_master_has_expected_bounds_and_no_red_ornament(self) -> None:
        path = self.renderer._source_path(
            "assets/layers/source/characters/magpie_small_base_master_v21.png"
        )
        with Image.open(path) as source:
            full = source.convert("RGBA").resize(
                (FACE_SIZE, FACE_SIZE), Image.Resampling.LANCZOS
            )
        bounds = full.getchannel("A").getbbox()
        expected = tuple(
            self.calculator.geometry["birdLogicalBoundsAtZero"]["SMALL"]
        )
        assert bounds is not None
        for actual, target in zip(bounds, expected):
            self.assertLessEqual(abs(actual - target), 2)
        red_pixels = sum(
            1
            for red, green, blue, alpha in full.get_flattened_data()
            if alpha > 128 and red > 150 and green < 85 and blue < 80
        )
        self.assertEqual(0, red_pixels)

    def test_exit_wing_connector_overlaps_bird_and_rear_wing(self) -> None:
        snapshot = self._small_exit_snapshot(0.25)
        foot = (225.0, 245.0)
        bird, anchor, y_offset = self.renderer._posed_bird(snapshot)
        posed_foot = (foot[0], foot[1] + y_offset)
        bird_layer = Image.new("RGBA", (FACE_SIZE, FACE_SIZE), (0, 0, 0, 0))
        bird_layer.alpha_composite(
            bird,
            (
                int(round(posed_foot[0] - anchor[0])),
                int(round(posed_foot[1] - anchor[1])),
            ),
        )
        rear = Image.new("RGBA", (FACE_SIZE, FACE_SIZE), (0, 0, 0, 0))
        front = Image.new("RGBA", (FACE_SIZE, FACE_SIZE), (0, 0, 0, 0))
        self.renderer._draw_small_wing(rear, posed_foot, snapshot, foreground=False)
        self.renderer._draw_small_wing(front, posed_foot, snapshot, foreground=True)
        self.assertIsNotNone(
            ImageChops.multiply(
                front.getchannel("A"), bird_layer.getchannel("A")
            ).getbbox()
        )
        self.assertIsNotNone(
            ImageChops.multiply(front.getchannel("A"), rear.getchannel("A")).getbbox()
        )

    def test_exit_wing_is_scaled_to_small_bird_body(self) -> None:
        snapshot = self._small_exit_snapshot(0.25)
        foot = (225.0, 245.0)
        layer = Image.new("RGBA", (FACE_SIZE, FACE_SIZE), (0, 0, 0, 0))
        self.renderer._draw_small_wing(layer, foot, snapshot, foreground=False)
        bounds = layer.getchannel("A").getbbox()
        assert bounds is not None
        wing_width = bounds[2] - bounds[0]
        body_height = self.renderer.birds["SMALL"][0].height
        self.assertGreater(wing_width, body_height * 0.30)
        self.assertLess(wing_width, body_height * 0.58)

    def test_repaired_tiger_head_covers_original_chin_gap(self) -> None:
        old_path = self.renderer._source_path("assets/layers/mvp/tiger_head.png")
        new_path = self.renderer._source_path(
            "assets/layers/source/characters/tiger_head_v21.png"
        )
        with Image.open(old_path) as source:
            old_alpha = source.convert("RGBA").getchannel("A")
        with Image.open(new_path) as source:
            new_alpha = source.convert("RGBA").getchannel("A")
        old_bounds = old_alpha.getbbox()
        new_bounds = new_alpha.getbbox()
        assert old_bounds is not None
        assert new_bounds is not None
        self.assertLess(new_bounds[0], old_bounds[0])
        self.assertGreater(new_bounds[3], old_bounds[3])
        old_coverage = sum(
            1 for value in old_alpha.get_flattened_data() if value > 0
        )
        new_coverage = sum(
            1 for value in new_alpha.get_flattened_data() if value > 0
        )
        self.assertGreater(new_coverage, old_coverage + 5_000)


if __name__ == "__main__":
    unittest.main()

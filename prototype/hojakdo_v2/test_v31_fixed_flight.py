from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timedelta

import numpy as np
from PIL import Image, ImageChops

from .build_v31_assets import build
from .render_prototype import FACE_SIZE, PrototypeRenderer
from .scene_calculator import HojakdoSceneCalculator


class HojakdoV31FixedFlightTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calculator = HojakdoSceneCalculator()
        cls.renderer = PrototypeRenderer(cls.calculator)
        first = cls.calculator.cycle_index_at(datetime(2026, 7, 15))
        cls.small_plan = next(
            cls.calculator.plan_cycle(first + offset)
            for offset in range(8)
            if cls.calculator.character_for_cycle(first + offset) == "SMALL"
        )
        cls.exit_phase = cls.small_plan.phases[-1]

    @staticmethod
    def _sha256(path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _snapshot(self, fraction: float):
        return self.calculator.snapshot(
            self.small_plan.cycle_start
            + timedelta(
                minutes=self.exit_phase.start + self.exit_phase.duration * fraction
            )
        )

    def test_asset_builder_is_reproducible_and_matches_approved_source(self) -> None:
        config = self.calculator.config["smallExit"]
        source = self.renderer._source_path(config["approvedSource"])
        runtime = self.renderer._source_path(config["runtimeSprite"])
        metadata_path = self.renderer._source_path(config["metadata"])
        before = self._sha256(runtime)
        metadata = build()
        after = self._sha256(runtime)
        stored = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(config["approvedSourceSha256"], self._sha256(source))
        self.assertEqual(before, after)
        self.assertEqual(metadata, stored)

    def test_runtime_sprite_has_approved_size_alpha_and_clean_hidden_rgb(self) -> None:
        config = self.calculator.config["smallExit"]
        path = self.renderer._source_path(config["runtimeSprite"])
        with Image.open(path) as source:
            sprite = source.convert("RGBA")
        self.assertEqual((138, 107), sprite.size)
        self.assertIsNotNone(sprite.getchannel("A").getbbox())
        pixels = np.asarray(sprite, dtype=np.uint8)
        hidden_rgb = np.any(pixels[:, :, :3] != 0, axis=2) & (pixels[:, :, 3] == 0)
        self.assertEqual(0, int(np.count_nonzero(hidden_rgb)))

    def test_fixed_sprite_pixels_anchor_scale_and_rotation_do_not_change(self) -> None:
        baseline_image = None
        baseline_anchor = None
        for fraction in (0.05, 0.24, 0.50, 0.85):
            snapshot = self._snapshot(fraction)
            image, anchor, y_offset = self.renderer._posed_bird(snapshot)
            if baseline_image is None:
                baseline_image = image
                baseline_anchor = anchor
            else:
                self.assertIsNone(ImageChops.difference(baseline_image, image).getbbox())
                self.assertEqual(baseline_anchor, anchor)
            self.assertEqual(0.0, y_offset)
            self.assertEqual(0, snapshot.wing_flap_beat)
            self.assertEqual(0.0, snapshot.wing_flap_progress)
        config = self.calculator.config["smallExit"]
        self.assertEqual(0, config["rotationDegrees"])
        self.assertEqual(config["scaleStart"], config["scaleEnd"])

    def test_exit_uses_approved_smoothstep_arc_and_finishes_offscreen(self) -> None:
        config = self.calculator.config["smallExit"]
        start = self.calculator._position_for_phase(
            self.small_plan, self.exit_phase, self.small_plan.cycle_start, 0.0
        )
        end = self.calculator._position_for_phase(
            self.small_plan, self.exit_phase, self.small_plan.cycle_end, 1.0
        )
        midpoint = self.calculator._position_for_phase(
            self.small_plan, self.exit_phase, self.small_plan.cycle_start, 0.5
        )
        self.assertEqual((344.0, 200.0), start)
        self.assertEqual(tuple(config["endAnchorLogical"]), end)
        self.assertAlmostEqual(48.0, config["arcHeightLogical"])
        self.assertAlmostEqual(446.0, midpoint[0])
        # The accepted quadratic path places its control point 48px above the
        # endpoint midpoint; a quadratic Bezier reaches half that displacement
        # at t=0.5, exactly as in the approved review GIF.
        self.assertAlmostEqual(142.5, midpoint[1])

        _, anchor = self.renderer.small_exit_bird
        left_at_end = end[0] - anchor[0]
        self.assertGreaterEqual(
            left_at_end,
            FACE_SIZE + float(config["offscreenPaddingLogical"]),
        )

    def test_v31_keeps_full_bloom_and_center_display_source_unchanged(self) -> None:
        self.assertEqual(4, self.renderer.battery_plum_stage_index(85))
        preserved = self.calculator.config["preservedDisplay"]
        path = self.renderer._source_path(preserved["source"])
        self.assertEqual(preserved["sourceSha256"], self._sha256(path))
        with Image.open(path) as source:
            center = source.convert("RGB").crop(tuple(preserved["centerCropSource"]))
        center_hash = hashlib.sha256(center.tobytes()).hexdigest()
        self.assertEqual(preserved["centerCropRgbSha256"], center_hash)
        self.assertTrue(preserved["preserveTimeWeekdayLayout"])

        manifest = json.loads(
            self.renderer._source_path(
                "assets/layers/source/manifest.json"
            ).read_text(encoding="utf-8")
        )
        approved = next(
            item
            for item in manifest["newAssets"]
            if item["id"] == "magpie_small_flight_right_v3_approved"
        )
        self.assertTrue(approved["preserveCenterDigitalTimeWeekday"])


if __name__ == "__main__":
    unittest.main()

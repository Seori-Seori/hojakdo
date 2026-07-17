from __future__ import annotations

import json
import unittest

import numpy as np
from PIL import Image, ImageChops

from .render_prototype import PrototypeRenderer
from .scene_calculator import HojakdoSceneCalculator


class HojakdoV23BatteryPlumTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calculator = HojakdoSceneCalculator()
        cls.renderer = PrototypeRenderer(cls.calculator)
        manifest_path = cls.renderer._source_path(
            cls.calculator.config["batteryPlum"]["manifest"]
        )
        cls.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_approved_battery_ranges_select_exactly_five_stages(self) -> None:
        samples = {
            -10: 0,
            0: 0,
            15: 0,
            16: 1,
            35: 1,
            36: 2,
            55: 2,
            56: 3,
            80: 3,
            81: 4,
            100: 4,
            120: 4,
        }
        for battery_percent, expected in samples.items():
            with self.subTest(battery_percent=battery_percent):
                self.assertEqual(
                    expected,
                    self.renderer.battery_plum_stage_index(battery_percent),
                )

    def test_plum_uses_static_swap_and_keeps_numeric_indicator(self) -> None:
        config = self.calculator.config["batteryPlum"]
        self.assertEqual("STATIC_LAYER_SWAP", config["transition"])
        self.assertFalse(config["animatedBloom"])
        self.assertTrue(config["keepNumericIndicator"])
        self.assertTrue(config["visibleInAod"])
        self.assertEqual(
            [[0, 15], [16, 35], [36, 55], [56, 80], [81, 100]],
            config["stageRanges"],
        )

    def test_stage_assets_are_cumulative_and_tightly_cropped(self) -> None:
        stages = self.manifest["stages"]
        self.assertEqual(5, len(stages))
        alpha_pixels = [int(stage["alphaPixels"]) for stage in stages]
        self.assertEqual(0, alpha_pixels[0])
        self.assertEqual(alpha_pixels, sorted(alpha_pixels))
        self.assertEqual(len(alpha_pixels), len(set(alpha_pixels)))

        decoded_bytes = []
        for stage in stages[1:]:
            width, height = stage["sizeSource"]
            decoded_bytes.append(int(width) * int(height) * 4)
        self.assertLess(max(decoded_bytes), 1_300_000)
        self.assertLess(sum(decoded_bytes), 4_500_000)

    def test_v23_preserves_battery_icon_and_percentage_pixels(self) -> None:
        v22_path = self.renderer._source_path(
            "assets/layers/mvp/clean_background_v22.png"
        )
        v23_path = self.renderer._source_path(
            "assets/layers/mvp/clean_background_v23.png"
        )
        with Image.open(v22_path) as source:
            v22 = source.convert("RGB")
        with Image.open(v23_path) as source:
            v23 = source.convert("RGB")
        sx = v22.width / 450.0
        sy = v22.height / 450.0
        battery_box = (
            int(round(194 * sx)),
            int(round(420 * sy)),
            int(round(276 * sx)),
            int(round(446 * sy)),
        )
        self.assertIsNone(
            ImageChops.difference(
                v22.crop(battery_box), v23.crop(battery_box)
            ).getbbox()
        )

    def test_background_changes_are_confined_to_the_approved_plum_crop(self) -> None:
        v22_path = self.renderer._source_path(
            "assets/layers/mvp/clean_background_v22.png"
        )
        v23_path = self.renderer._source_path(
            "assets/layers/mvp/clean_background_v23.png"
        )
        with Image.open(v22_path) as source:
            v22 = np.asarray(source.convert("RGB"))
        with Image.open(v23_path) as source:
            v23 = np.asarray(source.convert("RGB"))
        left, top, right, bottom = self.manifest["sourceCrop"]
        outside = np.ones(v22.shape[:2], dtype=bool)
        outside[top:bottom, left:right] = False
        self.assertTrue(np.array_equal(v22[outside], v23[outside]))

    def test_aod_keeps_the_same_stage_with_lower_opacity(self) -> None:
        normal = self.renderer._plum_layer(90, aod=False)
        aod = self.renderer._plum_layer(90, aod=True)
        normal_alpha = np.asarray(normal.getchannel("A"), dtype=np.uint32)
        aod_alpha = np.asarray(aod.getchannel("A"), dtype=np.uint32)
        self.assertGreater(int(np.count_nonzero(aod_alpha)), 0)
        self.assertEqual(
            int(np.count_nonzero(normal_alpha)),
            int(np.count_nonzero(aod_alpha)),
        )
        self.assertLess(int(aod_alpha.sum()), int(normal_alpha.sum()))


if __name__ == "__main__":
    unittest.main()

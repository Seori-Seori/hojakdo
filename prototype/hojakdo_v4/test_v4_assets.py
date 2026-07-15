from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image

from .build_v4_assets import (
    ANIMATION_DIR,
    DRAWABLE_DIR,
    FRAME_DIR,
    MANIFEST_PATH,
    OUTPUT_DIR,
    REPO_ROOT,
    build,
)
from .generate_watchface import WATCHFACE_PATH, generate


EXPECTED_ANIMATIONS = {
    "magpie_large_fly_pine_to_hand",
    "magpie_large_land_on_hand",
    "magpie_large_walk_step",
    "magpie_large_hop_to_tiger",
    "magpie_large_exit_right_jump",
    "magpie_large_head_tilt",
    "magpie_large_turn_perch",
    "magpie_small_fly_pine_to_hand",
    "magpie_small_land_on_hand",
    "magpie_small_walk_step",
    "magpie_small_hop_to_tiger",
    "magpie_small_head_scan",
    "magpie_small_look_plum",
    "magpie_small_turn_hop",
    "magpie_small_peck_tiger_ear",
    "tiger_head_eye_reaction",
}
EXPECTED_POSES = {
    "magpie_large_perch_hand",
    "magpie_large_walk_idle",
    "magpie_large_perch_tiger",
    "magpie_small_perch_hand",
    "magpie_small_walk_idle",
    "magpie_small_perch_tiger",
}
EXPECTED_MASKS = {
    "plum_foreground_mask",
    "pine_foreground_mask",
    "tiger_body_foreground_mask",
}


class HojakdoV4AssetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = build()
        generate()
        cls.root = ET.parse(WATCHFACE_PATH).getroot()

    def test_v4_manifest_and_approved_small_flight_size(self) -> None:
        self.assertEqual("4.0.0", self.manifest["version"])
        self.assertEqual("v4_complete_production_candidate", self.manifest["status"])
        flight = self.manifest["smallFlight"]
        self.assertEqual([100, 78], flight["sizeLogical"])
        self.assertEqual(0, flight["wingFlaps"])
        self.assertEqual("fixed_whole_sprite_translation", flight["motion"])
        with Image.open(DRAWABLE_DIR / flight["resource"]) as image:
            self.assertEqual((100, 78), image.size)
            self.assertIsNotNone(image.convert("RGBA").getchannel("A").getbbox())

    def test_six_static_poses_and_three_masks_are_complete(self) -> None:
        poses = {item["id"] for item in self.manifest["staticPoses"]}
        masks = {item["id"] for item in self.manifest["foregroundMasks"]}
        self.assertEqual(EXPECTED_POSES, poses)
        self.assertEqual(EXPECTED_MASKS, masks)
        for item in self.manifest["staticPoses"] + self.manifest["foregroundMasks"]:
            path = DRAWABLE_DIR / item["resource"]
            with Image.open(path) as source:
                image = source.convert("RGBA")
            self.assertEqual(tuple(item["sizeLogical"]), image.size)
            self.assertIsNotNone(image.getchannel("A").getbbox(), item["id"])
            pixels = np.asarray(image, dtype=np.uint8)
            hidden_rgb = (pixels[..., 3] == 0) & np.any(
                pixels[..., :3] != 0, axis=2
            )
            self.assertEqual(0, int(hidden_rgb.sum()), item["id"])

    def test_all_sixteen_agif_resources_have_frames_metadata_and_thumbnails(self) -> None:
        metadata_by_name = {item["id"]: item for item in self.manifest["animations"]}
        self.assertEqual(EXPECTED_ANIMATIONS, set(metadata_by_name))
        for name, metadata in metadata_by_name.items():
            gif_path = ANIMATION_DIR / metadata["resource"]
            thumbnail = DRAWABLE_DIR / metadata["thumbnail"]
            metadata_path = ANIMATION_DIR / f"{name}.json"
            frames = sorted((FRAME_DIR / name).glob("frame_*.png"))
            self.assertTrue(gif_path.is_file(), name)
            self.assertTrue(thumbnail.is_file(), name)
            self.assertTrue(metadata_path.is_file(), name)
            self.assertEqual(metadata["frameCount"], len(frames), name)
            self.assertGreaterEqual(len(frames), 6, name)
            for key in (
                "fps",
                "anchorX",
                "anchorY",
                "cropX",
                "cropY",
                "cropWidth",
                "cropHeight",
                "facing",
                "startPose",
                "endPose",
                "loopCount",
            ):
                self.assertIn(key, metadata, f"{name}:{key}")
            with Image.open(gif_path) as gif:
                self.assertEqual("GIF", gif.format, name)
                self.assertTrue(gif.is_animated, name)
                self.assertEqual(metadata["frameCount"], gif.n_frames, name)
                self.assertEqual(tuple(metadata["sizeLogical"]), gif.size, name)

    def test_plum_battery_stages_cover_the_full_range_without_gaps(self) -> None:
        stages = self.manifest["plumBatteryStages"]
        self.assertEqual(5, len(stages))
        coverage = []
        for item in stages:
            coverage.extend(
                range(item["minimumPercent"], item["maximumPercent"] + 1)
            )
            self.assertTrue((DRAWABLE_DIR / item["resource"]).is_file())
        self.assertEqual(list(range(101)), coverage)

    def test_live_wff_connects_every_animation_and_data_source(self) -> None:
        animated_parts = self.root.findall(".//PartAnimatedImage")
        self.assertEqual(16, len(animated_parts))
        names = {part.attrib["name"] for part in animated_parts}
        self.assertEqual(EXPECTED_ANIMATIONS, names)
        for part in animated_parts:
            self.assertIsNotNone(part.find("AnimationController"), part.attrib["name"])
            self.assertIsNotNone(part.find("AnimatedImage"), part.attrib["name"])
            self.assertIsNotNone(part.find("Thumbnail"), part.attrib["name"])
            ambient = part.find("Variant")
            self.assertIsNotNone(ambient, part.attrib["name"])
            self.assertEqual("0", ambient.attrib["value"])

        xml = WATCHFACE_PATH.read_text(encoding="utf-8")
        for source in (
            "HOUR_0_23_Z",
            "MINUTE_Z",
            "MONTH_Z",
            "DAY_Z",
            "DAY_OF_WEEK_S",
            "BATTERY_PERCENT",
            "YEAR",
            "DAY_OF_YEAR",
            "HOUR_0_23",
            "MINUTE",
        ):
            self.assertIn(f"[{source}]", xml)
        self.assertEqual(4, len(self.root.findall(".//PartText")))
        self.assertIn("hojakdo_v4_hour_branch", xml)
        self.assertIn("hojakdo_v4_minute_branch", xml)
        self.assertIn("magpie_small_flight_right_v4", xml)
        self.assertIn("[SECOND_MILLISECOND]", xml)
        self.assertIn("small_exit_fixed_flight", xml)
        live_index = xml.index('name="live_time"')
        for decorative_part in (
            'name="hour_hand_group"',
            'name="minute_hand_group"',
            'name="tiger_pupils"',
        ):
            self.assertGreater(live_index, xml.index(decorative_part))
        live_parts = {
            part.attrib["name"]: part.attrib for part in self.root.findall(".//PartText")
        }
        self.assertEqual(("171", "246"), (live_parts["live_time"]["x"], live_parts["live_time"]["y"]))
        self.assertEqual(("186", "275"), (live_parts["live_date"]["x"], live_parts["live_date"]["y"]))
        self.assertEqual(("190", "291"), (live_parts["live_weekday"]["x"], live_parts["live_weekday"]["y"]))

    def test_all_wff_image_resources_exist_and_names_are_android_safe(self) -> None:
        available = {path.stem for path in DRAWABLE_DIR.glob("*.png")}
        available |= {path.stem for path in ANIMATION_DIR.glob("*.gif")}
        available.add("preview")
        for element in self.root.findall(".//Image") + self.root.findall(
            ".//AnimatedImage"
        ) + self.root.findall(".//Thumbnail"):
            resource = element.attrib["resource"]
            self.assertRegex(resource, r"^[a-z][a-z0-9_]*$")
            self.assertIn(resource, available)

    def test_wff_expressions_have_balanced_parentheses(self) -> None:
        source_pattern = re.compile(r"\[[A-Z0-9_.]+\]")
        for expression in self.root.findall(".//Expression"):
            text = expression.text or ""
            depth = 0
            for character in text:
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    self.assertGreaterEqual(depth, 0, expression.attrib["name"])
            self.assertEqual(0, depth, expression.attrib["name"])
            self.assertTrue(source_pattern.search(text), expression.attrib["name"])

    def test_deterministic_schedule_alternates_and_meets_daily_target(self) -> None:
        cycle_count = (365 * 1440) // 43
        characters = ["LARGE" if index % 2 == 0 else "SMALL" for index in range(cycle_count)]
        self.assertTrue(
            all(a != b for a, b in zip(characters, characters[1:]))
        )
        hand_landings = sum(index % 11 in {0, 5} for index in range(cycle_count))
        per_day = hand_landings / 365
        self.assertGreater(per_day, 5.8)
        self.assertLess(per_day, 6.4)

    def test_decoded_memory_estimate_is_within_official_budgets(self) -> None:
        memory = self.manifest["memoryEstimate"]
        self.assertLess(
            memory["interactiveDecodedBytes"], memory["officialInteractiveBudgetBytes"]
        )
        self.assertLess(
            memory["staticDecodedBytes"], memory["officialAmbientBudgetBytes"]
        )

    def test_review_outputs_exist_at_logical_resolution(self) -> None:
        static = OUTPUT_DIR / "hojakdo_v4_integrated_static.png"
        board = OUTPUT_DIR / "hojakdo_v4_review_board.png"
        catalog = OUTPUT_DIR / "hojakdo_v4_animation_catalog.png"
        for path in (static, board, catalog, MANIFEST_PATH):
            self.assertTrue(path.is_file(), path)
        for path, expected_size in (
            (static, (450, 450)),
            (board, (940, 540)),
            (catalog, (1040, 740)),
        ):
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                self.assertEqual(expected_size, image.size)

        quiet_zone = self.manifest["readoutQuietZone"]
        self.assertEqual([-12, 20], quiet_zone["liveTextShiftLogical"])
        self.assertEqual(213, quiet_zone["liveTextCenterXLogical"])
        with Image.open(DRAWABLE_DIR / "hojakdo_v4_background.png") as source:
            background = np.asarray(source.convert("RGB"), dtype=np.float32)
        luma = (
            0.2126 * background[..., 0]
            + 0.7152 * background[..., 1]
            + 0.0722 * background[..., 2]
        )
        # Ignore the pivot's two bottom rows and require the former readout and
        # cloud-tail regions to contain paper texture rather than dark glyphs.
        readout = luma[228:295, 175:275]
        cloud_tail = luma[240:275, 148:202]
        self.assertLessEqual(int((readout < 145).sum()), 1)
        self.assertEqual(0, int((cloud_tail < 145).sum()))


if __name__ == "__main__":
    unittest.main()

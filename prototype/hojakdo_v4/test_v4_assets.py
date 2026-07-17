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
    HAND_ALPHA_THRESHOLD,
    HOUR_HAND_TARGET_LENGTH,
    MANIFEST_PATH,
    MINUTE_HAND_TARGET_LENGTH,
    OUTPUT_DIR,
    PIVOT,
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

    def test_v43_manifest_and_approved_small_flight_size(self) -> None:
        self.assertEqual("4.3.0", self.manifest["version"])
        self.assertEqual(
            "v4_3_lower_larger_top_readout_candidate",
            self.manifest["status"],
        )
        flight = self.manifest["smallFlight"]
        self.assertEqual([70, 54], flight["sizeLogical"])
        self.assertEqual(0, flight["wingFlaps"])
        self.assertEqual("fixed_whole_sprite_translation", flight["motion"])
        with Image.open(DRAWABLE_DIR / flight["resource"]) as image:
            self.assertEqual((70, 54), image.size)
            self.assertIsNotNone(image.convert("RGBA").getchannel("A").getbbox())

    def test_v41_hands_have_clear_length_hierarchy_and_synced_anchors(self) -> None:
        measurements: dict[str, tuple[float, int]] = {}
        for hand in ("hour", "minute"):
            path = DRAWABLE_DIR / f"hojakdo_v4_{hand}_branch.png"
            with Image.open(path) as source:
                rgba = np.asarray(source.convert("RGBA"), dtype=np.uint8)
            y, x = np.where(rgba[..., 3] > HAND_ALPHA_THRESHOLD)
            radial = np.hypot(x - PIVOT[0], y - PIVOT[1])
            measurements[hand] = (float(radial.max()), int(len(x)))

        hour_length, hour_pixels = measurements["hour"]
        minute_length, minute_pixels = measurements["minute"]
        self.assertAlmostEqual(HOUR_HAND_TARGET_LENGTH, hour_length, delta=2.0)
        self.assertAlmostEqual(
            MINUTE_HAND_TARGET_LENGTH, minute_length, delta=2.0
        )
        self.assertLess(hour_length / minute_length, 0.76)
        self.assertGreater(hour_pixels, int(minute_pixels * 1.25))

        expected_anchors = {
            "HOUR": {"LARGE": [293, 152], "SMALL": [290, 157]},
            "MINUTE": {"LARGE": [155, 114], "SMALL": [168, 118]},
        }
        self.assertEqual(
            expected_anchors,
            self.manifest["scene"]["handPerchAnchorsAtZero"],
        )
        for hand, characters in expected_anchors.items():
            for character, anchor in characters.items():
                carrier = self.root.find(
                    f'.//Group[@name="{hand.lower()}_{character.lower()}_carrier"]'
                )
                self.assertIsNotNone(carrier)
                self.assertAlmostEqual(
                    anchor[0] / 450,
                    float(carrier.attrib["pivotX"]),
                    places=8,
                )
                self.assertAlmostEqual(
                    anchor[1] / 450,
                    float(carrier.attrib["pivotY"]),
                    places=8,
                )

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
        self.assertEqual(
            "above_plum_foreground_mask_below_hands",
            self.manifest["plumBatteryLayer"],
        )
        with Image.open(DRAWABLE_DIR / stages[-1]["resource"]) as source:
            full_bloom = np.asarray(source.convert("RGBA"), dtype=np.uint8)
        self.assertGreater(int((full_bloom[..., 3] > 0).sum()), 9000)

        xml = WATCHFACE_PATH.read_text(encoding="utf-8")
        self.assertGreater(
            xml.index('name="plum_stage_5"'),
            xml.index('name="plum_foreground_mask"'),
        )
        self.assertLess(
            xml.index('name="plum_stage_5"'),
            xml.index('name="hour_hand_group"'),
        )
        self.assertLess(
            xml.index('name="plum_stage_5"'),
            xml.index('name="minute_hand_group"'),
        )
        plum_stage_index = xml.index('name="plum_stage_5"')
        hour_index = xml.index('name="hour_hand_group"')
        minute_index = xml.index('name="minute_hand_group"')
        for bird_part in (
            'name="large_plum_idle"',
            'name="small_plum_idle"',
            'name="magpie_large_walk_step"',
            'name="magpie_small_walk_step"',
        ):
            bird_index = xml.index(bird_part)
            self.assertGreater(bird_index, plum_stage_index)
            self.assertLess(bird_index, hour_index)
            self.assertLess(bird_index, minute_index)
        self.assertEqual(
            [
                "background",
                "readout_hanji_patch",
                "plum_foreground_mask",
                "plum_battery_stage",
                "plum_birds",
                "pine_foreground_mask",
                "tiger_body_foreground_mask",
                "tiger_head_or_reaction",
                "hour_hand",
                "minute_hand",
                "tiger_birds_and_exit",
                "bird_animations",
                "live_text",
            ],
            self.manifest["scene"]["layerOrder"],
        )
        stage_five = next(
            expression
            for expression in self.root.findall(".//Expression")
            if expression.attrib["name"] == "battery_stage_5"
        )
        self.assertEqual(
            "[BATTERY_PERCENT] >= 81 && [BATTERY_PERCENT] <= 100",
            (stage_five.text or "").strip(),
        )

    def test_live_wff_connects_every_animation_and_data_source(self) -> None:
        animated_parts = self.root.findall(".//PartAnimatedImage")
        self.assertEqual(16, len(animated_parts))
        names = {part.attrib["name"] for part in animated_parts}
        self.assertEqual(EXPECTED_ANIMATIONS, names)
        for part in animated_parts:
            controller = part.find("AnimationController")
            self.assertIsNotNone(controller, part.attrib["name"])
            expected_after = (
                "FIRST_FRAME"
                if part.attrib["name"] == "tiger_head_eye_reaction"
                else "HIDE"
            )
            self.assertEqual(expected_after, controller.attrib["afterPlaying"])
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
        self.assertEqual(3, len(self.root.findall(".//PartText")))
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
        patch_index = xml.index('name="readout_hanji_patch"')
        self.assertGreater(patch_index, xml.index('name="hojakdo_v4_background"'))
        self.assertLess(patch_index, xml.index('name="hour_hand_group"'))
        self.assertLess(patch_index, xml.index('name="minute_hand_group"'))
        self.assertGreater(live_index, xml.index('name="tiger_pupils"'))
        self.assertLess(
            xml.index('name="tiger_head"'),
            xml.index('name="large_tiger_idle"'),
        )
        self.assertLess(
            xml.index('name="tiger_head"'),
            xml.index('name="small_tiger_idle"'),
        )
        self.assertEqual(
            {"LARGE": [335.0, 233.0], "SMALL": [340.0, 241.0]},
            self.manifest["scene"]["tigerPerchAnchors"],
        )
        small_exit = next(
            part
            for part in self.root.findall(".//PartImage")
            if part.attrib.get("name") == "small_exit_fixed_flight"
        )
        self.assertEqual(
            ("293", "206", "70", "54"),
            tuple(
                small_exit.attrib[key]
                for key in ("x", "y", "width", "height")
            ),
        )
        self.assertLess(
            xml.index('name="tiger_head_eye_reaction"'),
            xml.index('name="small_tiger_idle"'),
        )
        self.assertLess(
            xml.index('name="small_tiger_idle"'),
            xml.index('name="magpie_small_hop_to_tiger"'),
        )
        live_parts = {
            part.attrib["name"]: part.attrib for part in self.root.findall(".//PartText")
        }
        self.assertEqual(
            {"live_time", "live_date_weekday", "live_battery"},
            set(live_parts),
        )
        self.assertEqual(
            ("142", "78", "166", "58"),
            tuple(
                live_parts["live_time"][key]
                for key in ("x", "y", "width", "height")
            ),
        )
        self.assertEqual(
            ("166", "129", "118", "25"),
            tuple(
                live_parts["live_date_weekday"][key]
                for key in ("x", "y", "width", "height")
            ),
        )
        time_font = next(
            part.find(".//Font")
            for part in self.root.findall(".//PartText")
            if part.attrib["name"] == "live_time"
        )
        date_weekday_font = next(
            part.find(".//Font")
            for part in self.root.findall(".//PartText")
            if part.attrib["name"] == "live_date_weekday"
        )
        self.assertEqual("46", time_font.attrib["size"])
        self.assertEqual("16", date_weekday_font.attrib["size"])

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

    def test_hand_tiger_and_small_perch_regressions_are_locked(self) -> None:
        xml = WATCHFACE_PATH.read_text(encoding="utf-8")
        hour_index = xml.index('name="hour_hand_group"')
        minute_index = xml.index('name="minute_hand_group"')
        for environmental_part in (
            'name="plum_stage_5"',
            'name="pine_foreground_mask"',
            'name="tiger_body_foreground_mask"',
            'name="tiger_head_eye_reaction"',
            'name="tiger_head"',
        ):
            self.assertLess(xml.index(environmental_part), hour_index)
            self.assertLess(xml.index(environmental_part), minute_index)

        tiger_conditions = [
            condition
            for condition in self.root.findall(".//Condition")
            if condition.find(
                './/PartAnimatedImage[@name="tiger_head_eye_reaction"]'
            )
            is not None
        ]
        self.assertEqual(1, len(tiger_conditions))
        tiger_condition = tiger_conditions[0]
        default = tiger_condition.find("Default")
        self.assertIsNotNone(default)
        self.assertIsNotNone(default.find('./PartImage[@name="tiger_head"]'))
        self.assertIsNotNone(default.find('./PartImage[@name="tiger_pupils"]'))
        compare = tiger_condition.find("Compare")
        self.assertIsNotNone(compare)
        for name, ambient_alpha in (
            ("tiger_head_reaction_ambient", "145"),
            ("tiger_pupils_reaction_ambient", "155"),
        ):
            fallback = compare.find(f'./PartImage[@name="{name}"]')
            self.assertIsNotNone(fallback)
            self.assertEqual("0", fallback.attrib["alpha"])
            variant = fallback.find("Variant")
            self.assertIsNotNone(variant)
            self.assertEqual("AMBIENT", variant.attrib["mode"])
            self.assertEqual("alpha", variant.attrib["target"])
            self.assertEqual(ambient_alpha, variant.attrib["value"])

        pose = next(
            item
            for item in self.manifest["staticPoses"]
            if item["id"] == "magpie_small_perch_tiger"
        )
        with Image.open(DRAWABLE_DIR / pose["resource"]) as source:
            bird_alpha = np.asarray(
                source.convert("RGBA").getchannel("A"), dtype=np.uint8
            )
        with Image.open(DRAWABLE_DIR / "hojakdo_v4_tiger_head.png") as source:
            head_alpha = np.asarray(
                source.convert("RGBA").getchannel("A"), dtype=np.uint8
            )
        anchor_x, anchor_y = pose["anchorLogical"]
        foot_x, foot_y = self.manifest["scene"]["tigerPerchAnchors"]["SMALL"]
        left = round(foot_x - anchor_x)
        top = round(foot_y - anchor_y)
        bird_canvas = np.zeros_like(head_alpha)
        bird_canvas[
            top : top + bird_alpha.shape[0],
            left : left + bird_alpha.shape[1],
        ] = bird_alpha
        contact_pixels = (bird_canvas > 128) & (head_alpha > 128)
        self.assertGreaterEqual(int(contact_pixels.sum()), 80)

        animation_by_name = {
            item["id"]: item for item in self.manifest["animations"]
        }
        for name, minimum_contact in (
            ("magpie_small_hop_to_tiger", 80),
            ("magpie_small_head_scan", 80),
            ("magpie_small_look_plum", 80),
            ("magpie_small_turn_hop", 30),
            ("magpie_small_peck_tiger_ear", 80),
        ):
            metadata = animation_by_name[name]
            last_frame = (
                FRAME_DIR
                / name
                / f"frame_{int(metadata['frameCount']) - 1:02d}.png"
            )
            with Image.open(last_frame) as source:
                frame_alpha = np.asarray(
                    source.convert("RGBA").getchannel("A"), dtype=np.uint8
                )
            x, y = metadata["placementLogical"]
            frame_canvas = np.zeros_like(head_alpha)
            frame_canvas[
                y : y + frame_alpha.shape[0],
                x : x + frame_alpha.shape[1],
            ] = frame_alpha
            overlap = (frame_canvas > 128) & (head_alpha > 128)
            self.assertGreaterEqual(
                int(overlap.sum()), minimum_contact, name
            )

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
        cleanup_review = OUTPUT_DIR / "hojakdo_v4_readout_cleanup_review.png"
        emulator_review = OUTPUT_DIR / "hojakdo_v4_emulator_regression_review.png"
        board = OUTPUT_DIR / "hojakdo_v4_review_board.png"
        catalog = OUTPUT_DIR / "hojakdo_v4_animation_catalog.png"
        for path in (
            static,
            cleanup_review,
            emulator_review,
            board,
            catalog,
            MANIFEST_PATH,
        ):
            self.assertTrue(path.is_file(), path)
        for path, expected_size in (
            (static, (450, 450)),
            (cleanup_review, (450, 450)),
            (emulator_review, (450, 450)),
            (board, (940, 540)),
            (catalog, (1040, 740)),
        ):
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                self.assertEqual(expected_size, image.size)

        with Image.open(emulator_review) as source:
            emulator_pixels = np.asarray(source.convert("RGB"), dtype=np.int16)
        plum_pixels = emulator_pixels[156:399, 25:183]
        visible_blossoms = (
            (plum_pixels[..., 0] - plum_pixels[..., 1] > 60)
            & (plum_pixels[..., 0] - plum_pixels[..., 2] > 75)
        )
        # The hands now correctly cross above the full bloom, so a small number
        # of blossom pixels are intentionally occluded in this 05:24 frame.
        self.assertGreater(int(visible_blossoms.sum()), 1800)

        quiet_zone = self.manifest["readoutQuietZone"]
        self.assertEqual(
            [198, 250, 252, 300],
            quiet_zone["dateCloudCleanupBoundsLogical"],
        )
        self.assertEqual(
            [188, 272, 270, 294],
            quiet_zone["dateFinalOverlayBoundsLogical"],
        )
        self.assertEqual(225, quiet_zone["liveTextCenterXLogical"])
        self.assertNotIn("liveTextShiftLogical", quiet_zone)
        self.assertEqual(
            {
                "layout": "top_two_rows_time_then_date_weekday",
                "centerXLogical": 225,
                "zOrder": "above_hands_birds_and_animations",
                "time": {
                    "yLogical": 85,
                    "fontSize": 46,
                    "wffBoundsLogical": [142, 78, 166, 58],
                },
                "dateWeekday": {
                    "yLogical": 132,
                    "fontSize": 16,
                    "separator": "  ",
                    "wffBoundsLogical": [166, 129, 118, 25],
                },
            },
            self.manifest["readoutLayout"],
        )
        self.assertEqual(
            [282, 158, 306, 181],
            self.manifest["backgroundCleanup"]["pineSprigBoundsLogical"],
        )
        self.assertEqual(
            [191, 309, 231, 414],
            self.manifest["backgroundCleanup"][
                "tigerHindLegGhostBoundsLogical"
            ],
        )
        patch_metadata = self.manifest["readoutHanjiPatch"]
        self.assertEqual([188, 272], patch_metadata["placementLogical"])
        self.assertEqual([82, 22], patch_metadata["sizeLogical"])
        self.assertEqual(
            "above_background_below_hands_and_decorations",
            patch_metadata["layer"],
        )
        with Image.open(DRAWABLE_DIR / str(patch_metadata["resource"])) as source:
            patch = np.asarray(source.convert("RGBA"), dtype=np.uint8)
        self.assertEqual((22, 82, 4), patch.shape)
        self.assertTrue(np.all(patch[2:-2, 2:-2, 3] == 255))
        patch_luma = (
            0.2126 * patch[..., 0]
            + 0.7152 * patch[..., 1]
            + 0.0722 * patch[..., 2]
        )
        self.assertEqual(0, int((patch_luma[2:-2, 2:-2] < 145).sum()))
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
        date_cloud = luma[255:295, 203:247]
        forced_date = luma[274:292, 190:268]
        pine_sprig = luma[163:176, 287:301]
        tiger_hind_leg_ghost = luma[325:390, 195:210]
        self.assertLessEqual(int((readout < 145).sum()), 1)
        self.assertEqual(0, int((cloud_tail < 145).sum()))
        self.assertGreater(float(np.percentile(date_cloud, 1)), 164.0)
        self.assertEqual(0, int((forced_date < 145).sum()))
        self.assertEqual(0, int((pine_sprig < 145).sum()))
        self.assertEqual(0, int((tiger_hind_leg_ghost < 130).sum()))


if __name__ == "__main__":
    unittest.main()

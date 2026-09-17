from __future__ import annotations

import json
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
MANIFEST_PATH = REPO_ROOT / "assets/layers/v4/manifest.json"
WATCHFACE_PATH = REPO_ROOT / "watchface/src/main/res/raw/watchface.xml"

# Use local calendar sources instead of UTC_TIMESTAMP so the expression graph
# only refreshes once per minute. A fixed 366-day stride keeps the key monotonic
# and deterministic across year boundaries without retaining state.
MINUTE_KEY = (
    "(([YEAR] * 527040) + ([DAY_OF_YEAR] * 1440) + "
    "([HOUR_0_23] * 60) + [MINUTE] - 32)"
)
CYCLE_INDEX = f"floor({MINUTE_KEY} / 43)"
CYCLE_LOCAL = f"({MINUTE_KEY} % 43)"
CHAR_LARGE = f"(({CYCLE_INDEX} % 2) == 0)"
CHAR_SMALL = f"(({CYCLE_INDEX} % 2) == 1)"
ROUTE_HOUR = f"(({CYCLE_INDEX} % 11) == 0)"
ROUTE_MINUTE = f"(({CYCLE_INDEX} % 11) == 5)"
ROUTE_HAND = f"({ROUTE_HOUR} || {ROUTE_MINUTE})"
ROUTE_PLUM = f"(!{ROUTE_HAND})"

# These two source animations used a horizontal squeeze through an almost
# zero-width silhouette to change facing direction. On a real watch that
# intermediate frame reads as a broken or mirrored bird. Runtime playback uses
# a deliberate paper-theatre cut from the first pose to the final pose instead.
HARD_CUT_TURN_ANIMATIONS = {
    "magpie_large_turn_perch",
    "magpie_small_turn_hop",
}


def _indent(block: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else line for line in block.splitlines())


def _variant(alpha: int = 0) -> str:
    return f'<Variant mode="AMBIENT" target="alpha" value="{alpha}" />'


def _part_image(
    resource: str,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    name: str | None = None,
    alpha: int | None = None,
    ambient_alpha: int | None = None,
) -> str:
    name_attr = f' name="{name}"' if name else ""
    alpha_attr = f' alpha="{alpha}"' if alpha is not None else ""
    children = [f'<Image resource="{resource}" />']
    if ambient_alpha is not None:
        children.append(_variant(ambient_alpha))
    inner = _indent("\n".join(children), 4)
    return (
        f'<PartImage{name_attr}{alpha_attr} x="{x}" y="{y}" width="{width}" height="{height}">\n'
        f"{inner}\n"
        "</PartImage>"
    )


def frame_resource_name(animation_name: str, frame_index: int) -> str:
    return f"{animation_name}_frame_{frame_index:02d}"


def runtime_frame_windows(
    metadata: dict[str, object],
) -> tuple[tuple[int, float, float | None], ...]:
    """Return absolute-second frame windows, holding the final pose.

    Watch Face Format's ON_VISIBLE controller restarts when the face becomes
    visible again. Selecting PNG frames from SECOND_MILLISECOND instead makes
    the rendered pose a pure function of wall-clock time, so screen and face
    switches restore the same frame instead of replaying an animation.
    """

    name = str(metadata["id"])
    frame_count = int(metadata["frameCount"])
    frame_seconds = float(metadata["frameDurationMs"]) / 1000.0
    if frame_count < 1 or frame_seconds <= 0:
        raise ValueError(f"Invalid runtime animation metadata: {name}")

    if name in HARD_CUT_TURN_ANIMATIONS:
        cut_at = (frame_count // 2) * frame_seconds
        return ((0, 0.0, cut_at), (frame_count - 1, cut_at, None))

    windows: list[tuple[int, float, float | None]] = []
    for frame_index in range(frame_count):
        start = frame_index * frame_seconds
        end = None if frame_index == frame_count - 1 else start + frame_seconds
        windows.append((frame_index, start, end))
    return tuple(windows)


def runtime_frame_index(
    metadata: dict[str, object], second_millisecond: float
) -> int:
    if not 0.0 <= second_millisecond < 60.0:
        raise ValueError("second_millisecond must be in [0, 60)")
    for frame_index, start, end in runtime_frame_windows(metadata):
        if second_millisecond >= start and (
            end is None or second_millisecond < end
        ):
            return frame_index
    raise AssertionError(f"No runtime frame for {metadata['id']}")


def _format_second(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _timeline_animation(metadata: dict[str, object]) -> str:
    x, y = (int(value) for value in metadata["placementLogical"])
    width, height = (int(value) for value in metadata["sizeLogical"])
    name = str(metadata["id"])
    expressions: list[tuple[str, str, str]] = []
    for slot, (frame_index, start, end) in enumerate(
        runtime_frame_windows(metadata)
    ):
        bounds = []
        if start > 0:
            bounds.append(
                f"[SECOND_MILLISECOND] >= {_format_second(start)}"
            )
        if end is not None:
            bounds.append(f"[SECOND_MILLISECOND] < {_format_second(end)}")
        expression = " && ".join(bounds) if bounds else "[SECOND_MILLISECOND] >= 0"
        part = _part_image(
            frame_resource_name(name, frame_index),
            x,
            y,
            width,
            height,
            name=f"{name}_runtime_slot_{slot:02d}",
            ambient_alpha=0,
        )
        expressions.append(
            (f"show_{name}_runtime_slot_{slot:02d}", expression, part)
        )

    return f'''<Group name="{name}" x="0" y="0" width="450" height="450">
{_indent(_condition(expressions), 4)}
</Group>'''


def _condition(
    expressions: list[tuple[str, str, str]],
    *,
    default: str | None = None,
) -> str:
    expression_lines = [
        f'<Expression name="{name}"><![CDATA[{expression}]]></Expression>'
        for name, expression, _ in expressions
    ]
    lines = ["<Condition>", "    <Expressions>"]
    lines.extend(f"        {line}" for line in expression_lines)
    lines.append("    </Expressions>")
    for name, _, element in expressions:
        lines.append(f'    <Compare expression="{name}">')
        lines.append(_indent(element, 8))
        lines.append("    </Compare>")
    if default is not None:
        lines.append("    <Default>")
        lines.append(_indent(default, 8))
        lines.append("    </Default>")
    lines.append("</Condition>")
    return "\n".join(lines)


def _pose_part(
    pose: dict[str, object], foot: tuple[int, int], name: str
) -> str:
    width, height = (int(value) for value in pose["sizeLogical"])
    anchor_x, anchor_y = (float(value) for value in pose["anchorLogical"])
    x = round(foot[0] - anchor_x)
    y = round(foot[1] - anchor_y)
    return _part_image(
        str(pose["id"]),
        x,
        y,
        width,
        height,
        name=name,
        ambient_alpha=0,
    )


def _small_exit_part(
    flight: dict[str, object], tiger_foot: tuple[int, int]
) -> str:
    progress = "([SECOND_MILLISECOND] / 60)"
    width, height = (int(value) for value in flight["sizeLogical"])
    anchor_x, anchor_y = (float(value) for value in flight["anchorLogical"])
    start_x = round(tiger_foot[0] - anchor_x)
    start_y = round(tiger_foot[1] - anchor_y)
    return f'''<PartImage name="small_exit_fixed_flight" x="{start_x}" y="{start_y}" width="{width}" height="{height}">
    <Image resource="magpie_small_flight_right_v4" />
    <Transform target="x" value="{start_x} + (204 * {progress})" />
    <Transform target="y" value="{start_y} - (163 * {progress}) + (96 * {progress} * {progress})" />
    {_variant(0)}
</PartImage>'''


def _carrier(
    hand: str,
    pose: dict[str, object],
    anchor: tuple[float, float],
    expression: str,
    character: str,
) -> str:
    width, height = (int(value) for value in pose["sizeLogical"])
    local_x, local_y = (float(value) for value in pose["anchorLogical"])
    x = round(anchor[0] - local_x)
    y = round(anchor[1] - local_y)
    if hand == "hour":
        inverse = "-(([HOUR_0_23_MINUTE] * 30) - 50.232272878132)"
    else:
        inverse = "-(([MINUTE_SECOND] * 6) - 325.271003720479)"
    pose_part = _part_image(
        str(pose["id"]),
        x,
        y,
        width,
        height,
        name=f"{hand}_{character.lower()}_perch",
        ambient_alpha=0,
    )
    carrier = f'''<Group name="{hand}_{character.lower()}_carrier" x="0" y="0" width="450" height="450"
    pivotX="{anchor[0] / 450:.9f}" pivotY="{anchor[1] / 450:.9f}">
    <Transform target="angle" value="{inverse}">
        <Animation duration="0.35" interpolation="EASE_IN_OUT" />
    </Transform>
{_indent(pose_part, 4)}
</Group>'''
    return _condition([(f"show_{hand}_{character.lower()}", expression, carrier)])


def _hand_group(
    hand: str,
    branch_resource: str,
    carriers: list[str],
) -> str:
    if hand == "hour":
        angle = "(([HOUR_0_23_MINUTE] * 30) - 50.232272878132)"
    else:
        angle = "(([MINUTE_SECOND] * 6) - 325.271003720479)"
    branch = _part_image(
        branch_resource,
        0,
        0,
        450,
        450,
        name=f"{hand}_branch",
        ambient_alpha=185,
    )
    body = [
        f'<Group name="{hand}_hand_group" x="0" y="0" width="450" height="450" pivotX="0.497777778" pivotY="0.460000000">',
        f'    <Transform target="angle" value="{angle}">',
        '        <Animation duration="0.35" interpolation="EASE_IN_OUT" />',
        "    </Transform>",
        _indent(branch, 4),
    ]
    body.extend(_indent(carrier, 4) for carrier in carriers)
    body.append("</Group>")
    return "\n".join(body)


def _live_text(layout: dict[str, object]) -> str:
    time_layout = layout["time"]
    date_weekday_layout = layout["dateWeekday"]
    time_x, time_y, time_width, time_height = time_layout["wffBoundsLogical"]
    date_x, date_y, date_width, date_height = date_weekday_layout[
        "wffBoundsLogical"
    ]
    separator = str(date_weekday_layout["separator"])
    time_part = f'''<PartText name="live_time" x="{time_x}" y="{time_y}" width="{time_width}" height="{time_height}">
    <Text align="CENTER" verticalAlign="CENTER">
        <Font family="SYNC_TO_DEVICE" size="{time_layout["fontSize"]}" color="#211811" weight="BOLD" letterSpacing="0.03">
            <Template>%s:%s
                <Parameter expression="[HOUR_0_23_Z]" />
                <Parameter expression="[MINUTE_Z]" />
            </Template>
        </Font>
    </Text>
    <Variant mode="AMBIENT" target="alpha" value="220" />
</PartText>'''
    date_weekday_part = f'''<PartText name="live_date_weekday" x="{date_x}" y="{date_y}" width="{date_width}" height="{date_height}">
    <Text align="CENTER" verticalAlign="CENTER">
        <Font family="SYNC_TO_DEVICE" size="{date_weekday_layout["fontSize"]}" color="#211811" weight="BOLD">
            <Upper><Template>%s.%s{separator}%s
                    <Parameter expression="[MONTH_Z]" />
                    <Parameter expression="[DAY_Z]" />
                    <Parameter expression="[DAY_OF_WEEK_S]" />
            </Template></Upper>
        </Font>
    </Text>
    <Variant mode="AMBIENT" target="alpha" value="220" />
</PartText>'''
    battery_icon = _part_image(
        "battery_icon", 194, 418, 22, 14, name="battery_icon", ambient_alpha=190
    )
    battery_part = '''<PartText name="live_battery" x="216" y="414" width="40" height="22">
    <Text align="CENTER" verticalAlign="CENTER">
        <Font family="SYNC_TO_DEVICE" size="12" color="#211811" weight="BOLD">
            <Template>%s%%<Parameter expression="[BATTERY_PERCENT]" /></Template>
        </Font>
    </Text>
    <Variant mode="AMBIENT" target="alpha" value="190" />
</PartText>'''
    return "\n".join((time_part, date_weekday_part, battery_icon, battery_part))


def generate() -> str:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    animations = {item["id"]: item for item in manifest["animations"]}
    poses = {item["id"]: item for item in manifest["staticPoses"]}
    masks = {item["id"]: item for item in manifest["foregroundMasks"]}
    small_flight = manifest["smallFlight"]
    tiger_anchors = {
        name: tuple(int(round(float(value))) for value in point)
        for name, point in manifest["scene"]["tigerPerchAnchors"].items()
    }
    hand_anchors = {
        hand: {
            character: tuple(float(value) for value in point)
            for character, point in anchors.items()
        }
        for hand, anchors in manifest["scene"][
            "handPerchAnchorsAtZero"
        ].items()
    }

    plum_expressions: list[tuple[str, str, str]] = []
    for stage in manifest["plumBatteryStages"]:
        minimum = int(stage["minimumPercent"])
        maximum = int(stage["maximumPercent"])
        x, y = (int(value) for value in stage["placementLogical"])
        width, height = (int(value) for value in stage["sizeLogical"])
        part = _part_image(
            Path(str(stage["resource"])).stem,
            x,
            y,
            width,
            height,
            name=f"plum_stage_{stage['stage']}",
            ambient_alpha=133,
        )
        plum_expressions.append(
            (
                f"battery_stage_{stage['stage']}",
                f"[BATTERY_PERCENT] >= {minimum} && [BATTERY_PERCENT] <= {maximum}",
                part,
            )
        )

    active_perch = f"({CYCLE_LOCAL} >= 4 && {CYCLE_LOCAL} <= 8)"
    hour_large = f"{CHAR_LARGE} && {ROUTE_HOUR} && {active_perch}"
    hour_small = f"{CHAR_SMALL} && {ROUTE_HOUR} && {active_perch}"
    minute_large = f"{CHAR_LARGE} && {ROUTE_MINUTE} && {active_perch}"
    minute_small = f"{CHAR_SMALL} && {ROUTE_MINUTE} && {active_perch}"
    hour_group = _hand_group(
        "hour",
        "hojakdo_v4_hour_branch",
        [
            _carrier(
                "hour",
                poses["magpie_large_perch_hand"],
                hand_anchors["HOUR"]["LARGE"],
                hour_large,
                "large",
            ),
            _carrier(
                "hour",
                poses["magpie_small_perch_hand"],
                hand_anchors["HOUR"]["SMALL"],
                hour_small,
                "small",
            ),
        ],
    )
    minute_group = _hand_group(
        "minute",
        "hojakdo_v4_minute_branch",
        [
            _carrier(
                "minute",
                poses["magpie_large_perch_hand"],
                hand_anchors["MINUTE"]["LARGE"],
                minute_large,
                "large",
            ),
            _carrier(
                "minute",
                poses["magpie_small_perch_hand"],
                hand_anchors["MINUTE"]["SMALL"],
                minute_small,
                "small",
            ),
        ],
    )

    animation_slots = {
        "magpie_large_fly_pine_to_hand": f"{CHAR_LARGE} && {ROUTE_HAND} && {CYCLE_LOCAL} == 2",
        "magpie_large_land_on_hand": f"{CHAR_LARGE} && {ROUTE_HAND} && {CYCLE_LOCAL} == 3",
        "magpie_large_walk_step": f"{CHAR_LARGE} && {ROUTE_PLUM} && {CYCLE_LOCAL} == 2",
        "magpie_large_hop_to_tiger": f"{CHAR_LARGE} && {CYCLE_LOCAL} == 9",
        "magpie_large_head_tilt": f"{CHAR_LARGE} && {CYCLE_LOCAL} == 11",
        "magpie_large_turn_perch": f"{CHAR_LARGE} && {CYCLE_LOCAL} == 12",
        "magpie_large_exit_right_jump": f"{CHAR_LARGE} && {CYCLE_LOCAL} == 41",
        "magpie_small_fly_pine_to_hand": f"{CHAR_SMALL} && {ROUTE_HAND} && {CYCLE_LOCAL} == 2",
        "magpie_small_land_on_hand": f"{CHAR_SMALL} && {ROUTE_HAND} && {CYCLE_LOCAL} == 3",
        "magpie_small_walk_step": f"{CHAR_SMALL} && {ROUTE_PLUM} && {CYCLE_LOCAL} == 2",
        "magpie_small_hop_to_tiger": f"{CHAR_SMALL} && {CYCLE_LOCAL} == 9",
        "magpie_small_head_scan": f"{CHAR_SMALL} && {CYCLE_LOCAL} == 11",
        "magpie_small_look_plum": f"{CHAR_SMALL} && {CYCLE_LOCAL} == 12",
        "magpie_small_turn_hop": f"{CHAR_SMALL} && {CYCLE_LOCAL} == 13",
        "magpie_small_peck_tiger_ear": f"{CHAR_SMALL} && {CYCLE_LOCAL} == 14",
        "tiger_head_eye_reaction": f"{CYCLE_LOCAL} == 10",
    }
    walk_animation_names = {
        "magpie_large_walk_step",
        "magpie_small_walk_step",
    }
    walk_animation_condition = _condition(
        [
            (f"show_{name}", expression, _timeline_animation(animations[name]))
            for name, expression in animation_slots.items()
            if name in walk_animation_names
        ]
    )
    tiger_reaction_part = _timeline_animation(
        animations["tiger_head_eye_reaction"]
    )
    high_animation_condition = _condition(
        [
            (f"show_{name}", expression, _timeline_animation(animations[name]))
            for name, expression in animation_slots.items()
            if name not in walk_animation_names
            and name != "tiger_head_eye_reaction"
        ]
    )

    plum_static_condition = _condition(
        [
            (
                "large_plum_idle",
                f"{CHAR_LARGE} && {ROUTE_PLUM} && {CYCLE_LOCAL} >= 3 && {CYCLE_LOCAL} <= 8",
                _pose_part(
                    poses["magpie_large_walk_idle"],
                    (151, 337),
                    "large_plum_idle",
                ),
            ),
            (
                "small_plum_idle",
                f"{CHAR_SMALL} && {ROUTE_PLUM} && {CYCLE_LOCAL} >= 3 && {CYCLE_LOCAL} <= 8",
                _pose_part(
                    poses["magpie_small_walk_idle"],
                    (155, 336),
                    "small_plum_idle",
                ),
            ),
        ]
    )
    tiger_static_condition = _condition(
        [
            (
                "large_tiger_idle",
                f"{CHAR_LARGE} && ({CYCLE_LOCAL} == 10 || ({CYCLE_LOCAL} >= 13 && {CYCLE_LOCAL} <= 40))",
                _pose_part(
                    poses["magpie_large_perch_tiger"],
                    tiger_anchors["LARGE"],
                    "large_tiger_idle",
                ),
            ),
            (
                "small_tiger_idle",
                f"{CHAR_SMALL} && ({CYCLE_LOCAL} == 10 || ({CYCLE_LOCAL} >= 15 && {CYCLE_LOCAL} <= 40))",
                _pose_part(
                    poses["magpie_small_perch_tiger"],
                    tiger_anchors["SMALL"],
                    "small_tiger_idle",
                ),
            ),
            (
                "small_exit_fixed_flight",
                f"{CHAR_SMALL} && {CYCLE_LOCAL} == 41",
                _small_exit_part(small_flight, tiger_anchors["SMALL"]),
            ),
        ]
    )

    mask_parts: dict[str, str] = {}
    for name in (
        "pine_foreground_mask",
        "plum_foreground_mask",
        "tiger_body_foreground_mask",
    ):
        mask = masks[name]
        x, y = (int(value) for value in mask["placementLogical"])
        width, height = (int(value) for value in mask["sizeLogical"])
        mask_parts[name] = _part_image(
            name, x, y, width, height, name=name, ambient_alpha=145
        )

    background = _part_image(
        "hojakdo_v4_background",
        0,
        0,
        450,
        450,
        name="hojakdo_v4_background",
        ambient_alpha=145,
    )
    tiger_head = _part_image(
        "hojakdo_v4_tiger_head",
        0,
        0,
        450,
        450,
        name="tiger_head",
        ambient_alpha=145,
    )
    tiger_pupils = _part_image(
        "hojakdo_v4_tiger_pupils",
        0,
        0,
        450,
        450,
        name="tiger_pupils",
        ambient_alpha=155,
    )
    # Animated images are transparent in ambient mode. These zero-alpha
    # interactive fallbacks become visible only in AOD, preventing the tiger
    # from losing its head during the one-minute reaction condition.
    tiger_head_reaction_ambient = _part_image(
        "hojakdo_v4_tiger_head",
        0,
        0,
        450,
        450,
        name="tiger_head_reaction_ambient",
        alpha=0,
        ambient_alpha=145,
    )
    tiger_pupils_reaction_ambient = _part_image(
        "hojakdo_v4_tiger_pupils",
        0,
        0,
        450,
        450,
        name="tiger_pupils_reaction_ambient",
        alpha=0,
        ambient_alpha=155,
    )
    tiger_visual_condition = _condition(
        [
            (
                "show_tiger_head_eye_reaction",
                animation_slots["tiger_head_eye_reaction"],
                "\n".join(
                    (
                        tiger_head_reaction_ambient,
                        tiger_pupils_reaction_ambient,
                        tiger_reaction_part,
                    )
                ),
            )
        ],
        # The static head must not remain under the moving head. Keeping the
        # two versions mutually exclusive makes the small tilt and pupil lag
        # visible instead of averaging into an apparently frozen tiger.
        default="\n".join((tiger_head, tiger_pupils)),
    )
    hanji_patch = manifest["readoutHanjiPatch"]
    patch_x, patch_y = (int(value) for value in hanji_patch["placementLogical"])
    patch_width, patch_height = (
        int(value) for value in hanji_patch["sizeLogical"]
    )
    readout_hanji_patch = _part_image(
        Path(str(hanji_patch["resource"])).stem,
        patch_x,
        patch_y,
        patch_width,
        patch_height,
        name="readout_hanji_patch",
        # The underlying background contains the same forced repair. Hiding
        # this overlay in ambient avoids stacking two translucent paper layers.
        ambient_alpha=0,
    )
    scene_parts = [
        background,
        # The repair patch must never cover a rotating hand. Keep it directly
        # above the base background and below every decorative/runtime layer.
        readout_hanji_patch,
        # Restore the complete plum first, then keep both the walking
        # animation and its idle pose visibly in front of every branch and
        # battery-driven blossom. All of these layers remain below the hands.
        mask_parts["plum_foreground_mask"],
        _condition(plum_expressions),
        plum_static_condition,
        walk_animation_condition,
        # Resolve all environmental depth before the hands. The previous
        # order left the pine mask above a down-left minute hand, making it
        # disappear around frames such as 11:42.
        mask_parts["pine_foreground_mask"],
        mask_parts["tiger_body_foreground_mask"],
        tiger_visual_condition,
        hour_group,
        minute_group,
        # Tiger-perched birds and active bird animations remain above the
        # hands so feet, hops, and landings are not clipped.
        tiger_static_condition,
        high_animation_condition,
        _live_text(manifest["readoutLayout"]),
    ]
    xml = '''<?xml version="1.0" encoding="utf-8"?>
<WatchFace width="450" height="450">
    <Metadata key="CLOCK_TYPE" value="ANALOG" />
    <Metadata key="PREVIEW_TIME" value="14:18:00" />
    <Scene backgroundColor="#000000">
{parts}
    </Scene>
</WatchFace>
'''.format(parts="\n\n".join(_indent(part, 8) for part in scene_parts))
    WATCHFACE_PATH.write_text(xml, encoding="utf-8")
    return xml


def main() -> None:
    xml = generate()
    print(WATCHFACE_PATH)
    print(f"bytes={len(xml.encode('utf-8'))}")


if __name__ == "__main__":
    main()

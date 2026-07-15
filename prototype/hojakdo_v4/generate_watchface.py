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
    ambient_alpha: int | None = None,
) -> str:
    name_attr = f' name="{name}"' if name else ""
    children = [f'<Image resource="{resource}" />']
    if ambient_alpha is not None:
        children.append(_variant(ambient_alpha))
    inner = _indent("\n".join(children), 4)
    return (
        f'<PartImage{name_attr} x="{x}" y="{y}" width="{width}" height="{height}">\n'
        f"{inner}\n"
        "</PartImage>"
    )


def _part_animation(metadata: dict[str, object]) -> str:
    x, y = (int(value) for value in metadata["placementLogical"])
    width, height = (int(value) for value in metadata["sizeLogical"])
    name = str(metadata["id"])
    return f'''<PartAnimatedImage name="{name}" x="{x}" y="{y}" width="{width}" height="{height}">
    <AnimationController play="ON_VISIBLE" repeat="FALSE" loopCount="1"
        resumePlayBack="FALSE" beforePlaying="FIRST_FRAME" afterPlaying="HIDE" />
    <AnimatedImage resource="{name}" format="AGIF" thumbnail="{name}_thumbnail" />
    <Thumbnail resource="{name}_thumbnail" />
    {_variant(0)}
</PartAnimatedImage>'''


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


def _small_exit_part() -> str:
    progress = "([SECOND_MILLISECOND] / 60)"
    return f'''<PartImage name="small_exit_fixed_flight" x="277" y="150" width="100" height="78">
    <Image resource="magpie_small_flight_right_v4" />
    <Transform target="x" value="277 + (204 * {progress})" />
    <Transform target="y" value="150 - (163 * {progress}) + (96 * {progress} * {progress})" />
    {_variant(0)}
</PartImage>'''


def _carrier(
    hand: str,
    pose: dict[str, object],
    anchor: tuple[int, int],
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


def _live_text() -> str:
    time_part = '''<PartText name="live_time" x="183" y="246" width="84" height="31">
    <Text align="CENTER" verticalAlign="CENTER">
        <Font family="SYNC_TO_DEVICE" size="25" color="#211811" weight="BOLD" letterSpacing="0.03">
            <Template>%s:%s
                <Parameter expression="[HOUR_0_23_Z]" />
                <Parameter expression="[MINUTE_Z]" />
            </Template>
        </Font>
    </Text>
    <Variant mode="AMBIENT" target="alpha" value="220" />
</PartText>'''
    date_part = '''<PartText name="live_date" x="198" y="275" width="54" height="15">
    <Text align="CENTER" verticalAlign="CENTER">
        <Font family="SYNC_TO_DEVICE" size="11" color="#211811" weight="BOLD">
            <Template>%s.%s
                <Parameter expression="[MONTH_Z]" />
                <Parameter expression="[DAY_Z]" />
            </Template>
        </Font>
    </Text>
    <Variant mode="AMBIENT" target="alpha" value="220" />
</PartText>'''
    weekday_part = '''<PartText name="live_weekday" x="202" y="291" width="46" height="13">
    <Text align="CENTER" verticalAlign="CENTER">
        <Font family="SYNC_TO_DEVICE" size="9" color="#211811" weight="BOLD">
            <Upper><Template>%s<Parameter expression="[DAY_OF_WEEK_S]" /></Template></Upper>
        </Font>
    </Text>
    <Variant mode="AMBIENT" target="alpha" value="220" />
</PartText>'''
    battery_icon = _part_image(
        "battery_icon", 186, 418, 22, 14, name="battery_icon", ambient_alpha=190
    )
    battery_part = '''<PartText name="live_battery" x="208" y="414" width="48" height="22">
    <Text align="START" verticalAlign="CENTER">
        <Font family="SYNC_TO_DEVICE" size="12" color="#211811" weight="BOLD">
            <Template>%s%%<Parameter expression="[BATTERY_PERCENT]" /></Template>
        </Font>
    </Text>
    <Variant mode="AMBIENT" target="alpha" value="190" />
</PartText>'''
    return "\n".join((time_part, date_part, weekday_part, battery_icon, battery_part))


def generate() -> str:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    animations = {item["id"]: item for item in manifest["animations"]}
    poses = {item["id"]: item for item in manifest["staticPoses"]}
    masks = {item["id"]: item for item in manifest["foregroundMasks"]}

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
                (305, 143),
                hour_large,
                "large",
            ),
            _carrier(
                "hour",
                poses["magpie_small_perch_hand"],
                (302, 148),
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
                (159, 118),
                minute_large,
                "large",
            ),
            _carrier(
                "minute",
                poses["magpie_small_perch_hand"],
                (171, 122),
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
    animation_condition = _condition(
        [
            (f"show_{name}", expression, _part_animation(animations[name]))
            for name, expression in animation_slots.items()
        ]
    )

    static_expressions = [
        (
            "large_plum_idle",
            f"{CHAR_LARGE} && {ROUTE_PLUM} && {CYCLE_LOCAL} >= 3 && {CYCLE_LOCAL} <= 8",
            _pose_part(
                poses["magpie_large_walk_idle"], (151, 337), "large_plum_idle"
            ),
        ),
        (
            "small_plum_idle",
            f"{CHAR_SMALL} && {ROUTE_PLUM} && {CYCLE_LOCAL} >= 3 && {CYCLE_LOCAL} <= 8",
            _pose_part(
                poses["magpie_small_walk_idle"], (155, 336), "small_plum_idle"
            ),
        ),
        (
            "large_tiger_idle",
            f"{CHAR_LARGE} && {CYCLE_LOCAL} >= 13 && {CYCLE_LOCAL} <= 40",
            _pose_part(
                poses["magpie_large_perch_tiger"], (335, 233), "large_tiger_idle"
            ),
        ),
        (
            "small_tiger_idle",
            f"{CHAR_SMALL} && {CYCLE_LOCAL} >= 15 && {CYCLE_LOCAL} <= 40",
            _pose_part(
                poses["magpie_small_perch_tiger"], (340, 218), "small_tiger_idle"
            ),
        ),
        (
            "small_exit_fixed_flight",
            f"{CHAR_SMALL} && {CYCLE_LOCAL} == 41",
            _small_exit_part(),
        ),
    ]
    static_condition = _condition(static_expressions)

    mask_parts = []
    for name in (
        "pine_foreground_mask",
        "plum_foreground_mask",
        "tiger_body_foreground_mask",
    ):
        mask = masks[name]
        x, y = (int(value) for value in mask["placementLogical"])
        width, height = (int(value) for value in mask["sizeLogical"])
        mask_parts.append(
            _part_image(name, x, y, width, height, name=name, ambient_alpha=145)
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
    scene_parts = [
        background,
        _condition(plum_expressions),
        hour_group,
        minute_group,
        static_condition,
        animation_condition,
        *mask_parts,
        tiger_head,
        tiger_pupils,
        # Keep live data above every decorative hand, character, and mask. The
        # approved center is a quiet readout zone, not an animation surface.
        _live_text(),
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

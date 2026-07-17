from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
CONFIG_PATH = PACKAGE_DIR / "config.json"
APPROVED_SOURCE = (
    REPO_ROOT
    / "assets/layers/source/drafts/magpie_small_flight_right_v3_approved.png"
)
ALIGNED_MASTER = (
    REPO_ROOT
    / "assets/layers/source/characters/magpie_small_flight_right_v31_master.png"
)
RUNTIME_SPRITE = (
    REPO_ROOT / "assets/layers/mvp/magpie_small_flight_right_v31.png"
)
METADATA_PATH = (
    REPO_ROOT
    / "assets/layers/source/characters/magpie_small_flight_right_v31.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _largest_component(mask: np.ndarray) -> np.ndarray:
    labels, count = ndimage.label(
        mask, structure=np.ones((3, 3), dtype=bool)
    )
    if count == 0:
        raise RuntimeError("Approved flight source has no foreground component")
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    return labels == int(np.argmax(sizes))


def _extract_master(source: Image.Image) -> tuple[Image.Image, tuple[int, ...]]:
    rgb_u8 = np.asarray(source.convert("RGB"), dtype=np.uint8)
    rgb = rgb_u8.astype(np.float32)
    luminance = (
        0.2126 * rgb[:, :, 0]
        + 0.7152 * rgb[:, :, 1]
        + 0.0722 * rgb[:, :, 2]
    )

    # The approved outline is one connected ink component. Filling only holes
    # enclosed by it keeps the paper-colored belly while excluding the hanji
    # preview background. These values reproduce the approved V3.1 review GIF.
    ink = _largest_component(luminance < 160.0)
    ink = ndimage.binary_closing(
        ink, structure=np.ones((3, 3), dtype=bool), iterations=1
    )
    silhouette = ndimage.binary_fill_holes(ink)
    soft = ndimage.gaussian_filter(silhouette.astype(np.float32), sigma=0.62)
    alpha = np.clip((soft - 0.035) / 0.93 * 255.0, 0, 255).astype(np.uint8)
    alpha[soft >= 0.985] = 255

    ys, xs = np.where(alpha > 1)
    if len(xs) == 0:
        raise RuntimeError("Flight extraction produced an empty alpha channel")
    visible_bounds = (
        int(xs.min()),
        int(ys.min()),
        int(xs.max()) + 1,
        int(ys.max()) + 1,
    )

    rgba = np.zeros((source.height, source.width, 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb_u8
    rgba[:, :, 3] = alpha
    rgba[alpha == 0, :3] = 0
    return Image.fromarray(rgba, "RGBA"), visible_bounds


def build() -> dict[str, object]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    flight = config["smallExit"]
    expected_sha = str(flight["approvedSourceSha256"])
    actual_sha = _sha256(APPROVED_SOURCE)
    if actual_sha != expected_sha:
        raise RuntimeError(
            f"Approved source hash mismatch: expected {expected_sha}, got {actual_sha}"
        )

    with Image.open(APPROVED_SOURCE) as image:
        source = image.convert("RGB")
    master, visible_bounds = _extract_master(source)

    padding = int(flight["sourcePaddingPixels"])
    left = max(0, visible_bounds[0] - padding)
    top = max(0, visible_bounds[1] - padding)
    right = min(master.width, visible_bounds[2] + padding)
    bottom = min(master.height, visible_bounds[3] + padding)
    crop_box = (left, top, right, bottom)
    crop = master.crop(crop_box)

    target_width = int(flight["runtimeWidthLogical"])
    target_height = max(1, round(crop.height * target_width / crop.width))
    runtime = crop.resize(
        (target_width, target_height), Image.Resampling.LANCZOS
    )
    runtime_pixels = np.asarray(runtime, dtype=np.uint8).copy()
    runtime_pixels[runtime_pixels[:, :, 3] == 0, :3] = 0
    runtime = Image.fromarray(runtime_pixels, "RGBA")

    ALIGNED_MASTER.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SPRITE.parent.mkdir(parents=True, exist_ok=True)
    master.save(ALIGNED_MASTER, optimize=True)
    runtime.save(RUNTIME_SPRITE, optimize=True)

    anchor_normalized = tuple(float(value) for value in flight["anchorNormalized"])
    anchor_runtime = (
        round(target_width * anchor_normalized[0], 3),
        round(target_height * anchor_normalized[1], 3),
    )
    alpha = np.asarray(runtime.getchannel("A"), dtype=np.uint8)
    pixels = np.asarray(runtime, dtype=np.uint8)
    hidden_rgb = int(np.count_nonzero(np.any(pixels[:, :, :3] != 0, axis=2) & (alpha == 0)))
    metadata: dict[str, object] = {
        "schemaVersion": 1,
        "status": "v3_1_fixed_flight_runtime_approved",
        "approvedSource": str(APPROVED_SOURCE.relative_to(REPO_ROOT)),
        "approvedSourceSha256": actual_sha,
        "sourceCanvas": [source.width, source.height],
        "visibleBoundsSource": list(visible_bounds),
        "safeCropSource": list(crop_box),
        "sourcePaddingPixels": padding,
        "alignedMaster": str(ALIGNED_MASTER.relative_to(REPO_ROOT)),
        "alignedMasterSha256": _sha256(ALIGNED_MASTER),
        "runtimeSprite": str(RUNTIME_SPRITE.relative_to(REPO_ROOT)),
        "runtimeSpriteSha256": _sha256(RUNTIME_SPRITE),
        "runtimeSizeLogical": [target_width, target_height],
        "anchorNormalized": list(anchor_normalized),
        "anchorRuntimeLogical": list(anchor_runtime),
        "animation": "STATIC_SPRITE_TRANSLATION",
        "easing": "SMOOTHSTEP",
        "arcHeightLogical": float(flight["arcHeightLogical"]),
        "rotationDegrees": 0,
        "scaleStart": 1.0,
        "scaleEnd": 1.0,
        "wingFlaps": 0,
        "wholeSpriteMoves": True,
        "fullyTransparentRgbPixels": hidden_rgb,
    }
    METADATA_PATH.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def main() -> None:
    metadata = build()
    print(ALIGNED_MASTER)
    print(RUNTIME_SPRITE)
    print(METADATA_PATH)
    print(
        "runtime="
        f"{metadata['runtimeSizeLogical'][0]}x{metadata['runtimeSizeLogical'][1]} "
        f"anchor={metadata['anchorRuntimeLogical']}"
    )


if __name__ == "__main__":
    main()

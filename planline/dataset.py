"""Curate verified, full-string dimension crops for Planline OCR experiments.

The dataset is kept separate from the source repository by default. Each sample
stores the exact transcription, crop image, source drawing group and optional
writer group so train/validation/test splits cannot leak related handwriting.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import warnings
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

DATASET_SCHEMA = "planline-handwriting-crops/v1"
REVIEW_SCHEMA = "planline-detection-review/v1"
MANIFEST_NAME = "manifest.jsonl"
SPLITS_NAME = "splits.json"
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_BYTES = 25 * 1024 * 1024
VALID_STYLES = {"handwritten", "printed", "unclear", "unknown"}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decode_raster(path: Path) -> np.ndarray:
    """Decode using the same OpenCV colour path as the web detector API."""
    if not path.is_file():
        raise ValueError(f"Image does not exist: {path}")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError(f"Image file is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB: {path.name}")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as probe:
                width, height = probe.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise ValueError(
                        f"Image dimensions {width} × {height} exceed the "
                        f"{MAX_IMAGE_PIXELS:,}-pixel dataset limit."
                    )
    except ValueError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError("Image exceeds the configured pixel limit.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError(
            f"Could not read {path.name} as a raster image. For PDF input, "
            "rasterise the analysed page first."
        ) from exc

    encoded = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"OpenCV could not decode image: {path}")
    height, width = image.shape[:2]
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError("Decoded image exceeds the configured pixel limit.")
    return image


def _encode_png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise ValueError("Could not encode crop as PNG.")
    return encoded.tobytes()


def _normalise_writer(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _crop_id(
    source_id: str,
    crop_sha256: str,
    text: str,
    writer_id: str | None,
    detection_id: str | None,
) -> str:
    identity = "\0".join((source_id, writer_id or "", detection_id or "", crop_sha256, text))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _read_manifest(dataset_dir: Path) -> list[dict[str, Any]]:
    manifest = dataset_dir / MANIFEST_NAME
    if not manifest.exists():
        return []
    entries: list[dict[str, Any]] = []
    with manifest.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {manifest.name} line {line_number}.") from exc
            if not isinstance(item, dict):
                raise ValueError(f"Manifest line {line_number} must be a JSON object.")
            entries.append(item)
    return entries


def _write_entries(dataset_dir: Path, new_entries: list[tuple[dict[str, Any], bytes]]) -> dict[str, int]:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    images_dir = dataset_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    existing = _read_manifest(dataset_dir)
    existing_by_id = {item.get("crop_id"): item for item in existing}
    if len(existing_by_id) != len(existing):
        raise ValueError("Existing manifest contains duplicate crop_id values; fix it before importing more crops.")

    added = 0
    skipped = 0
    for entry, image_bytes in new_entries:
        crop_id = entry["crop_id"]
        previous = existing_by_id.get(crop_id)
        if previous is not None:
            if previous.get("crop_sha256") != entry.get("crop_sha256") or previous.get("text") != entry.get("text"):
                raise ValueError(f"Crop ID collision with different content: {crop_id}")
            skipped += 1
            continue
        image_path = dataset_dir / entry["image_path"]
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image_bytes)
        existing.append(entry)
        existing_by_id[crop_id] = entry
        added += 1

    if added:
        manifest_path = dataset_dir / MANIFEST_NAME
        temporary = manifest_path.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for item in existing:
                handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temporary, manifest_path)
        # Any previous split no longer describes the complete dataset.
        (dataset_dir / SPLITS_NAME).unlink(missing_ok=True)

    return {"added": added, "skipped_duplicates": skipped, "total": len(existing)}


def export_review_crops(
    review_path: Path,
    image_path: Path,
    output_dir: Path,
    *,
    text_style: str = "handwritten",
    source_id: str | None = None,
    writer_id: str | None = None,
) -> dict[str, int]:
    """Extract only verified manual labels from a Planline review export."""
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Review file is not valid JSON: {review_path}") from exc
    if not isinstance(review, dict) or review.get("schema_version") != REVIEW_SCHEMA:
        raise ValueError(f"Review must use {REVIEW_SCHEMA}.")
    if text_style not in {"handwritten", "printed", "all"}:
        raise ValueError("text_style must be handwritten, printed or all.")

    image = _decode_raster(image_path)
    height, width = image.shape[:2]
    source = review.get("source")
    if not isinstance(source, dict):
        raise ValueError("Review JSON is missing source metadata.")
    if source.get("image_width_px") != width or source.get("image_height_px") != height:
        raise ValueError(
            "The supplied image dimensions do not match the review export. "
            "Use the exact raster image/page that was analysed."
        )

    source_sha = _sha256_file(image_path)
    stable_source_id = (source_id or f"sha256:{source_sha}").strip()
    if not stable_source_id:
        raise ValueError("source_id cannot be empty.")
    stable_writer_id = _normalise_writer(writer_id)
    source_filename = source.get("filename") or image_path.name
    review_items = review.get("manual_dimension_text_review")
    if not isinstance(review_items, list):
        raise ValueError("Review JSON is missing manual_dimension_text_review.")

    new_entries: list[tuple[dict[str, Any], bytes]] = []
    skipped_unverified = 0
    skipped_style = 0
    skipped_blank = 0
    skipped_no_crop = 0

    for item in review_items:
        if not isinstance(item, dict):
            continue
        if item.get("verified") is not True:
            skipped_unverified += 1
            continue
        style = item.get("text_style", "unknown")
        if style not in VALID_STYLES:
            style = "unknown"
        if text_style != "all" and style != text_style:
            skipped_style += 1
            continue
        label = item.get("raw_text")
        if not isinstance(label, str) or not label.strip():
            skipped_blank += 1
            continue
        detection_id = item.get("detection_id")
        if not isinstance(detection_id, str) or not detection_id:
            skipped_no_crop += 1
            continue
        bounds = item.get("crop_bbox")
        if not isinstance(bounds, dict):
            skipped_no_crop += 1
            continue
        try:
            x1, y1, x2, y2 = (int(bounds[key]) for key in ("x1", "y1", "x2", "y2"))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid crop_bbox for {detection_id}.") from exc
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError(f"Crop bounds for {detection_id} fall outside the source image.")

        crop_bytes = _encode_png(image[y1:y2, x1:x2])
        crop_sha = _sha256_bytes(crop_bytes)
        crop_id = _crop_id(stable_source_id, crop_sha, label.strip(), stable_writer_id, detection_id)
        image_rel = f"images/{crop_id}.png"
        entry = {
            "dataset_schema_version": DATASET_SCHEMA,
            "crop_id": crop_id,
            "image_path": image_rel,
            "text": label.strip(),
            "text_style": style,
            "verified": True,
            "source_id": stable_source_id,
            "source_sha256": source_sha,
            "source_filename": str(source_filename),
            "detection_id": detection_id,
            "writer_id": stable_writer_id,
            "crop_bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            "crop_sha256": crop_sha,
            "origin": "planline_review_export",
        }
        new_entries.append((entry, crop_bytes))

    if not new_entries:
        raise ValueError(
            "No eligible crops found. Mark a non-empty transcription as verified, "
            "set its style to handwritten, and ensure its review export contains crop_bbox data."
        )
    result = _write_entries(output_dir, new_entries)
    result.update({
        "skipped_unverified": skipped_unverified,
        "skipped_style": skipped_style,
        "skipped_blank": skipped_blank,
        "skipped_no_crop": skipped_no_crop,
    })
    return result


def _is_true(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def import_crop_csv(
    annotations_path: Path,
    output_dir: Path,
    *,
    text_style: str = "handwritten",
) -> dict[str, int]:
    """Import already-cropped images with an explicitly verified CSV label."""
    if text_style not in {"handwritten", "printed", "all"}:
        raise ValueError("text_style must be handwritten, printed or all.")
    required = {"image", "text", "source_id", "text_style", "verified"}
    new_entries: list[tuple[dict[str, Any], bytes]] = []
    skipped_unverified = 0
    skipped_style = 0
    skipped_blank = 0

    with annotations_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = required - fields
        if missing:
            raise ValueError("CSV is missing required columns: " + ", ".join(sorted(missing)))
        for row_number, row in enumerate(reader, start=2):
            if not _is_true(row.get("verified")):
                skipped_unverified += 1
                continue
            label = (row.get("text") or "").strip()
            if not label:
                skipped_blank += 1
                continue
            style = (row.get("text_style") or "").strip().lower()
            if style not in VALID_STYLES:
                raise ValueError(f"Invalid text_style on CSV row {row_number}: {style!r}")
            if text_style != "all" and style != text_style:
                skipped_style += 1
                continue
            stable_source_id = (row.get("source_id") or "").strip()
            if not stable_source_id:
                raise ValueError(f"source_id is required on CSV row {row_number}.")
            raw_image_path = Path((row.get("image") or "").strip())
            if not str(raw_image_path):
                raise ValueError(f"image is required on CSV row {row_number}.")
            crop_path = raw_image_path if raw_image_path.is_absolute() else annotations_path.parent / raw_image_path
            image = _decode_raster(crop_path)
            crop_bytes = _encode_png(image)
            crop_sha = _sha256_bytes(crop_bytes)
            writer_id = _normalise_writer(row.get("writer_id"))
            detection_id = _normalise_writer(row.get("detection_id"))
            crop_id = _crop_id(stable_source_id, crop_sha, label, writer_id, detection_id)
            source_sha = (row.get("source_sha256") or "").strip().lower() or None
            if source_sha is not None and not re.fullmatch(r"[0-9a-f]{64}", source_sha):
                raise ValueError(f"source_sha256 must be a 64-character SHA-256 hex digest on row {row_number}.")
            entry = {
                "dataset_schema_version": DATASET_SCHEMA,
                "crop_id": crop_id,
                "image_path": f"images/{crop_id}.png",
                "text": label,
                "text_style": style,
                "verified": True,
                "source_id": stable_source_id,
                "source_sha256": source_sha,
                "source_filename": (row.get("source_filename") or "").strip() or None,
                "detection_id": detection_id,
                "writer_id": writer_id,
                "crop_bbox": None,
                "crop_sha256": crop_sha,
                "origin": "manually_cropped_image",
            }
            new_entries.append((entry, crop_bytes))

    if not new_entries:
        raise ValueError(
            "No eligible CSV rows found. Include verified, non-empty labels and "
            "images with the selected text_style."
        )
    result = _write_entries(output_dir, new_entries)
    result.update({
        "skipped_unverified": skipped_unverified,
        "skipped_style": skipped_style,
        "skipped_blank": skipped_blank,
    })
    return result


def validate_dataset(dataset_dir: Path) -> dict[str, Any]:
    entries = _read_manifest(dataset_dir)
    if not entries:
        raise ValueError(f"No samples found in {dataset_dir / MANIFEST_NAME}.")
    seen: set[str] = set()
    source_hashes: dict[str, set[str]] = {}
    styles: Counter[str] = Counter()
    groups: set[str] = set()
    writers: set[str] = set()

    for index, item in enumerate(entries, start=1):
        crop_id = item.get("crop_id")
        if not isinstance(crop_id, str) or not crop_id:
            raise ValueError(f"Manifest entry {index} has no crop_id.")
        if crop_id in seen:
            raise ValueError(f"Duplicate crop_id in manifest: {crop_id}")
        seen.add(crop_id)
        if item.get("dataset_schema_version") != DATASET_SCHEMA:
            raise ValueError(f"Unsupported dataset schema in sample {crop_id}.")
        label = item.get("text")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Sample {crop_id} has an empty text label.")
        if item.get("verified") is not True:
            raise ValueError(f"Sample {crop_id} is not manually verified.")
        style = item.get("text_style")
        if style not in VALID_STYLES:
            raise ValueError(f"Sample {crop_id} has invalid text_style {style!r}.")
        source_id = item.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError(f"Sample {crop_id} has no source_id.")
        groups.add(source_id)
        writer_id = _normalise_writer(item.get("writer_id"))
        if writer_id:
            writers.add(writer_id)
        source_sha = item.get("source_sha256")
        if source_sha:
            if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
                raise ValueError(f"Sample {crop_id} has an invalid source_sha256.")
            source_hashes.setdefault(source_id, set()).add(source_sha)
        if len(source_hashes.get(source_id, set())) > 1:
            raise ValueError(f"source_id {source_id!r} maps to more than one source SHA-256.")

        image_rel = item.get("image_path")
        if not isinstance(image_rel, str) or not image_rel:
            raise ValueError(f"Sample {crop_id} has no image_path.")
        pure = PurePosixPath(image_rel)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"Sample {crop_id} has an unsafe image_path.")
        image_path = (dataset_dir / Path(*pure.parts)).resolve()
        if not image_path.is_relative_to(dataset_dir.resolve()):
            raise ValueError(f"Sample {crop_id} image path escapes the dataset directory.")
        if not image_path.is_file():
            raise ValueError(f"Image file is missing for sample {crop_id}: {image_rel}")
        image = _decode_raster(image_path)
        actual_hash = _sha256_file(image_path)
        if item.get("crop_sha256") and actual_hash != item["crop_sha256"]:
            raise ValueError(f"Image checksum mismatch for sample {crop_id}.")
        if image.shape[0] < 1 or image.shape[1] < 1:
            raise ValueError(f"Image dimensions are invalid for sample {crop_id}.")
        styles[style] += 1

    split_path = dataset_dir / SPLITS_NAME
    if split_path.exists():
        try:
            split_data = json.loads(split_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{SPLITS_NAME} is not valid JSON.") from exc
        assignments = split_data.get("assignments", {})
        current_ids = {item["crop_id"] for item in entries}
        if set(assignments) != current_ids:
            raise ValueError("splits.json is stale; regenerate splits after changing the manifest.")
        if any(split not in {"train", "validation", "test"} for split in assignments.values()):
            raise ValueError("splits.json contains an unsupported split name.")
        for component in _connected_group_ids(entries):
            component_splits = {assignments[crop_id] for crop_id in component}
            if len(component_splits) != 1:
                raise ValueError(
                    "Data leakage: samples sharing a source drawing or writer appear in multiple splits."
                )

    return {
        "samples": len(entries),
        "sources": len(groups),
        "writers": len(writers),
        "by_text_style": dict(sorted(styles.items())),
        "dataset_dir": str(dataset_dir),
        "splits_present": split_path.exists(),
    }


def _connected_group_ids(entries: list[dict[str, Any]]) -> list[list[str]]:
    """Join samples sharing a source drawing OR writer to prevent cross-split leakage."""
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    sample_keys: list[tuple[str, str]] = []
    for item in entries:
        source_key = f"source:{item['source_id']}"
        writer = _normalise_writer(item.get("writer_id"))
        find(source_key)
        if writer:
            writer_key = f"writer:{writer}"
            union(source_key, writer_key)
        sample_keys.append((item["crop_id"], source_key))

    components: dict[str, list[str]] = {}
    for crop_id, key in sample_keys:
        components.setdefault(find(key), []).append(crop_id)
    return list(components.values())


def create_grouped_splits(dataset_dir: Path, *, seed: int = 42, force: bool = False) -> dict[str, Any]:
    """Create deterministic 80/10/10 splits grouped by source drawing and writer."""
    validate_dataset(dataset_dir)
    existing_path = dataset_dir / SPLITS_NAME
    if existing_path.exists() and not force:
        raise ValueError(f"{SPLITS_NAME} already exists. Use --force to deliberately rebuild it.")
    entries = _read_manifest(dataset_dir)
    components = _connected_group_ids(entries)
    if len(components) < 3:
        raise ValueError(
            f"Need at least 3 independent source/writer groups for train, validation and test; "
            f"found {len(components)}. Keep collecting distinct drawings/writers rather than splitting crops from one plan."
        )

    rng = random.Random(seed)
    rng.shuffle(components)
    components.sort(key=len, reverse=True)
    ratios = {"train": 0.8, "validation": 0.1, "test": 0.1}
    counts = {name: 0 for name in ratios}
    assignments: dict[str, str] = {}
    group_counts = {name: 0 for name in ratios}
    for component in components:
        selected = min(ratios, key=lambda name: counts[name] / ratios[name])
        group_counts[selected] += 1
        counts[selected] += len(component)
        for crop_id in component:
            assignments[crop_id] = selected

    result = {
        "dataset_schema_version": DATASET_SCHEMA,
        "seed": seed,
        "grouping_policy": "connected components: samples sharing either source_id or writer_id stay in the same split",
        "target_ratios": ratios,
        "sample_counts": counts,
        "group_counts": group_counts,
        "assignments": assignments,
    }
    temporary = existing_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, existing_path)
    validate_dataset(dataset_dir)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare verified Planline dimension-text crops for OCR experiments."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export-review", help="Extract verified crops from a Planline review JSON and its source image.")
    export_parser.add_argument("--review", required=True, type=Path)
    export_parser.add_argument("--image", required=True, type=Path, help="Exact raster image/page used for analysis.")
    export_parser.add_argument("--output-dir", required=True, type=Path)
    export_parser.add_argument("--text-style", choices=["handwritten", "printed", "all"], default="handwritten")
    export_parser.add_argument("--source-id", help="Stable ID for this drawing; defaults to the source image SHA-256.")
    export_parser.add_argument("--writer-id", help="Pseudonymous writer ID; samples from one writer stay in one split.")

    import_parser = subparsers.add_parser("import-csv", help="Import manually cropped images with verified labels from a CSV manifest.")
    import_parser.add_argument("--annotations", required=True, type=Path)
    import_parser.add_argument("--output-dir", required=True, type=Path)
    import_parser.add_argument("--text-style", choices=["handwritten", "printed", "all"], default="handwritten")

    validate_parser = subparsers.add_parser("validate", help="Check labels, image files, checksums and split integrity.")
    validate_parser.add_argument("--dataset", required=True, type=Path)

    split_parser = subparsers.add_parser("split", help="Create source/writer-grouped train/validation/test assignments.")
    split_parser.add_argument("--dataset", required=True, type=Path)
    split_parser.add_argument("--seed", type=int, default=42)
    split_parser.add_argument("--force", action="store_true", help="Replace an existing split plan deliberately.")

    args = parser.parse_args(argv)
    try:
        if args.command == "export-review":
            result = export_review_crops(
                args.review, args.image, args.output_dir,
                text_style=args.text_style, source_id=args.source_id, writer_id=args.writer_id,
            )
        elif args.command == "import-csv":
            result = import_crop_csv(args.annotations, args.output_dir, text_style=args.text_style)
        elif args.command == "validate":
            result = validate_dataset(args.dataset)
        else:
            result = create_grouped_splits(args.dataset, seed=args.seed, force=args.force)
    except (OSError, ValueError, cv2.error) as exc:
        print(f"planline dataset: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
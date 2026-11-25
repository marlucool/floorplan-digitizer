"""Quality audit for Planline's handwritten dimension OCR datasets.

Run with: python -m planline.ocr_quality --dataset datasets/ocr/my-dataset
The audit is read-only and never changes labels, images, or split assignments.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .dataset import SPLITS_NAME, _read_manifest, validate_dataset


def audit_dataset(dataset_dir: Path) -> dict[str, Any]:
    """Return a deterministic quality report without modifying the dataset."""
    dataset_dir = dataset_dir.expanduser().resolve()
    entries = _read_manifest(dataset_dir)
    warnings: list[dict[str, str]] = []
    notes: list[str] = []
    try:
        validation = validate_dataset(dataset_dir)
        dataset_valid = True
    except (OSError, ValueError) as exc:
        validation = {"error": str(exc)}
        dataset_valid = False
        warnings.append({"code": "dataset_validation_failed", "message": str(exc)})

    def warn(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    if not entries:
        warn("empty_dataset", "No labelled crops have been collected yet.")

    labels = [str(item.get("text", "")) for item in entries]
    styles = Counter(str(item.get("text_style", "unknown")) for item in entries)
    sources = Counter(str(item.get("source_id", "")) for item in entries if item.get("source_id"))
    writers = Counter(str(item.get("writer_id", "")) for item in entries if item.get("writer_id"))
    characters = Counter("".join(labels))
    image_labels: dict[str, set[str]] = defaultdict(set)
    image_ids: dict[str, list[str]] = defaultdict(list)
    for item in entries:
        digest = str(item.get("crop_sha256", ""))
        image_labels[digest].add(str(item.get("text", "")))
        image_ids[digest].append(str(item.get("crop_id", "")))

    exact_duplicate_images = sum(max(0, len(ids) - 1) for ids in image_ids.values())
    conflicting_duplicate_images = [
        digest for digest, values in image_labels.items() if digest and len(values) > 1
    ]
    if exact_duplicate_images:
        warn("duplicate_images", f"{exact_duplicate_images} repeated crop image(s) were found.")
    if conflicting_duplicate_images:
        warn(
            "conflicting_labels",
            f"{len(conflicting_duplicate_images)} identical crop image(s) have different transcriptions.",
        )

    for item in entries:
        text = str(item.get("text", ""))
        crop_id = str(item.get("crop_id", "unknown"))
        if not text:
            warn("blank_label", f"Crop {crop_id} has an empty label.")
        if text != text.strip():
            warn("outer_whitespace", f"Crop {crop_id} has leading or trailing whitespace.")
        if len(text) < 2:
            warn("very_short_label", f"Crop {crop_id} has a label shorter than two characters.")
        if len(text) > 32:
            warn("long_label", f"Crop {crop_id} is unusually long for one dimension string.")
        if any(char.isalpha() and not char.isascii() for char in text):
            warn("non_ascii_letter", f"Crop {crop_id} contains a non-ASCII letter; check OCR charset support.")

    if len(entries) < 30:
        warn("small_dataset", f"Only {len(entries)} crops are labelled; use this for workflow testing, not reliability claims.")
    if len(sources) < 3:
        warn("few_sources", f"Only {len(sources)} drawing source(s) are represented.")
    if len(writers) < 2:
        notes.append("Writer IDs are absent or represent fewer than two writers. Evaluation will not measure generalisation to unseen handwriting authors.")

    split_summary: dict[str, Any] = {"present": False, "counts": {}, "groups": {}}
    split_path = dataset_dir / SPLITS_NAME
    if split_path.is_file():
        try:
            split_data = json.loads(split_path.read_text(encoding="utf-8"))
            if not isinstance(split_data, dict):
                raise ValueError("Split file must contain a JSON object.")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            split_data = {}
            warn("invalid_splits_file", f"Could not read split assignments: {exc}")
        assignments = split_data.get("assignments", {})
        if not isinstance(assignments, dict):
            assignments = {}
            warn("invalid_splits_file", "Split assignments must be a JSON object.")
        split_summary = {
            "present": True,
            "counts": split_data.get("sample_counts", {}),
            "groups": split_data.get("group_counts", {}),
            "seed": split_data.get("seed"),
        }
        if set(assignments) != {str(item.get("crop_id")) for item in entries}:
            warn("stale_splits", "Split assignments do not cover exactly the current dataset samples.")
        for key in ("source_id", "writer_id"):
            owners: dict[str, set[str]] = defaultdict(set)
            for item in entries:
                value = item.get(key)
                split = assignments.get(item.get("crop_id"))
                if value and split:
                    owners[str(value)].add(str(split))
            leaking = [value for value, split_set in owners.items() if len(split_set) > 1]
            if leaking:
                warn("split_leakage", f"{len(leaking)} {key} group(s) occur in more than one split.")
        if not any(value == "test" for value in assignments.values()):
            warn("missing_test_split", "No held-out test samples are assigned.")
    else:
        warn("missing_splits", "No train/validation/test split plan exists yet.")

    if len(entries) and not any(item.get("verified") is True for item in entries):
        warn("no_verified_labels", "No samples are marked as verified.")

    report = {
        "schema": "planline-ocr-quality-report/v1",
        "dataset": dataset_dir.name,
        "valid": dataset_valid,
        "sample_count": len(entries),
        "verified_count": sum(item.get("verified") is True for item in entries),
        "source_count": len(sources),
        "writer_count": len(writers),
        "text_style_counts": dict(sorted(styles.items())),
        "label_length": {
            "minimum": min(map(len, labels), default=0),
            "maximum": max(map(len, labels), default=0),
            "average": round(sum(map(len, labels)) / len(labels), 2) if labels else 0,
        },
        "character_frequencies": dict(sorted(characters.items())),
        "duplicate_crop_count": exact_duplicate_images,
        "conflicting_duplicate_image_count": len(conflicting_duplicate_images),
        "splits": split_summary,
        "validation": validation,
        "warnings": warnings,
        "notes": notes,
        "ready_for_training": not warnings and len(entries) >= 30 and split_summary["present"],
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only quality audit for a Planline OCR crop dataset.")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    parser.add_argument("--fail-on-warnings", action="store_true", help="Exit with code 1 when any warnings are found.")
    args = parser.parse_args(argv)
    try:
        report = audit_dataset(args.dataset)
        rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"planline OCR quality: {exc}", file=sys.stderr)
        return 2
    return 1 if args.fail_on_warnings and report["warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def levenshtein_distance(reference: str, hypothesis: str) -> int:
    """Return character-level edit distance using O(min(n, m)) memory."""
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for row_index, ref_char in enumerate(reference, start=1):
        current = [row_index]
        for column_index, hyp_char in enumerate(hypothesis, start=1):
            substitution_cost = 0 if ref_char == hyp_char else 1
            current.append(
                min(
                    previous[column_index] + 1,
                    current[column_index - 1] + 1,
                    previous[column_index - 1] + substitution_cost,
                )
            )
        previous = current
    return previous[-1]


def _metrics(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {
            "sample_count": 0,
            "predicted_count": 0,
            "exact_matches": 0,
            "exact_match_rate": None,
            "prediction_coverage_rate": None,
            "character_error_rate": None,
        }
    predicted = sum(bool(sample["prediction"]) for sample in samples)
    exact = sum(sample["exact_match"] for sample in samples)
    edit_distance = sum(sample["edit_distance"] for sample in samples)
    reference_chars = sum(len(sample["reference"]) for sample in samples)
    return {
        "sample_count": len(samples),
        "predicted_count": predicted,
        "exact_matches": exact,
        "exact_match_rate": exact / len(samples),
        "prediction_coverage_rate": predicted / len(samples),
        "character_error_rate": edit_distance / max(1, reference_chars),
    }


def evaluate_ocr(review: dict[str, Any], predictions: dict[str, Any]) -> dict[str, Any]:
    """Compare OCR predictions against verified manual transcriptions."""
    if not isinstance(review, dict) or not isinstance(predictions, dict):
        raise ValueError("Review and prediction inputs must be JSON objects.")
    if review.get("schema_version") != "planline-detection-review/v1":
        raise ValueError("Unsupported review schema version.")
    review_items = review.get("manual_dimension_text_review")
    if not isinstance(review_items, list):
        raise ValueError("Review JSON is missing manual_dimension_text_review.")

    prediction_items = predictions.get("predictions")
    if not isinstance(prediction_items, list):
        raise ValueError("Prediction JSON must contain a predictions array.")

    prediction_map: dict[str, dict[str, Any]] = {}
    for item in prediction_items:
        if not isinstance(item, dict):
            raise ValueError("Each prediction must be an object.")
        detection_id = item.get("detection_id")
        text = item.get("text")
        if not isinstance(detection_id, str) or not isinstance(text, str):
            raise ValueError("Each prediction needs string detection_id and text fields.")
        if detection_id in prediction_map:
            raise ValueError(f"Duplicate prediction for detection_id {detection_id!r}.")
        confidence = item.get("confidence")
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ValueError(f"Invalid confidence for detection_id {detection_id!r}.")
        prediction_map[detection_id] = item

    samples: list[dict[str, Any]] = []
    for item in review_items:
        if not isinstance(item, dict):
            continue
        if item.get("verified") is not True:
            continue
        reference = item.get("raw_text")
        detection_id = item.get("detection_id")
        if not isinstance(reference, str) or not reference.strip():
            continue
        if not isinstance(detection_id, str):
            continue
        reference = reference.strip()
        prediction_item = prediction_map.get(detection_id)
        prediction = prediction_item.get("text", "").strip() if prediction_item else ""
        distance = levenshtein_distance(reference, prediction)
        text_style = item.get("text_style", "unknown")
        if text_style not in {"unknown", "printed", "handwritten", "unclear"}:
            text_style = "unknown"
        samples.append({
            "detection_id": detection_id,
            "text_style": text_style,
            "reference": reference,
            "prediction": prediction,
            "confidence": prediction_item.get("confidence") if prediction_item else None,
            "edit_distance": distance,
            "exact_match": reference == prediction,
        })

    if not samples:
        raise ValueError("No non-empty, manually verified transcriptions were found.")

    by_style: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        style = sample["text_style"]
        by_style[str(style)].append(sample)

    return {
        "engine": predictions.get("engine", "unspecified"),
        "model": predictions.get("model", "unspecified"),
        "source_filename": (
            review.get("source", {}).get("filename")
            if isinstance(review.get("source"), dict)
            else None
        ),
        "metrics": _metrics(samples),
        "by_text_style": {style: _metrics(items) for style, items in sorted(by_style.items())},
        "samples": samples,
        "notes": [
            "Only manually verified transcriptions are included.",
            "Only leading/trailing whitespace is trimmed; punctuation, decimal separators and units are compared exactly.",
            "Missing predictions count as empty strings and contribute their full reference length to character error rate.",
            "These metrics evaluate transcription only; they do not validate dimension-to-wall association, scale or geometry.",
        ],
    }


def evaluate_dataset(
    dataset_dir: Path,
    predictions: dict[str, Any],
    *,
    split: str = "test",
) -> dict[str, Any]:
    """Score crop_id predictions against one held-out dataset split."""
    from .dataset import SPLITS_NAME, _read_manifest, validate_dataset

    if not isinstance(predictions, dict):
        raise ValueError("Prediction input must be a JSON object.")
    if split not in {"train", "validation", "test", "all"}:
        raise ValueError("split must be train, validation, test or all.")

    validate_dataset(dataset_dir)
    split_path = dataset_dir / SPLITS_NAME
    if not split_path.is_file():
        raise ValueError("No split plan exists. Run planline.dataset split before evaluating OCR.")
    try:
        split_data = json.loads(split_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Dataset splits.json is not valid JSON.") from exc
    assignments = split_data.get("assignments")
    if not isinstance(assignments, dict):
        raise ValueError("Dataset split file is missing assignments.")

    entries = _read_manifest(dataset_dir)
    known_ids = {item.get("crop_id") for item in entries}
    prediction_items = predictions.get("predictions")
    if not isinstance(prediction_items, list):
        raise ValueError("Prediction JSON must contain a predictions array.")

    prediction_map: dict[str, dict[str, Any]] = {}
    for item in prediction_items:
        if not isinstance(item, dict):
            raise ValueError("Each prediction must be an object.")
        crop_id = item.get("crop_id")
        text = item.get("text")
        if not isinstance(crop_id, str) or not isinstance(text, str):
            raise ValueError("Each dataset prediction needs string crop_id and text fields.")
        if crop_id not in known_ids:
            raise ValueError(f"Prediction references unknown crop_id {crop_id!r}.")
        if crop_id in prediction_map:
            raise ValueError(f"Duplicate prediction for crop_id {crop_id!r}.")
        confidence = item.get("confidence")
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ValueError(f"Invalid confidence for crop_id {crop_id!r}.")
        prediction_map[crop_id] = item

    selected_entries = [
        item for item in entries
        if split == "all" or assignments.get(item.get("crop_id")) == split
    ]
    samples: list[dict[str, Any]] = []
    for item in selected_entries:
        if item.get("verified") is not True:
            continue
        reference = item.get("text")
        crop_id = item.get("crop_id")
        if not isinstance(reference, str) or not reference.strip() or not isinstance(crop_id, str):
            continue
        reference = reference.strip()
        prediction_item = prediction_map.get(crop_id)
        prediction = prediction_item.get("text", "").strip() if prediction_item else ""
        distance = levenshtein_distance(reference, prediction)
        style = item.get("text_style", "unknown")
        samples.append({
            "crop_id": crop_id,
            "source_id": item.get("source_id"),
            "writer_id": item.get("writer_id"),
            "text_style": style,
            "reference": reference,
            "prediction": prediction,
            "confidence": prediction_item.get("confidence") if prediction_item else None,
            "edit_distance": distance,
            "exact_match": reference == prediction,
        })

    if not samples:
        raise ValueError(
            f"No verified, non-empty samples were found in the {split!r} split."
        )
    by_style: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        by_style[str(sample["text_style"])].append(sample)
    return {
        "engine": predictions.get("engine", "unspecified"),
        "model": predictions.get("model", "unspecified"),
        "dataset_dir": str(dataset_dir),
        "split": split,
        "metrics": _metrics(samples),
        "by_text_style": {style: _metrics(items) for style, items in sorted(by_style.items())},
        "samples": samples,
        "notes": [
            "Only manually verified dataset labels are scored.",
            "Only leading/trailing whitespace is trimmed; punctuation, decimal separators and units are compared exactly.",
            "Missing predictions count as empty strings and contribute their full reference length to character error rate.",
            "These metrics evaluate transcription only; they do not validate dimension-to-wall association, scale or geometry.",
            "The default test split is source/writer-grouped and held out from training when the dataset split plan is respected.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate OCR predictions against verified Planline dimension transcriptions."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--review", type=Path, help="Planline detection-review v1 JSON export.")
    source.add_argument("--dataset", type=Path, help="Curated Planline OCR crop dataset directory.")
    parser.add_argument("--split", choices=["train", "validation", "test", "all"], default="test",
                        help="Dataset split to score (default: held-out test). Dataset mode only.")
    parser.add_argument("--predictions", required=True, type=Path, help="JSON with engine, model and predictions array.")
    parser.add_argument("--output", type=Path, help="Optional path for the metrics JSON; defaults to stdout.")
    args = parser.parse_args(argv)

    try:
        predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
        if args.dataset is not None:
            report = evaluate_dataset(args.dataset, predictions, split=args.split)
        else:
            if args.split != "test":
                raise ValueError("--split is only used with --dataset.")
            review = json.loads(args.review.read_text(encoding="utf-8"))
            report = evaluate_ocr(review, predictions)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"planline OCR evaluation: {exc}", file=sys.stderr)
        return 2

    output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

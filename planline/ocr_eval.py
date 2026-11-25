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
        "character_error_rate": edit_distance / max(1, reference_chars),
    }


def evaluate_ocr(review: dict[str, Any], predictions: dict[str, Any]) -> dict[str, Any]:
    """Compare OCR predictions against verified manual transcriptions."""
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
            not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1
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
        samples.append({
            "detection_id": detection_id,
            "text_style": item.get("text_style", "unknown"),
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
        "source_filename": review.get("source", {}).get("filename"),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate OCR predictions against verified Planline dimension transcriptions."
    )
    parser.add_argument("--review", required=True, type=Path, help="Planline detection-review v1 JSON export.")
    parser.add_argument("--predictions", required=True, type=Path, help="JSON with engine, model and predictions array.")
    parser.add_argument("--output", type=Path, help="Optional path for the metrics JSON; defaults to stdout.")
    args = parser.parse_args(argv)

    try:
        review = json.loads(args.review.read_text(encoding="utf-8"))
        predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
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

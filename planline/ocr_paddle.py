from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np


MODEL_DEFAULT = "en_PP-OCRv5_mobile_rec"


def _result_payload(result: Any) -> dict[str, Any]:
    payload = getattr(result, "json", None)
    if callable(payload):
        payload = payload()
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(payload, dict) and isinstance(payload.get("res"), dict):
        payload = payload["res"]
    if not isinstance(payload, dict):
        return {}
    return payload


def _recognition_fields(result: Any) -> tuple[str, float | None]:
    payload = _result_payload(result)
    text = payload.get("rec_text", "")
    if not isinstance(text, str):
        text = ""
    score = payload.get("rec_score")
    if isinstance(score, bool):
        score = None
    else:
        try:
            score = float(score)
        except (TypeError, ValueError, OverflowError):
            score = None
        if score is not None and (not math.isfinite(score) or not 0 <= score <= 1):
            score = None
    return text, score


def recognize_review_crops(
    review: dict[str, Any],
    image: np.ndarray,
    recognizer: Any,
) -> tuple[list[dict[str, Any]], int]:
    """Run a supplied text recognizer on bounded crops from a review export."""
    if not isinstance(review, dict) or review.get("schema_version") != "planline-detection-review/v1":
        raise ValueError("Unsupported Planline review JSON.")
    items = review.get("manual_dimension_text_review")
    if not isinstance(items, list):
        raise ValueError("Review JSON is missing manual_dimension_text_review.")

    height, width = image.shape[:2]
    source = review.get("source")
    if isinstance(source, dict):
        expected_width = source.get("image_width_px")
        expected_height = source.get("image_height_px")
        if expected_width is not None and expected_width != width:
            raise ValueError("Source image width does not match the review export.")
        if expected_height is not None and expected_height != height:
            raise ValueError("Source image height does not match the review export.")

    predictions: list[dict[str, Any]] = []
    skipped = 0
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("detection_id"), str):
            skipped += 1
            continue
        crop_bbox = item.get("crop_bbox")
        if not isinstance(crop_bbox, dict):
            skipped += 1
            continue
        try:
            x1, y1, x2, y2 = (
                int(crop_bbox["x1"]),
                int(crop_bbox["y1"]),
                int(crop_bbox["x2"]),
                int(crop_bbox["y2"]),
            )
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if x1 < 0 or y1 < 0 or x2 > width or y2 > height or x2 <= x1 or y2 <= y1:
            skipped += 1
            continue
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            skipped += 1
            continue

        results = recognizer.predict(input=crop, batch_size=1)
        if not results:
            text, confidence = "", None
        else:
            text, confidence = _recognition_fields(results[0])
        predictions.append({
            "detection_id": item["detection_id"],
            "text": text,
            "confidence": confidence,
        })
    return predictions, skipped


def recognize_dataset_crops(
    dataset_dir: Path,
    recognizer: Any,
) -> tuple[list[dict[str, Any]], int]:
    """Recognise every validated crop in a curated Planline dataset."""
    from .dataset import _read_manifest, validate_dataset

    validate_dataset(dataset_dir)
    entries = _read_manifest(dataset_dir)
    predictions: list[dict[str, Any]] = []
    skipped = 0
    for item in entries:
        crop_id = item.get("crop_id")
        image_rel = item.get("image_path")
        if not isinstance(crop_id, str) or not isinstance(image_rel, str):
            skipped += 1
            continue
        image_path = (dataset_dir / image_rel).resolve()
        if not image_path.is_relative_to(dataset_dir.resolve()):
            raise ValueError(f"Crop image path escapes dataset directory: {image_rel}")
        encoded = np.fromfile(str(image_path), dtype=np.uint8)
        crop = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if crop is None:
            raise ValueError(f"Could not decode dataset crop: {image_path}")
        results = recognizer.predict(input=crop, batch_size=1)
        if not results:
            text, confidence = "", None
        else:
            text, confidence = _recognition_fields(results[0])
        predictions.append({
            "crop_id": crop_id,
            "text": text,
            "confidence": confidence,
        })
    return predictions, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run optional PaddleOCR text recognition on Planline dimension crops."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--review", type=Path, help="Planline review JSON export.")
    source.add_argument("--dataset", type=Path, help="Curated Planline OCR crop dataset directory.")
    parser.add_argument("--image", type=Path, help="Exact raster image used for the review (required with --review).")
    parser.add_argument("--output", required=True, type=Path, help="Output predictions JSON path.")
    parser.add_argument("--model", default=MODEL_DEFAULT, help=f"PaddleOCR recognition model (default: {MODEL_DEFAULT}).")
    parser.add_argument("--device", default="cpu", help="Paddle device, for example cpu or gpu:0 (default: cpu).")
    args = parser.parse_args(argv)

    try:
        if args.review is not None and args.image is None:
            raise ValueError("--image is required when using --review.")
        if args.dataset is not None and args.image is not None:
            raise ValueError("--image is only used with --review.")

        from paddleocr import TextRecognition

        recognizer = TextRecognition(model_name=args.model, device=args.device)
        if args.dataset is not None:
            predictions, skipped = recognize_dataset_crops(args.dataset, recognizer)
            input_kind = "planline-handwriting-crops/v1"
            source_info = {"dataset_dir": str(args.dataset)}
        else:
            review = json.loads(args.review.read_text(encoding="utf-8"))
            encoded = np.fromfile(str(args.image), dtype=np.uint8)
            image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"Could not decode raster image: {args.image}")
            predictions, skipped = recognize_review_crops(review, image, recognizer)
            input_kind = "planline-detection-review/v1"
            source_info = {
                "source_filename": review.get("source", {}).get("filename")
                if isinstance(review.get("source"), dict)
                else None
            }
        output = {
            "engine": "PaddleOCR",
            "model": args.model,
            "input_kind": input_kind,
            **source_info,
            "predictions": predictions,
            "skipped_crops": skipped,
            "notes": [
                "Raw recognizer output only; no unit parsing, correction or geometry inference is performed.",
                "All predictions are unverified and must be checked by a person.",
            ],
        }
        args.output.write_text(
            json.dumps(output, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except ImportError as exc:
        print(
            "PaddleOCR is optional. Install a compatible PaddlePaddle package and "
            "requirements-ocr-paddle.txt before running this command.",
            file=sys.stderr,
        )
        return 2
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(f"planline PaddleOCR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

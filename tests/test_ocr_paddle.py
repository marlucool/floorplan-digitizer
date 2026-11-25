from __future__ import annotations

import csv
import json

import numpy as np
import pytest
from PIL import Image

from planline.dataset import import_crop_csv
from planline.ocr_paddle import recognize_dataset_crops, recognize_review_crops


class FakeResult:
    json = {"res": {"rec_text": "4200", "rec_score": 0.91}}


class FakeRecognizer:
    def __init__(self) -> None:
        self.seen_shapes: list[tuple[int, ...]] = []

    def predict(self, *, input: np.ndarray, batch_size: int):
        assert batch_size == 1
        self.seen_shapes.append(input.shape)
        return [FakeResult()]


def _review() -> dict:
    return {
        "schema_version": "planline-detection-review/v1",
        "source": {"image_width_px": 100, "image_height_px": 80, "filename": "plan.png"},
        "manual_dimension_text_review": [
            {
                "detection_id": "det-001",
                "crop_bbox": {
                    "x1": 10, "y1": 12, "x2": 40, "y2": 32,
                    "width": 30, "height": 20,
                },
            },
            {"detection_id": "det-002", "crop_bbox": None},
            {
                "detection_id": "det-003",
                "crop_bbox": {
                    "x1": 90, "y1": 10, "x2": 120, "y2": 30,
                    "width": 30, "height": 20,
                },
            },
        ],
    }


def test_recognize_review_crops_returns_raw_text_and_score() -> None:
    image = np.zeros((80, 100, 3), dtype=np.uint8)
    recognizer = FakeRecognizer()

    predictions, skipped = recognize_review_crops(_review(), image, recognizer)

    assert predictions == [
        {"detection_id": "det-001", "text": "4200", "confidence": 0.91}
    ]
    assert skipped == 2
    assert recognizer.seen_shapes == [(20, 30, 3)]


def test_recognize_review_crops_rejects_source_dimension_mismatch() -> None:
    review = _review()
    image = np.zeros((79, 100, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="height does not match"):
        recognize_review_crops(review, image, FakeRecognizer())


def test_recognize_review_crops_handles_empty_recognizer_result() -> None:
    class EmptyRecognizer:
        def predict(self, *, input: np.ndarray, batch_size: int):
            return []

    review = _review()
    review["manual_dimension_text_review"] = [review["manual_dimension_text_review"][0]]
    image = np.zeros((80, 100, 3), dtype=np.uint8)
    predictions, skipped = recognize_review_crops(review, image, EmptyRecognizer())

    assert predictions == [
        {"detection_id": "det-001", "text": "", "confidence": None}
    ]
    assert skipped == 0


def test_recognize_dataset_crops_uses_crop_ids_and_validated_images(tmp_path) -> None:
    crop_path = tmp_path / "handwritten.png"
    Image.new("RGB", (24, 12), "white").save(crop_path)
    annotations = tmp_path / "labels.csv"
    with annotations.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["image", "text", "source_id", "writer_id", "text_style", "verified"],
        )
        writer.writeheader()
        writer.writerow({
            "image": crop_path.name,
            "text": "4,200 mm",
            "source_id": "plan-A",
            "writer_id": "writer-01",
            "text_style": "handwritten",
            "verified": "true",
        })

    dataset_dir = tmp_path / "dataset"
    import_crop_csv(annotations, dataset_dir)
    manifest_entry = json.loads((dataset_dir / "manifest.jsonl").read_text().splitlines()[0])
    recognizer = FakeRecognizer()

    predictions, skipped = recognize_dataset_crops(dataset_dir, recognizer)

    assert predictions == [{
        "crop_id": manifest_entry["crop_id"],
        "text": "4200",
        "confidence": 0.91,
    }]
    assert skipped == 0
    assert recognizer.seen_shapes == [(12, 24, 3)]

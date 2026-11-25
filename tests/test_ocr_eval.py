from __future__ import annotations

import json

import pytest

from planline.ocr_eval import evaluate_ocr, levenshtein_distance, main


def _review() -> dict:
    return {
        "schema_version": "planline-detection-review/v1",
        "source": {"filename": "archive-plan.png"},
        "manual_dimension_text_review": [
            {
                "detection_id": "det-001",
                "raw_text": " 4200 ",
                "text_style": "handwritten",
                "verified": True,
            },
            {
                "detection_id": "det-002",
                "raw_text": "2500",
                "text_style": "printed",
                "verified": True,
            },
            {
                "detection_id": "det-003",
                "raw_text": "3.5",
                "text_style": "handwritten",
                "verified": True,
            },
            {
                "detection_id": "det-004",
                "raw_text": "9999",
                "text_style": "printed",
                "verified": False,
            },
        ],
    }


def test_levenshtein_distance_counts_character_edits() -> None:
    assert levenshtein_distance("4200", "4200") == 0
    assert levenshtein_distance("2500", "250O") == 1
    assert levenshtein_distance("3.5", "") == 3
    assert levenshtein_distance("", "abc") == 3


def test_evaluate_ocr_uses_only_verified_manual_labels_and_groups_by_style() -> None:
    report = evaluate_ocr(
        _review(),
        {
            "engine": "example-ocr",
            "model": "example-model",
            "predictions": [
                {"detection_id": "det-001", "text": "4200 ", "confidence": 0.9},
                {"detection_id": "det-002", "text": "250O", "confidence": 0.8},
            ],
        },
    )

    assert report["source_filename"] == "archive-plan.png"
    assert report["metrics"]["sample_count"] == 3
    assert report["metrics"]["predicted_count"] == 2
    assert report["metrics"]["exact_matches"] == 1
    assert report["metrics"]["exact_match_rate"] == pytest.approx(1 / 3)
    assert report["metrics"]["character_error_rate"] == pytest.approx(4 / 11)
    assert report["by_text_style"]["handwritten"]["sample_count"] == 2
    assert report["by_text_style"]["handwritten"]["character_error_rate"] == pytest.approx(3 / 7)
    assert report["by_text_style"]["printed"]["character_error_rate"] == pytest.approx(1 / 4)
    assert all(sample["detection_id"] != "det-004" for sample in report["samples"])


def test_evaluate_ocr_rejects_duplicate_predictions() -> None:
    with pytest.raises(ValueError, match="Duplicate prediction"):
        evaluate_ocr(
            _review(),
            {
                "predictions": [
                    {"detection_id": "det-001", "text": "4200"},
                    {"detection_id": "det-001", "text": "4200"},
                ]
            },
        )


def test_evaluate_ocr_requires_verified_transcriptions() -> None:
    review = _review()
    for item in review["manual_dimension_text_review"]:
        item["verified"] = False
    with pytest.raises(ValueError, match="No non-empty"):
        evaluate_ocr(review, {"predictions": []})



def test_ocr_evaluation_cli_writes_metrics_json(tmp_path) -> None:
    review_path = tmp_path / "review.json"
    predictions_path = tmp_path / "predictions.json"
    output_path = tmp_path / "metrics.json"
    review_path.write_text(json.dumps(_review()), encoding="utf-8")
    predictions_path.write_text(
        json.dumps({"engine": "test-engine", "predictions": [
            {"detection_id": "det-001", "text": "4200"},
            {"detection_id": "det-002", "text": "2500"},
            {"detection_id": "det-003", "text": "3.5"}
        ]}),
        encoding="utf-8",
    )

    exit_code = main([
        "--review", str(review_path),
        "--predictions", str(predictions_path),
        "--output", str(output_path),
    ])

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["engine"] == "test-engine"
    assert report["metrics"]["exact_match_rate"] == 1.0

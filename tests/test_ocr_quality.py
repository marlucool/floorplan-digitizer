from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image

from planline.dataset import create_grouped_splits, import_crop_csv
from planline.ocr_quality import audit_dataset


def _make_dataset(tmp_path: Path) -> Path:
    crops = tmp_path / "crops"
    crops.mkdir()
    rows = []
    for index, (source, writer, label) in enumerate([
        ("plan-a", "writer-a", "4,200 mm"),
        ("plan-b", "writer-b", "2750"),
        ("plan-c", "writer-c", "3.65 m"),
        ("plan-a", "writer-a", "4200"),
    ]):
        image_path = crops / f"crop-{index}.png"
        Image.new("RGB", (80, 24), "white").save(image_path)
        rows.append({
            "image": str(image_path),
            "text": label,
            "source_id": source,
            "writer_id": writer,
            "text_style": "handwritten",
            "verified": "true",
        })
    csv_path = tmp_path / "labels.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    dataset = tmp_path / "dataset"
    import_crop_csv(csv_path, dataset)
    create_grouped_splits(dataset, seed=42)
    return dataset


def test_audit_reports_valid_dataset_and_grouped_splits(tmp_path: Path) -> None:
    report = audit_dataset(_make_dataset(tmp_path))
    assert report["valid"] is True
    assert report["sample_count"] == 4
    assert report["verified_count"] == 4
    assert report["splits"]["present"] is True
    assert "4" in report["character_frequencies"]
    assert any(item["code"] == "small_dataset" for item in report["warnings"])


def test_audit_warns_when_split_plan_is_missing(tmp_path: Path) -> None:
    dataset = _make_dataset(tmp_path)
    (dataset / "splits.json").unlink()
    report = audit_dataset(dataset)
    assert any(item["code"] == "missing_splits" for item in report["warnings"])
    assert report["ready_for_training"] is False



def test_audit_reports_split_leakage_instead_of_aborting(tmp_path: Path) -> None:
    import json

    dataset = _make_dataset(tmp_path)
    manifest = [json.loads(line) for line in (dataset / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    split_path = dataset / "splits.json"
    split_data = json.loads(split_path.read_text(encoding="utf-8"))
    first, second = manifest[0], manifest[3]
    original_split = split_data["assignments"][first["crop_id"]]
    split_data["assignments"][second["crop_id"]] = "test" if original_split != "test" else "train"
    split_path.write_text(json.dumps(split_data), encoding="utf-8")

    report = audit_dataset(dataset)
    assert report["valid"] is False
    assert any(item["code"] == "split_leakage" for item in report["warnings"])
    assert any(item["code"] == "dataset_validation_failed" for item in report["warnings"])

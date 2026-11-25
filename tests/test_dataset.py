from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from planline.dataset import (
    create_grouped_splits,
    export_review_crops,
    import_crop_csv,
    validate_dataset,
)


def _write_source(path: Path, size: tuple[int, int] = (40, 30)) -> None:
    image = Image.new("RGB", size, "white")
    for x in range(5, 15):
        for y in range(6, 14):
            image.putpixel((x, y), (255, 0, 0))
    image.save(path)


def _review(width: int = 40, height: int = 30) -> dict:
    return {
        "schema_version": "planline-detection-review/v1",
        "source": {
            "filename": "survey.png",
            "image_width_px": width,
            "image_height_px": height,
        },
        "manual_dimension_text_review": [
            {
                "detection_id": "det-001",
                "raw_text": " 4,200 mm ",
                "text_style": "handwritten",
                "verified": True,
                "crop_bbox": {"x1": 4, "y1": 5, "x2": 16, "y2": 15},
            },
            {
                "detection_id": "det-002",
                "raw_text": "2500",
                "text_style": "handwritten",
                "verified": False,
                "crop_bbox": {"x1": 1, "y1": 1, "x2": 10, "y2": 10},
            },
            {
                "detection_id": "det-003",
                "raw_text": "3000",
                "text_style": "printed",
                "verified": True,
                "crop_bbox": {"x1": 1, "y1": 1, "x2": 10, "y2": 10},
            },
            {
                "detection_id": "det-004",
                "raw_text": "",
                "text_style": "handwritten",
                "verified": True,
                "crop_bbox": {"x1": 1, "y1": 1, "x2": 10, "y2": 10},
            },
        ],
    }


def test_export_review_uses_only_verified_handwritten_full_strings(tmp_path: Path) -> None:
    source = tmp_path / "survey.png"
    review_path = tmp_path / "review.json"
    output = tmp_path / "dataset"
    _write_source(source)
    review_path.write_text(json.dumps(_review()), encoding="utf-8")

    result = export_review_crops(
        review_path, source, output, writer_id="writer-A"
    )

    assert result["added"] == 1
    assert result["skipped_unverified"] == 1
    assert result["skipped_style"] == 1
    assert result["skipped_blank"] == 1
    rows = [json.loads(line) for line in (output / "manifest.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["text"] == "4,200 mm"
    assert rows[0]["writer_id"] == "writer-A"
    assert rows[0]["source_id"].startswith("sha256:")
    assert rows[0]["origin"] == "planline_review_export"
    assert (output / rows[0]["image_path"]).is_file()
    assert validate_dataset(output)["samples"] == 1


def test_export_review_requires_exact_source_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "survey.png"
    review_path = tmp_path / "review.json"
    _write_source(source)
    review_path.write_text(json.dumps(_review(width=99)), encoding="utf-8")

    with pytest.raises(ValueError, match="dimensions do not match"):
        export_review_crops(review_path, source, tmp_path / "dataset")


def test_export_review_rejects_out_of_bounds_crop(tmp_path: Path) -> None:
    source = tmp_path / "survey.png"
    review_path = tmp_path / "review.json"
    payload = _review()
    payload["manual_dimension_text_review"][0]["crop_bbox"] = {
        "x1": 1, "y1": 1, "x2": 90, "y2": 90
    }
    _write_source(source)
    review_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="fall outside"):
        export_review_crops(review_path, source, tmp_path / "dataset")


def test_review_export_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "survey.png"
    review_path = tmp_path / "review.json"
    output = tmp_path / "dataset"
    _write_source(source)
    review_path.write_text(json.dumps(_review()), encoding="utf-8")

    first = export_review_crops(review_path, source, output)
    second = export_review_crops(review_path, source, output)

    assert first["added"] == 1
    assert second["added"] == 0
    assert second["skipped_duplicates"] == 1
    assert len((output / "manifest.jsonl").read_text().splitlines()) == 1


def test_import_csv_accepts_manual_crops_and_skips_unverified(tmp_path: Path) -> None:
    crop = tmp_path / "crop.png"
    Image.new("RGB", (18, 12), "white").save(crop)
    csv_path = tmp_path / "labels.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["image", "text", "source_id", "writer_id", "text_style", "verified"],
        )
        writer.writeheader()
        writer.writerow({
            "image": "crop.png", "text": "3.75m", "source_id": "sheet-01",
            "writer_id": "drafter-1", "text_style": "handwritten", "verified": "true",
        })
        writer.writerow({
            "image": "crop.png", "text": "9999", "source_id": "sheet-01",
            "writer_id": "drafter-1", "text_style": "handwritten", "verified": "false",
        })

    output = tmp_path / "dataset"
    result = import_crop_csv(csv_path, output)
    rows = [json.loads(line) for line in (output / "manifest.jsonl").read_text().splitlines()]

    assert result["added"] == 1
    assert result["skipped_unverified"] == 1
    assert rows[0]["text"] == "3.75m"
    assert rows[0]["source_id"] == "sheet-01"
    assert rows[0]["origin"] == "manually_cropped_image"
    assert validate_dataset(output)["samples"] == 1


def test_grouped_splits_keep_both_sources_and_writers_together(tmp_path: Path) -> None:
    crop = tmp_path / "crop.png"
    Image.new("RGB", (12, 8), "white").save(crop)
    csv_path = tmp_path / "labels.csv"
    rows = [
        ("sheet-A", "writer-1", "4000"),
        ("sheet-B", "writer-1", "4200"),
        ("sheet-C", "writer-2", "3100"),
        ("sheet-D", "writer-3", "2900"),
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["image", "text", "source_id", "writer_id", "text_style", "verified"]
        )
        writer.writeheader()
        for source_id, writer_id, text in rows:
            writer.writerow({
                "image": "crop.png", "text": text, "source_id": source_id,
                "writer_id": writer_id, "text_style": "handwritten", "verified": "true",
            })

    output = tmp_path / "dataset"
    import_crop_csv(csv_path, output)
    split_data = create_grouped_splits(output, seed=7)
    entries = [json.loads(line) for line in (output / "manifest.jsonl").read_text().splitlines()]
    assignments = split_data["assignments"]
    writer1_splits = {assignments[item["crop_id"]] for item in entries if item["writer_id"] == "writer-1"}

    assert len(writer1_splits) == 1
    assert set(split_data["sample_counts"]) == {"train", "validation", "test"}
    assert sum(split_data["sample_counts"].values()) == 4
    assert validate_dataset(output)["splits_present"] is True


def test_split_refuses_too_few_independent_sources(tmp_path: Path) -> None:
    crop = tmp_path / "crop.png"
    Image.new("RGB", (12, 8), "white").save(crop)
    csv_path = tmp_path / "labels.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["image", "text", "source_id", "text_style", "verified"]
        )
        writer.writeheader()
        for index in range(2):
            writer.writerow({
                "image": "crop.png", "text": str(1000 + index),
                "source_id": f"sheet-{index}", "text_style": "handwritten", "verified": "true",
            })
    output = tmp_path / "dataset"
    import_crop_csv(csv_path, output)

    with pytest.raises(ValueError, match="at least 3 independent"):
        create_grouped_splits(output)


def test_same_source_is_grouped_together_even_with_different_writer_ids(tmp_path: Path) -> None:
    crop = tmp_path / "crop.png"
    Image.new("RGB", (12, 8), "white").save(crop)
    csv_path = tmp_path / "labels.csv"
    rows = [
        ("sheet-A", "writer-1", "4000"),
        ("sheet-A", "writer-2", "4200"),
        ("sheet-B", "writer-3", "3100"),
        ("sheet-C", "writer-4", "2900"),
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["image", "text", "source_id", "writer_id", "text_style", "verified"]
        )
        writer.writeheader()
        for source_id, writer_id, text in rows:
            writer.writerow({
                "image": "crop.png", "text": text, "source_id": source_id,
                "writer_id": writer_id, "text_style": "handwritten", "verified": "true",
            })

    output = tmp_path / "dataset"
    import_crop_csv(csv_path, output)
    split_data = create_grouped_splits(output, seed=13)
    entries = [json.loads(line) for line in (output / "manifest.jsonl").read_text().splitlines()]
    assignments = split_data["assignments"]
    same_source_splits = {
        assignments[item["crop_id"]] for item in entries if item["source_id"] == "sheet-A"
    }

    assert len(same_source_splits) == 1
    assert validate_dataset(output)["splits_present"] is True


def test_adding_samples_invalidates_previous_split_file(tmp_path: Path) -> None:
    crop = tmp_path / "crop.png"
    Image.new("RGB", (12, 8), "white").save(crop)
    csv_path = tmp_path / "labels.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["image", "text", "source_id", "text_style", "verified"]
        )
        writer.writeheader()
        for index in range(3):
            writer.writerow({
                "image": "crop.png", "text": str(1000 + index),
                "source_id": f"sheet-{index}", "text_style": "handwritten", "verified": "true",
            })

    output = tmp_path / "dataset"
    import_crop_csv(csv_path, output)
    create_grouped_splits(output)
    assert (output / "splits.json").exists()

    next_csv = tmp_path / "next.csv"
    with next_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["image", "text", "source_id", "text_style", "verified"]
        )
        writer.writeheader()
        writer.writerow({
            "image": "crop.png", "text": "7000", "source_id": "sheet-4",
            "text_style": "handwritten", "verified": "true",
        })
    import_crop_csv(next_csv, output)
    assert not (output / "splits.json").exists()



def _three_group_dataset(tmp_path: Path) -> Path:
    crop = tmp_path / "crop.png"
    Image.new("RGB", (12, 8), "white").save(crop)
    csv_path = tmp_path / "labels.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["image", "text", "source_id", "text_style", "verified"]
        )
        writer.writeheader()
        for index in range(3):
            writer.writerow({
                "image": "crop.png",
                "text": str(1000 + index),
                "source_id": f"sheet-{index}",
                "text_style": "handwritten",
                "verified": "true",
            })
    dataset_dir = tmp_path / "dataset"
    import_crop_csv(csv_path, dataset_dir)
    create_grouped_splits(dataset_dir)
    return dataset_dir


def test_force_rebuild_recovers_stale_split_assignments(tmp_path: Path) -> None:
    dataset_dir = _three_group_dataset(tmp_path)
    split_path = dataset_dir / "splits.json"
    split_data = json.loads(split_path.read_text(encoding="utf-8"))
    split_data["assignments"]["deleted-crop"] = "test"
    split_path.write_text(json.dumps(split_data), encoding="utf-8")

    with pytest.raises(ValueError, match="stale"):
        validate_dataset(dataset_dir)

    rebuilt = create_grouped_splits(dataset_dir, seed=17, force=True)
    current_ids = {
        json.loads(line)["crop_id"]
        for line in (dataset_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert set(rebuilt["assignments"]) == current_ids
    assert validate_dataset(dataset_dir)["splits_present"] is True


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("[]", "JSON object"),
        ('{"assignments": []}', "assignments object"),
    ],
)
def test_split_validation_rejects_malformed_metadata(
    tmp_path: Path, payload: str, message: str
) -> None:
    dataset_dir = _three_group_dataset(tmp_path)
    (dataset_dir / "splits.json").write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validate_dataset(dataset_dir)


def test_split_validation_requires_train_validation_and_test_samples(tmp_path: Path) -> None:
    dataset_dir = _three_group_dataset(tmp_path)
    split_path = dataset_dir / "splits.json"
    split_data = json.loads(split_path.read_text(encoding="utf-8"))
    split_data["assignments"] = {
        crop_id: "train" for crop_id in split_data["assignments"]
    }
    split_path.write_text(json.dumps(split_data), encoding="utf-8")

    with pytest.raises(ValueError, match="at least one sample to train, validation and test"):
        validate_dataset(dataset_dir)

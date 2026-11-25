from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from planline.dataset import (
    add_crop_sample,
    create_grouped_splits,
    delete_crop_sample,
    export_paddle_rec_dataset,
    update_crop_sample,
    validate_dataset,
)


def _png_bytes(color: str = "white") -> bytes:
    import io
    stream = io.BytesIO()
    Image.new("RGB", (24, 12), color).save(stream, format="PNG")
    return stream.getvalue()


def test_desktop_crop_add_edit_delete_and_split_invalidation(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    for index, writer in enumerate(("writer-a", "writer-b", "writer-c")):
        result = add_crop_sample(
            dataset, _png_bytes(), "crop.png", text=f"{index + 1},200 mm",
            source_id=f"plan-{index}", writer_id=writer,
        )
        assert result["added"] == 1
    split = create_grouped_splits(dataset, seed=7)
    assert set(split["sample_counts"]) == {"train", "validation", "test"}
    first = json.loads((dataset / "manifest.jsonl").read_text().splitlines()[0])
    update_crop_sample(
        dataset, first["crop_id"], text="4,200 mm", source_id="plan-0",
        writer_id="writer-a", text_style="handwritten",
    )
    assert not (dataset / "splits.json").exists()
    assert validate_dataset(dataset)["samples"] == 3
    delete_crop_sample(dataset, first["crop_id"])
    assert validate_dataset(dataset)["samples"] == 2
    assert not (dataset / "splits.json").exists()


def test_paddle_export_excludes_held_out_test_samples(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    for index, writer in enumerate(("writer-a", "writer-b", "writer-c")):
        add_crop_sample(
            dataset, _png_bytes("white"), "crop.png", text=f"{index + 1}000",
            source_id=f"plan-{index}", writer_id=writer,
        )
    split = create_grouped_splits(dataset, seed=12)
    output = tmp_path / "training"
    exported = export_paddle_rec_dataset(dataset, output)
    assert exported["training_samples"] == split["sample_counts"]["train"]
    assert exported["validation_samples"] == split["sample_counts"]["validation"]
    assert exported["test_samples"] == split["sample_counts"]["test"]
    training_ids = set((output / "train_list.txt").read_text().splitlines())
    validation_ids = set((output / "val_list.txt").read_text().splitlines())
    assert len(training_ids) + len(validation_ids) == exported["training_samples"] + exported["validation_samples"]
    assert all(line.split("\t", 1)[1] != "" for line in training_ids | validation_ids)


def test_desktop_crop_rejects_empty_or_invalid_labels(tmp_path: Path) -> None:
    import pytest
    with pytest.raises(ValueError, match="exact text"):
        add_crop_sample(tmp_path / "dataset", _png_bytes(), "crop.png", text=" ", source_id="plan-1")
    with pytest.raises(ValueError, match="source_id"):
        add_crop_sample(tmp_path / "dataset", _png_bytes(), "crop.png", text="4200", source_id="")

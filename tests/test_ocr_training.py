from __future__ import annotations

from pathlib import Path

import pytest

from planline.ocr_training import build_training_command


def test_build_training_command_overrides_data_checkpoint_and_small_batch(tmp_path: Path) -> None:
    source = tmp_path / "PaddleOCR"
    (source / "tools").mkdir(parents=True)
    (source / "tools" / "train.py").write_text("# training entrypoint")
    config = source / "configs" / "rec.yml"
    config.parent.mkdir(parents=True)
    config.write_text("Global: {}")
    checkpoint = tmp_path / "mobile.pdparams"
    checkpoint.write_bytes(b"test")
    data = tmp_path / "train data"
    data.mkdir()
    (data / "train_list.txt").write_text("images/a.png\t4200\n")
    (data / "val_list.txt").write_text("images/b.png\t3000\n")

    command = build_training_command(
        source, config, checkpoint, data, tmp_path / "output",
        epochs=12, batch_size=4, use_gpu=True,
    )

    assert command[1] == str((source / "tools" / "train.py").resolve())
    assert "Global.epoch_num=12" in command
    assert "Train.sampler.first_bs=4" in command
    assert any(item.startswith("Train.dataset.data_dir=") and "train data" in item for item in command)
    assert any(item.startswith("Global.pretrained_model=") and "mobile.pdparams" in item for item in command)


def test_build_training_command_rejects_unsafe_settings(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="epochs"):
        build_training_command(tmp_path, tmp_path / "config", tmp_path / "weights", tmp_path, tmp_path, epochs=0)
    with pytest.raises(ValueError, match="batch_size"):
        build_training_command(tmp_path, tmp_path / "config", tmp_path / "weights", tmp_path, tmp_path, batch_size=3)

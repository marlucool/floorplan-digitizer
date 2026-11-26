from __future__ import annotations

import zipfile
from pathlib import Path

from planline import ocr_training_assets


def test_training_asset_status_requires_source_config_and_nonempty_weights(tmp_path: Path) -> None:
    missing = ocr_training_assets.training_assets_status("mobile", root=tmp_path)
    assert missing["ready"] is False
    assert set(missing["missing"]) == {"source", "weights"}

    source = tmp_path / f"PaddleOCR-{ocr_training_assets.PADDLEOCR_VERSION}"
    (source / "tools").mkdir(parents=True)
    (source / "configs" / "rec" / "PP-OCRv5").mkdir(parents=True)
    (source / "tools" / "train.py").write_text("# training entry point", encoding="utf-8")
    (source / "configs" / "rec" / "PP-OCRv5" / "PP-OCRv5_mobile_rec.yml").write_text(
        "Global:\n  use_gpu: true\n", encoding="utf-8"
    )
    weights = tmp_path / "weights" / "PP-OCRv5_mobile_rec_pretrained.pdparams"
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"x" * ocr_training_assets._MIN_ASSET_BYTES)

    ready = ocr_training_assets.training_assets_status("mobile", root=tmp_path)
    assert ready["ready"] is True
    assert ready["missing"] == []
    assert Path(ready["config_path"]).is_file()
    assert Path(ready["pretrained_model"]).stat().st_size >= ocr_training_assets._MIN_ASSET_BYTES


def test_ensure_training_assets_downloads_pinned_source_and_variant_weights(
    tmp_path: Path, monkeypatch
) -> None:
    downloads: list[str] = []

    def fake_download(url: str, destination: Path, *, max_bytes: int) -> str:
        if destination.is_file() and ocr_training_assets._MIN_ASSET_BYTES <= destination.stat().st_size <= max_bytes:
            return "cached-sha256"
        downloads.append(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith(".zip"):
            with zipfile.ZipFile(destination, "w") as archive:
                archive.writestr(
                    f"PaddleOCR-{ocr_training_assets.PADDLEOCR_VERSION}/tools/train.py",
                    "print('train')",
                )
                archive.writestr(
                    f"PaddleOCR-{ocr_training_assets.PADDLEOCR_VERSION}/configs/rec/PP-OCRv5/PP-OCRv5_server_rec.yml",
                    "Global:\n  use_gpu: true\n",
                )
                archive.writestr(
                    f"PaddleOCR-{ocr_training_assets.PADDLEOCR_VERSION}/../escape.txt",
                    "must not escape",
                )
                archive.writestr(
                    f"PaddleOCR-{ocr_training_assets.PADDLEOCR_VERSION}/README.md",
                    "x" * ocr_training_assets._MIN_ASSET_BYTES,
                )
        else:
            destination.write_bytes(b"w" * ocr_training_assets._MIN_ASSET_BYTES)
        return "test-sha256"

    monkeypatch.setattr(ocr_training_assets, "_download_atomic", fake_download)
    result = ocr_training_assets.ensure_training_assets("server", root=tmp_path)

    assert result["ready"] is True
    assert result["model_variant"] == "server"
    assert result["source_version"] == "v3.3.1"
    assert len(downloads) == 2
    assert downloads[0] == ocr_training_assets.SOURCE_URL
    assert downloads[1].endswith("PP-OCRv5_server_rec_pretrained.pdparams")
    assert not (tmp_path.parent / "escape.txt").exists()
    assert (tmp_path / "asset_manifest.json").is_file()

    # The second call reuses the verified local files instead of downloading again.
    again = ocr_training_assets.ensure_training_assets("server", root=tmp_path)
    assert again["ready"] is True
    assert len(downloads) == 2


def test_training_asset_variant_is_validated(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="mobile or server"):
        ocr_training_assets.training_assets_status("invalid", root=tmp_path)

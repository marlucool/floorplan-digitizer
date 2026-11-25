from pathlib import Path

from planline.ocr_studio_api import _get_ocr_dataset_root


def test_installed_build_uses_external_user_data_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("PLANLINE_DATA_DIR", str(tmp_path))

    assert _get_ocr_dataset_root() == (tmp_path / "ocr").resolve()


def test_source_checkout_keeps_repository_local_dataset_directory(monkeypatch):
    monkeypatch.delenv("PLANLINE_DATA_DIR", raising=False)

    expected = Path(__file__).resolve().parents[1] / "datasets" / "ocr"
    assert _get_ocr_dataset_root() == expected

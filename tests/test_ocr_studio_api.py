from __future__ import annotations

import io
import json
import re
import sys
import types
import zipfile
from pathlib import Path

import numpy as np
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from planline import ocr_studio_api


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (28, 16), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_local_ocr_studio_dataset_and_annotation_routes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ocr_studio_api, "OCR_DATASET_ROOT", tmp_path / "ocr")
    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    client = TestClient(app)

    created = client.post("/api/ocr/datasets", json={"name": "test handwriting"})
    assert created.status_code == 201
    dataset_id = created.json()["dataset_id"]
    for index, writer in enumerate(("writer-a", "writer-b", "writer-c")):
        response = client.post(
            f"/api/ocr/datasets/{dataset_id}/samples",
            files={"file": ("crop.png", _png(), "image/png")},
            data={"text": f"{index + 1}200 mm", "source_id": f"plan-{index}", "writer_id": writer,
                  "text_style": "handwritten", "verified": "true"},
        )
        assert response.status_code == 201, response.text
    payload = client.get(f"/api/ocr/datasets/{dataset_id}").json()
    assert payload["summary"]["samples"] == 3
    crop_id = payload["samples"][0]["crop_id"]
    assert client.get(f"/api/ocr/datasets/{dataset_id}/samples/{crop_id}/image").status_code == 200

    splits = client.post(f"/api/ocr/datasets/{dataset_id}/splits", json={"seed": 42, "force": True})
    assert splits.status_code == 200, splits.text
    assert set(splits.json()["splits"]["sample_counts"]) == {"train", "validation", "test"}
    quality = client.get(f"/api/ocr/datasets/{dataset_id}/quality")
    assert quality.status_code == 200, quality.text
    assert quality.json()["sample_count"] == 3
    assert quality.json()["splits"]["present"] is True
    assert "character_frequencies" in quality.json()

    edited = client.patch(
        f"/api/ocr/datasets/{dataset_id}/samples/{crop_id}",
        json={"text": "4,200 mm", "source_id": "plan-0", "writer_id": "writer-a", "text_style": "handwritten", "verified": True},
    )
    assert edited.status_code == 200
    assert edited.json()["dataset"]["summary"]["splits_present"] is False
    deleted = client.delete(f"/api/ocr/datasets/{dataset_id}/samples/{crop_id}")
    assert deleted.status_code == 200
    assert deleted.json()["dataset"]["summary"]["samples"] == 2


def test_dataset_archive_import_and_export_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ocr_studio_api, "OCR_DATASET_ROOT", tmp_path / "ocr")
    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    client = TestClient(app)
    created = client.post("/api/ocr/datasets", json={"name": "archive round trip"})
    assert created.status_code == 201
    dataset_id = created.json()["dataset_id"]

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "annotations.csv",
            "image,text,source_id,writer_id,text_style,verified\ncrop.png,4200 mm,plan-a,writer-a,handwritten,true\n",
        )
        archive.writestr("crop.png", _png())

    imported = client.post(
        f"/api/ocr/datasets/{dataset_id}/import-archive",
        files={"file": ("dataset.zip", archive_buffer.getvalue(), "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["added"] == 1
    assert imported.json()["dataset"]["summary"]["samples"] == 1

    exported = client.get(f"/api/ocr/datasets/{dataset_id}/export")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        names = set(archive.namelist())
    assert ocr_studio_api.MANIFEST_NAME in names
    assert any(name.startswith("images/") and name.endswith(".png") for name in names)
    assert not any("training_runs" in name or "benchmarks" in name for name in names)


def test_dataset_archive_import_rejects_csv_path_traversal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ocr_studio_api, "OCR_DATASET_ROOT", tmp_path / "ocr")
    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    client = TestClient(app)
    dataset_id = client.post("/api/ocr/datasets", json={"name": "unsafe archive"}).json()["dataset_id"]

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr(
            "annotations.csv",
            "image,text,source_id,text_style,verified\n../outside.png,4200,plan-a,handwritten,true\n",
        )
        archive.writestr("outside.png", _png())

    response = client.post(
        f"/api/ocr/datasets/{dataset_id}/import-archive",
        files={"file": ("dataset.zip", archive_buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 422
    assert "outside the archive" in response.json()["detail"]


def test_malformed_split_metadata_does_not_break_dataset_views(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "ocr"
    monkeypatch.setattr(ocr_studio_api, "OCR_DATASET_ROOT", root)
    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    client = TestClient(app)

    created = client.post("/api/ocr/datasets", json={"name": "split recovery"})
    assert created.status_code == 201
    dataset_id = created.json()["dataset_id"]
    added = client.post(
        f"/api/ocr/datasets/{dataset_id}/samples",
        files={"file": ("crop.png", _png(), "image/png")},
        data={
            "text": "4200 mm",
            "source_id": "plan-1",
            "writer_id": "writer-1",
            "verified": "true",
        },
    )
    assert added.status_code == 201, added.text

    (root / dataset_id / ocr_studio_api.SPLITS_NAME).write_text("[]", encoding="utf-8")

    detail = client.get(f"/api/ocr/datasets/{dataset_id}")
    listing = client.get("/api/ocr/datasets")
    assert detail.status_code == 200, detail.text
    assert listing.status_code == 200, listing.text
    summary = detail.json()["summary"]
    assert summary["valid"] is False
    assert summary["split_error"] == "splits.json must contain a JSON object."
    assert detail.json()["samples"][0]["split"] is None
    assert listing.json()["datasets"][0]["summary"]["valid"] is False


def test_local_ocr_studio_requires_verified_labels(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ocr_studio_api, "OCR_DATASET_ROOT", tmp_path / "ocr")
    app = FastAPI(); app.include_router(ocr_studio_api.router)
    client = TestClient(app)
    created = client.post("/api/ocr/datasets", json={"name": "handwriting"}).json()
    response = client.post(
        f"/api/ocr/datasets/{created['dataset_id']}/samples",
        files={"file": ("crop.png", _png(), "image/png")},
        data={"text": "4200", "source_id": "plan-1", "verified": "false"},
    )
    assert response.status_code == 422

    verified = client.post(
        f"/api/ocr/datasets/{created['dataset_id']}/samples",
        files={"file": ("verified.png", _png(), "image/png")},
        data={"text": "4200 mm", "source_id": "plan-1", "verified": "true"},
    )
    assert verified.status_code == 201, verified.text
    crop_id = verified.json()["crop_id"]
    omitted_verification = client.patch(
        f"/api/ocr/datasets/{created['dataset_id']}/samples/{crop_id}",
        json={"text": "4300 mm", "source_id": "plan-1"},
    )
    assert omitted_verification.status_code == 422


def test_ocr_model_list_includes_base_and_local_fine_tuned_models(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ocr"
    monkeypatch.setattr(ocr_studio_api, "OCR_DATASET_ROOT", root)
    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    client = TestClient(app)
    created = client.post("/api/ocr/datasets", json={"name": "handwriting"}).json()
    dataset_id = created["dataset_id"]
    inference_dir = root / dataset_id / "training_runs" / "012345abcdef" / "inference"
    inference_dir.mkdir(parents=True)
    (inference_dir / "inference.pdiparams").write_bytes(b"test")
    response = client.get("/api/ocr/models")
    assert response.status_code == 200
    models = response.json()["models"]
    assert any(item["model_id"] == "base:PP-OCRv5_mobile_rec" for item in models)
    assert any(item["model_id"] == f"trained:{dataset_id}:012345abcdef" for item in models)


def test_review_recognition_returns_unverified_crop_predictions(monkeypatch) -> None:
    from planline import api as planline_api

    image = np.full((16, 28, 3), 255, dtype=np.uint8)
    monkeypatch.setattr(
        planline_api,
        "decode_upload",
        lambda data, filename, page_index=0: (image.copy(), {"page_index": page_index}),
    )

    class FakeResult:
        def json(self):
            return {"res": {"rec_text": "4,200 mm", "rec_score": 0.93}}

    class FakeTextRecognition:
        def __init__(self, model_name=None, device=None):
            assert model_name == "PP-OCRv5_mobile_rec"
            assert device == "cpu"

        def predict(self, input, batch_size=1):
            assert input.shape == (16, 28, 3)
            assert batch_size == 1
            return [FakeResult()]

    fake_module = types.ModuleType("paddleocr")
    fake_module.TextRecognition = FakeTextRecognition
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    client = TestClient(app)
    review = {
        "schema_version": "planline-detection-review/v1",
        "source": {
            "filename": "plan.png",
            "page_index": 0,
            "image_width_px": 28,
            "image_height_px": 16,
        },
        "analysis": {"preprocessing": {"brightness": 0, "contrast": 1}},
        "manual_dimension_text_review": [
            {
                "detection_id": "det-001",
                "crop_bbox": {"x1": 0, "y1": 0, "x2": 28, "y2": 16},
            }
        ],
    }
    response = client.post(
        "/api/ocr/recognize-review",
        data={
            "review_json": json.dumps(review),
            "model_id": "base:PP-OCRv5_mobile_rec",
            "device": "cpu",
        },
        files={"file": ("plan.png", _png(), "image/png")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["predictions"] == [
        {"detection_id": "det-001", "text": "4,200 mm", "confidence": 0.93}
    ]
    assert any("unverified suggestions" in note for note in payload["notes"])


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ((3, 8, 20), False),
        ((3, 9, 0), True),
        ((3, 12, 5), True),
        ((3, 13, 18), True),
        ((3, 14, 0), False),
        ((4, 0, 0), False),
    ],
)
def test_paddle_python_compatibility_range(version, expected) -> None:
    assert ocr_studio_api.paddle_python_supported(version) is expected


def test_ocr_status_exposes_runtime_compatibility() -> None:
    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    response = TestClient(app).get("/api/ocr/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["python_version"]
    assert payload["python_executable"]
    assert isinstance(payload["python_compatible_for_paddle"], bool)
    assert payload["training_supported"] == payload["python_compatible_for_paddle"]
    assert "training_runtime_ready" in payload
    assert "inference_runtime_ready" in payload
    assert payload["training_note"]



def test_windows_installer_uses_ocr_compatible_python_runtime() -> None:
    """The bundled interpreter must remain inside PaddlePaddle's supported range."""
    repository_root = Path(__file__).resolve().parents[1]
    installer_source = (
        repository_root / "packaging" / "windows" / "Program.cs"
    ).read_text(encoding="utf-8")

    match = re.search(
        r'private const string PythonVersion = "(\d+)\.(\d+)\.(\d+)";',
        installer_source,
    )
    assert match is not None, "Windows installer must declare one pinned PythonVersion."
    version = tuple(int(part) for part in match.groups())

    assert ocr_studio_api.paddle_python_supported(version), (
        f"Bundled Python {version} is outside the supported PaddlePaddle range."
    )
    assert "python_version = PythonVersion" in installer_source
    assert "python-{PythonVersion}-amd64.exe" in installer_source
    assert "await IsCompatiblePythonRuntimeAsync(python)" in installer_source
    assert "3.14.10" not in installer_source
    checksum = re.search(
        r'private const string PythonSha256 =\s*"([0-9a-f]{64})";',
        installer_source,
    )
    assert checksum is not None, "Installer must pin a valid 64-character SHA-256."



def test_ocr_jobs_reject_unsupported_python_before_starting(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ocr_studio_api, "paddle_python_supported", lambda: False)
    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    client = TestClient(app)

    training = client.post(
        "/api/ocr/datasets/example/train",
        json={"paddleocr_dir": str(tmp_path), "pretrained_model": str(tmp_path / "model.pdparams")},
    )
    benchmark = client.post(
        "/api/ocr/datasets/example/benchmark",
        json={},
    )

    assert training.status_code == 422
    assert "CPython 3.9" in training.json()["detail"]
    assert benchmark.status_code == 422
    assert "CPython 3.9" in benchmark.json()["detail"]



def test_ocr_training_defaults_to_cpu_unless_gpu_is_explicitly_selected() -> None:
    assert ocr_studio_api.StartTrainingRequest(
        paddleocr_dir="paddleocr",
        pretrained_model="model.pdparams",
    ).use_gpu is False


def test_gpu_training_is_rejected_when_paddle_cuda_is_unavailable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ocr_studio_api, "_require_supported_paddle_python", lambda: None)
    monkeypatch.setattr(ocr_studio_api, "_paddle_gpu_available", lambda: False)
    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    client = TestClient(app)

    response = client.post(
        "/api/ocr/datasets/example/train",
        json={
            "paddleocr_dir": str(tmp_path / "PaddleOCR"),
            "pretrained_model": str(tmp_path / "model.pdparams"),
            "use_gpu": True,
        },
    )

    assert response.status_code == 422
    assert "PaddlePaddle GPU support is not available" in response.json()["detail"]


def test_gpu_benchmark_and_recognition_are_rejected_without_cuda(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ocr_studio_api, "_require_supported_paddle_python", lambda: None)
    monkeypatch.setattr(ocr_studio_api, "_paddle_gpu_available", lambda: False)
    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    client = TestClient(app)

    benchmark = client.post(
        "/api/ocr/datasets/example/benchmark",
        json={"device": "gpu:0"},
    )
    recognition = client.post(
        "/api/ocr/recognize-review",
        data={"review_json": "{}", "device": "gpu:0"},
        files={"file": ("drawing.png", _png(), "image/png")},
    )

    assert benchmark.status_code == 422
    assert recognition.status_code == 422
    assert "PaddlePaddle GPU support is not available" in benchmark.json()["detail"]
    assert "PaddlePaddle GPU support is not available" in recognition.json()["detail"]


def test_ocr_status_reports_paddle_cuda_availability(monkeypatch) -> None:
    monkeypatch.setattr(ocr_studio_api, "_paddle_gpu_available", lambda: False)
    result = ocr_studio_api.ocr_studio_status()

    assert result["paddle_cuda_available"] is False



def test_training_asset_status_and_prepare_routes(monkeypatch, tmp_path: Path) -> None:
    status = {
        "ready": False,
        "model_variant": "mobile",
        "source_version": "v3.3.1",
        "paddleocr_dir": "",
        "config_path": "",
        "pretrained_model": "",
        "missing": ["source", "weights"],
    }
    prepared = {
        "ready": True,
        "model_variant": "mobile",
        "source_version": "v3.3.1",
        "paddleocr_dir": str(tmp_path / "PaddleOCR"),
        "config_path": str(tmp_path / "config.yml"),
        "pretrained_model": str(tmp_path / "model.pdparams"),
        "missing": [],
    }
    monkeypatch.setattr(ocr_studio_api, "training_assets_status", lambda variant: status)
    monkeypatch.setattr(ocr_studio_api, "ensure_training_assets", lambda variant: prepared)
    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    client = TestClient(app)

    current = client.get("/api/ocr/training-assets?model_variant=mobile")
    ready = client.post(
        "/api/ocr/training-assets/prepare",
        json={"model_variant": "mobile"},
    )

    assert current.status_code == 200
    assert current.json()["ready"] is False
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert ready.json()["pretrained_model"] == prepared["pretrained_model"]


def test_training_route_automatically_provisions_missing_asset_paths(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ocr_studio_api, "_require_supported_paddle_python", lambda: None)
    monkeypatch.setattr(ocr_studio_api, "_paddle_gpu_available", lambda: False)
    monkeypatch.setattr(ocr_studio_api, "_dataset_dir", lambda dataset_id: tmp_path)
    prepared = {
        "paddleocr_dir": str(tmp_path / "PaddleOCR"),
        "pretrained_model": str(tmp_path / "model.pdparams"),
    }
    monkeypatch.setattr(ocr_studio_api, "ensure_training_assets", lambda variant: prepared)
    captured: dict[str, object] = {}

    def fake_start_training(dataset_dir, paddleocr_dir, pretrained_model, **kwargs):
        captured.update({
            "dataset_dir": dataset_dir,
            "paddleocr_dir": paddleocr_dir,
            "pretrained_model": pretrained_model,
            **kwargs,
        })
        return {"job_id": "training-job"}

    monkeypatch.setattr(ocr_studio_api, "start_training_job", fake_start_training)
    app = FastAPI()
    app.include_router(ocr_studio_api.router)
    client = TestClient(app)

    response = client.post(
        "/api/ocr/datasets/example/train",
        json={"epochs": 2, "batch_size": 4},
    )

    assert response.status_code == 202
    assert response.json()["job_id"] == "training-job"
    assert captured["paddleocr_dir"] == Path(prepared["paddleocr_dir"])
    assert captured["pretrained_model"] == Path(prepared["pretrained_model"])
    assert captured["model_variant"] == "mobile"

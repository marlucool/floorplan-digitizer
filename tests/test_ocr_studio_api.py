from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import numpy as np

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

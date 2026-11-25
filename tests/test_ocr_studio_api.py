from __future__ import annotations

import io
from pathlib import Path

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

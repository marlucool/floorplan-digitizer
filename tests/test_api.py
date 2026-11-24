from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from planline import api


class FakeBoxes:
    xyxy = np.array([[10, 20, 110, 60], [120, 80, 180, 110]], dtype=float)
    cls = np.array([0, 2], dtype=float)
    conf = np.array([0.91, 0.77], dtype=float)

    def __len__(self) -> int:
        return len(self.xyxy)


class FakeResult:
    names = {0: "wall", 1: "dimension_line", 2: "dimension_value"}
    boxes = FakeBoxes()


class FakeDetector:
    def predict(self, **kwargs):
        assert kwargs["conf"] == 0.25
        assert kwargs["imgsz"] == 640
        return [FakeResult()]


def image_bytes() -> bytes:
    image = np.full((160, 240, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def test_serialise_detections_clamps_and_labels_boxes() -> None:
    detections = api.serialise_detections(FakeResult(), (120, 200, 3))
    assert len(detections) == 2
    assert detections[0]["class_name"] == "wall"
    assert detections[0]["confidence"] == 0.91
    assert detections[1]["class_name"] == "dimension_value"
    assert detections[1]["bbox"]["x2"] == 180.0


def test_analyse_returns_regions_without_fabricating_ocr(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_detector", lambda: FakeDetector())
    client = TestClient(api.app)
    response = client.post(
        "/api/analyze",
        files={"file": ("plan.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["image"] == {"width": 240, "height": 160}
    assert payload["counts"] == {"wall": 1, "dimension_value": 1}
    assert len(payload["dimension_regions"]) == 1
    assert "value" not in payload["dimension_regions"][0]
    assert payload["export_ready"] is False
    assert payload["preview_data_url"].startswith("data:image/jpeg;base64,")
    assert any("OCR has not run" in note for note in payload["notes"])


def test_detector_load_and_prediction_are_serialized(monkeypatch) -> None:
    class LockCheckingDetector(FakeDetector):
        def predict(self, **kwargs):
            assert api._model_lock.locked()
            return super().predict(**kwargs)

    def load_detector():
        assert api._model_lock.locked()
        return LockCheckingDetector()

    monkeypatch.setattr(api, "get_detector", load_detector)
    response = TestClient(api.app).post(
        "/api/analyze",
        files={"file": ("plan.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 200


def test_rejects_unsupported_file_type() -> None:
    response = TestClient(api.app).post(
        "/api/analyze",
        files={"file": ("plan.exe", b"not an image", "application/octet-stream")},
    )
    assert response.status_code == 415


def test_rejects_invalid_image() -> None:
    response = TestClient(api.app).post(
        "/api/analyze",
        files={"file": ("plan.png", b"not a png", "image/png")},
    )
    assert response.status_code == 400


def test_rejects_large_upload(monkeypatch) -> None:
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 32)
    response = TestClient(api.app).post(
        "/api/analyze",
        files={"file": ("plan.png", b"x" * 33, "image/png")},
    )
    assert response.status_code == 413


def test_health_does_not_load_models() -> None:
    response = TestClient(api.app).get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ocr_available"] is False
    assert payload["geometry_available"] is False


def test_web_ui_assets_and_architecture_notes_are_served() -> None:
    client = TestClient(api.app)
    page = client.get("/")
    assert page.status_code == 200
    assert 'id="classFilter"' in page.text
    assert 'id="overlayToggle"' in page.text

    script = client.get("/app.js")
    assert script.status_code == 200
    assert "renderDetectionRows" in script.text

    notes = client.get("/architecture")
    assert notes.status_code == 200
    assert "dimension-chain" in notes.text

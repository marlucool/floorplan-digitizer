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
    def __init__(self, expected_conf: float = 0.25) -> None:
        self.expected_conf = expected_conf

    def predict(self, **kwargs):
        assert kwargs["conf"] == self.expected_conf
        assert kwargs["imgsz"] == 640
        self.source = kwargs["source"]
        return [FakeResult()]


def image_bytes() -> bytes:
    image = np.full((160, 240, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def test_apply_image_adjustments_changes_intensity_without_changing_coordinates() -> None:
    source = np.array([[[50, 100, 200]]], dtype=np.uint8)
    adjusted = api.apply_image_adjustments(source, brightness=10, contrast=2)
    assert adjusted.shape == source.shape
    assert adjusted.tolist() == [[[110, 210, 255]]]
    assert source.tolist() == [[[50, 100, 200]]]


def test_apply_image_adjustments_rejects_out_of_range_values() -> None:
    source = np.zeros((2, 2, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="Brightness"):
        api.apply_image_adjustments(source, brightness=101)
    with pytest.raises(ValueError, match="Contrast"):
        api.apply_image_adjustments(source, contrast=2.1)


def test_serialise_detections_clamps_and_labels_boxes() -> None:
    detections = api.serialise_detections(FakeResult(), (120, 200, 3))
    assert len(detections) == 2
    assert detections[0]["class_name"] == "wall"
    assert detections[0]["confidence"] == 0.91
    assert detections[1]["class_name"] == "dimension_value"
    assert detections[1]["bbox"]["x2"] == 180.0


def test_serialise_detections_supports_list_class_names() -> None:
    class ListNameResult:
        names = ["wall", "dimension_line", "dimension_value"]
        boxes = FakeBoxes()

    detections = api.serialise_detections(ListNameResult(), (160, 240, 3))
    assert [item["class_name"] for item in detections] == [
        "wall",
        "dimension_value",
    ]


def test_serialise_detections_skips_non_finite_predictions() -> None:
    class InvalidBoxes:
        xyxy = np.array(
            [[np.nan, 0, 10, 10], [0, 0, 5, 5]], dtype=float
        )
        cls = np.array([0, 0], dtype=float)
        conf = np.array([0.9, np.nan], dtype=float)

        def __len__(self) -> int:
            return len(self.xyxy)

    class InvalidResult:
        names = {0: "wall"}
        boxes = InvalidBoxes()

    assert api.serialise_detections(InvalidResult(), (100, 100, 3)) == []


def test_analyse_uses_adjusted_image_for_detection_and_reports_settings(monkeypatch) -> None:
    detector = FakeDetector()
    monkeypatch.setattr(api, "get_detector", lambda: detector)
    source = np.full((160, 240, 3), 50, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", source)
    assert ok
    response = TestClient(api.app).post(
        "/api/analyze",
        data={"brightness": "10", "contrast": "1.5"},
        files={"file": ("plan.png", encoded.tobytes(), "image/png")},
    )
    assert response.status_code == 200
    assert detector.source[0, 0].tolist() == [85, 85, 85]
    assert response.json()["preprocessing"] == {
        "brightness": 10,
        "contrast": 1.5,
        "method": "linear_intensity_only",
    }


def test_analyse_returns_regions_without_fabricating_ocr(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_detector", lambda: FakeDetector(expected_conf=0.4))
    client = TestClient(api.app)
    response = client.post(
        "/api/analyze",
        data={"confidence_threshold": "0.4"},
        files={"file": ("plan.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["confidence_threshold"] == pytest.approx(0.4)
    assert payload["image"] == {"width": 240, "height": 160}
    assert payload["counts"] == {"wall": 1, "dimension_value": 1}
    assert len(payload["dimension_regions"]) == 1
    assert len(payload["association_candidates"]) == 1
    assert payload["association_candidates"][0]["status"] == "unmatched"
    assert payload["dimension_regions"][0]["association"]["confirmed"] is False
    assert payload["dimension_regions"][0]["crop_data_url"].startswith(
        "data:image/png;base64,"
    )
    assert payload["dimension_regions"][0]["crop_bbox"]["width"] > 60
    assert "value" not in payload["dimension_regions"][0]
    assert payload["export_ready"] is False
    assert payload["preview_data_url"].startswith("data:image/jpeg;base64,")
    assert any("OCR has not run" in note for note in payload["notes"])


def make_pdf_bytes() -> bytes:
    import fitz

    document = fitz.open()
    document.new_page(width=100, height=200)
    document.new_page(width=200, height=100)
    data = document.tobytes()
    document.close()
    return data


def test_decode_upload_rasterises_selected_pdf_page() -> None:
    image, source = api.decode_upload(make_pdf_bytes(), "plans.pdf", page_index=1)
    assert source["source_type"] == "pdf"
    assert source["page_count"] == 2
    assert source["page_index"] == 1
    assert image.shape[1] > image.shape[0]


def test_decode_upload_rejects_pdf_page_out_of_range() -> None:
    with pytest.raises(ValueError, match="Choose a page from 1 to 2"):
        api.decode_upload(make_pdf_bytes(), "plans.pdf", page_index=2)


def test_analyse_accepts_selected_pdf_page(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_detector", lambda: FakeDetector())
    response = TestClient(api.app).post(
        "/api/analyze",
        data={"page_index": "1"},
        files={"file": ("plans.pdf", make_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["page_index"] == 1
    assert payload["source"]["page_count"] == 2
    assert payload["image"]["width"] > payload["image"]["height"]


def test_dimension_review_crops_are_bounded(monkeypatch) -> None:
    class ManyBoxes:
        xyxy = np.tile(np.array([[20, 20, 50, 40]], dtype=float), (35, 1))
        cls = np.full(35, 2, dtype=float)
        conf = np.full(35, 0.8, dtype=float)

        def __len__(self) -> int:
            return len(self.xyxy)

    class ManyResult:
        names = {0: "wall", 1: "dimension_line", 2: "dimension_value"}
        boxes = ManyBoxes()

    class ManyDetector:
        def predict(self, **kwargs):
            assert kwargs["conf"] == 0.25
            return [ManyResult()]

    monkeypatch.setattr(api, "get_detector", lambda: ManyDetector())
    response = TestClient(api.app).post(
        "/api/analyze",
        files={"file": ("plan.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["dimension_regions"]) == 35
    assert all("crop_data_url" in item for item in payload["dimension_regions"][:30])
    assert all("crop_data_url" not in item for item in payload["dimension_regions"][30:])
    assert any("first 30" in note for note in payload["notes"])


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


def test_serialise_detections_clamps_boxes_to_source_bounds() -> None:
    class OutsideBoxes:
        xyxy = np.array([[-10, -5, 150, 160]], dtype=float)
        cls = np.array([0], dtype=float)
        conf = np.array([0.8], dtype=float)

        def __len__(self) -> int:
            return len(self.xyxy)

    class OutsideResult:
        names = {0: "wall"}
        boxes = OutsideBoxes()

    detections = api.serialise_detections(OutsideResult(), (100, 100, 3))
    assert len(detections) == 1
    assert detections[0]["bbox"] == {
        "x1": 0.0,
        "y1": 0.0,
        "x2": 100.0,
        "y2": 100.0,
        "width": 100.0,
        "height": 100.0,
    }


def test_rejects_decoded_image_over_pixel_limit_before_opencv_decode(monkeypatch) -> None:
    monkeypatch.setattr(api, "MAX_IMAGE_PIXELS", 100)
    monkeypatch.setattr(
        api.cv2,
        "imdecode",
        lambda *_args: pytest.fail("OpenCV must not decode an oversized raster"),
    )
    response = TestClient(api.app).post(
        "/api/analyze",
        files={"file": ("plan.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 413


def test_rejects_empty_upload() -> None:
    response = TestClient(api.app).post(
        "/api/analyze",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400


def test_dimension_chain_endpoint_checks_only_explicit_values() -> None:
    response = TestClient(api.app).post(
        "/api/validate-dimension-chain",
        json={
            "segment_values": ["3000", "4500", "2500"],
            "segment_verified": [True, True, True],
            "overall_value": "10000",
            "overall_verified": True,
            "unit": "mm",
            "tolerance": "0",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "matches"
    assert response.json()["difference"] == "0"


def test_dimension_chain_endpoint_keeps_unverified_values_unresolved_for_review() -> None:
    response = TestClient(api.app).post(
        "/api/validate-dimension-chain",
        json={
            "segment_values": ["3000", "4500", "2500"],
            "segment_verified": [True, False, True],
            "overall_value": "10000",
            "overall_verified": True,
            "unit": "mm",
            "tolerance": "0",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "needs_review"
    assert response.json()["unverified_indices"] == [1]


def test_dimension_chain_endpoint_rejects_mismatched_verification_flags() -> None:
    response = TestClient(api.app).post(
        "/api/validate-dimension-chain",
        json={
            "segment_values": ["3000", "4500"],
            "segment_verified": [True],
            "overall_value": "7500",
            "overall_verified": True,
            "unit": "mm",
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("threshold", ["0", "1.01", "nan", "inf"])
def test_rejects_invalid_confidence_threshold(threshold: str) -> None:
    response = TestClient(api.app).post(
        "/api/analyze",
        data={"confidence_threshold": threshold},
        files={"file": ("plan.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 422


def test_rejects_unsupported_file_type() -> None:
    response = TestClient(api.app).post(
        "/api/analyze",
        files={"file": ("plan.exe", b"not an image", "application/octet-stream")},
    )
    assert response.status_code == 415


def test_analyse_validates_image_cleanup_ranges() -> None:
    client = TestClient(api.app)
    response = client.post(
        "/api/analyze",
        data={"brightness": "101"},
        files={"file": ("plan.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 422
    response = client.post(
        "/api/analyze",
        data={"contrast": "2.1"},
        files={"file": ("plan.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 422


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
    assert payload["dimension_chain_validation_available"] is True
    assert payload["geometry_available"] is False


def test_web_ui_assets_and_architecture_notes_are_served() -> None:
    client = TestClient(api.app)
    page = client.get("/")
    assert page.status_code == 200
    assert 'id="classFilter"' in page.text
    assert 'id="overlayToggle"' in page.text
    assert 'id="pdfPageNumber"' in page.text
    assert 'id="startCalibration"' in page.text
    assert 'id="applyCalibration"' in page.text
    assert 'id="openProject"' in page.text
    assert 'id="saveProject"' in page.text
    assert 'id="brightnessControl"' in page.text
    assert 'id="contrastControl"' in page.text
    assert 'id="drawWallTool"' in page.text
    assert 'id="exportGeometry"' in page.text
    assert 'id="drawRoomTool"' in page.text
    assert 'id="exportDxf"' in page.text
    assert 'id="wallLength"' in page.text
    assert 'id="geometrySnap"' in page.text
    assert 'id="finishRoom"' in page.text
    assert 'id="roomArea"' in page.text

    script = client.get("/app.js")
    assert "interpret-dimension-button" in script.text
    assert "compareSelectedWallToDimension" in script.text
    assert "user_two_point_reference" in script.text
    assert "pixels_per_mm" in script.text
    assert "planline-project" in script.text
    assert "restoreProjectReview" in script.text
    assert "encodeFileBase64" in script.text
    assert "openProjectFile" in script.text
    assert "brightness" in script.text
    assert "contrast" in script.text
    assert "exportManualGeometrySvg" in script.text
    assert "manual_geometry" in script.text
    assert "manual_rooms" in script.text
    assert "polygonAreaPx2" in script.text
    assert "function beginWallEndpointDrag" in script.text
    assert "function snapPointToGeometry" in script.text
    assert "runOcrOnCandidates" in script.text
    assert "function moveWallEndpointDrag" in script.text
    assert script.status_code == 200
    assert "renderDetectionRows" in script.text
    assert "applyImageScale" in script.text
    assert 'id="zoomIn"' in page.text
    assert 'id="fitView"' in page.text
    assert 'id="chainChecker"' in page.text
    assert 'id="addSegment"' in page.text
    assert 'id="checkChain"' in page.text
    assert 'id="dimensionTextReview"' in page.text
    assert 'id="runOcrButton"' in page.text
    assert 'id="ocrModelSelect"' in page.text
    assert 'id="ocrDeviceSelect"' in page.text
    assert 'id="exportReview"' in page.text
    assert 'id="confidenceThreshold"' in page.text
    assert "exportReviewJson" in script.text
    assert "checkDimensionChain" in script.text

    notes = client.get("/architecture")
    assert notes.status_code == 200
    assert "dimension-chain" in notes.text



def test_settings_page_and_global_workspace_navigation_are_available() -> None:
    client = TestClient(api.app)
    settings = client.get("/settings")
    assert settings.status_code == 200
    assert "Updates" in settings.text
    assert 'href="/">Drawing workspace</a>' in settings.text
    drawing = client.get("/")
    assert 'href="/settings">Settings</a>' in drawing.text
    ocr = client.get("/ocr")
    assert 'href="/settings">Settings</a>' in ocr.text


def test_update_check_endpoint_returns_current_release_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        api.updater,
        "check_for_updates",
        lambda: {
            "status": "update_available",
            "current_version": "0.1.1",
            "latest_version": "0.1.2",
            "update_available": True,
            "install_available": True,
            "release_url": "https://github.com/marlucool/floorplan-digitizer/releases/tag/planline-v0.1.2",
            "release_notes": "Fixes and improvements",
            "published_at": "2026-11-25T00:00:00Z",
            "installer_size": 10_000_000,
            "message": "A verified installer is available.",
        },
    )
    response = TestClient(api.app).get("/api/updates/check")
    assert response.status_code == 200
    assert response.json()["latest_version"] == "0.1.2"
    assert response.json()["install_available"] is True


def test_dimension_chain_endpoint_proposes_single_missing_segment_without_verifying_it() -> None:
    response = TestClient(api.app).post(
        "/api/validate-dimension-chain",
        json={
            "segment_values": ["3000", None, "2500"],
            "segment_verified": [True, False, True],
            "overall_value": "10000",
            "overall_verified": True,
            "unit": "mm",
            "tolerance": "0",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_available"] is True
    assert payload["candidate_index"] == 1
    assert payload["candidate_value"] == "4500"
    assert payload["candidate_requires_confirmation"] is True
    assert payload["status"] == "unresolved"

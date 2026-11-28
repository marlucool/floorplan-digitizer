from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from planline.api import app
from planline import reconstruction
from planline.reconstruction import WallReconstructionRequest, reconstruct_wall_edges


def detection(item_id: str, kind: str, box: tuple[float, float, float, float]) -> dict:
    x1, y1, x2, y2 = box
    return {
        "id": item_id,
        "class_name": kind,
        "confidence": 0.95,
        "bbox": {
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "width": x2 - x1, "height": y2 - y1,
        },
    }


def sample_request(**overrides) -> WallReconstructionRequest:
    values = {
        "source_width": 220,
        "source_height": 220,
        "source_page_index": 1,
        "detections": [
            detection("value-x", "dimension_value", (75, 31, 125, 49)),
            detection("line-x", "dimension_line", (20, 54, 180, 58)),
            detection("wall-left", "wall", (10, 60, 20, 180)),
            detection("wall-right", "wall", (180, 60, 190, 180)),
            detection("value-y", "dimension_value", (31, 75, 49, 125)),
            detection("line-y", "dimension_line", (54, 20, 58, 180)),
            detection("wall-top", "wall", (60, 10, 180, 20)),
            detection("wall-bottom", "wall", (60, 180, 180, 190)),
        ],
        "dimensions": [
            {
                "detection_id": "value-x",
                "raw_text": "4000 mm",
                "text_verified": True,
                "association_confirmed": True,
                "dimension_line_id": "line-x",
                "wall_ids": ["wall-left", "wall-right"],
            },
            {
                "detection_id": "value-y",
                "raw_text": "4000 mm",
                "text_verified": True,
                "association_confirmed": True,
                "dimension_line_id": "line-y",
                "wall_ids": ["wall-top", "wall-bottom"],
            },
        ],
    }
    values.update(overrides)
    return WallReconstructionRequest(**values)


def test_reconstructs_editable_wall_faces_from_both_confirmed_axes() -> None:
    result = reconstruct_wall_edges(sample_request())
    assert result["status"] == "draft"
    assert result["scale"]["pixels_per_mm_x"] == pytest.approx(0.04)
    assert result["scale"]["pixels_per_mm_y"] == pytest.approx(0.04)
    assert result["wall_regions_used"] == 4
    assert len(result["segments"]) == 8
    assert all(item["created_by_reconstruction"] for item in result["segments"])
    assert {item["source_page_index"] for item in result["segments"]} == {1}
    assert {item["source_detection_id"] for item in result["segments"]} == {
        "wall-left", "wall-right", "wall-top", "wall-bottom"
    }
    assert "doors" in " ".join(result["warnings"]).lower()


def test_unverified_or_unassociated_dimensions_do_not_constrain_geometry() -> None:
    request = sample_request(dimensions=[
        {
            "detection_id": "value-x",
            "raw_text": "4000 mm",
            "text_verified": True,
            "association_confirmed": False,
            "dimension_line_id": "line-x",
            "wall_ids": ["wall-left", "wall-right"],
        },
        {
            "detection_id": "value-y",
            "raw_text": "4000 mm",
            "text_verified": False,
            "association_confirmed": True,
            "dimension_line_id": "line-y",
            "wall_ids": ["wall-top", "wall-bottom"],
        },
    ])
    with pytest.raises(ValueError, match="Verify at least one dimension"):
        reconstruct_wall_edges(request)


def test_metric_reconstruction_requires_confirmed_dimensions_on_both_axes() -> None:
    request = sample_request(dimensions=[
        {
            "detection_id": "value-x",
            "raw_text": "4000 mm",
            "text_verified": True,
            "association_confirmed": True,
            "dimension_line_id": "line-x",
            "wall_ids": ["wall-left", "wall-right"],
        }
    ])
    with pytest.raises(ValueError, match="Y scale"):
        reconstruct_wall_edges(request)


def test_rejects_ambiguous_or_unreadable_verified_dimension_text() -> None:
    dimensions = sample_request().dimensions
    dimensions[0].raw_text = "4000"
    request = sample_request(dimensions=[item.model_dump() for item in dimensions])
    with pytest.raises(ValueError, match="unit is not written"):
        reconstruct_wall_edges(request)


def test_rejects_dimension_association_that_does_not_match_candidate_geometry() -> None:
    request = sample_request(dimensions=[
        {
            "detection_id": "value-x",
            "raw_text": "4000 mm",
            "text_verified": True,
            "association_confirmed": True,
            "dimension_line_id": "line-x",
            "wall_ids": ["wall-left", "wall-top"],
        },
        {
            "detection_id": "value-y",
            "raw_text": "4000 mm",
            "text_verified": True,
            "association_confirmed": True,
            "dimension_line_id": "line-y",
            "wall_ids": ["wall-top", "wall-bottom"],
        },
    ])
    with pytest.raises(ValueError, match="no longer matches"):
        reconstruct_wall_edges(request)


def test_conflicting_confirmed_dimensions_on_same_axis_block_reconstruction(monkeypatch) -> None:
    request = sample_request(
        detections=[
            *[item.model_dump() for item in sample_request().detections],
            detection("value-x2", "dimension_value", (70, 31, 120, 49)),
            detection("line-x2", "dimension_line", (20, 54, 180, 58)),
            detection("wall-inner-left", "wall", (60, 60, 70, 180)),
            detection("wall-inner-right", "wall", (130, 60, 140, 180)),
        ],
        dimensions=[
            {
                "detection_id": "value-x",
                "raw_text": "4000 mm",
                "text_verified": True,
                "association_confirmed": True,
                "dimension_line_id": "line-x",
                "wall_ids": ["wall-left", "wall-right"],
            },
            {
                "detection_id": "value-x2",
                "raw_text": "5000 mm",
                "text_verified": True,
                "association_confirmed": True,
                "dimension_line_id": "line-x2",
                "wall_ids": ["wall-inner-left", "wall-inner-right"],
            },
            {
                "detection_id": "value-y",
                "raw_text": "4000 mm",
                "text_verified": True,
                "association_confirmed": True,
                "dimension_line_id": "line-y",
                "wall_ids": ["wall-top", "wall-bottom"],
            },
        ],
    )

    # Isolate the scale-consistency gate with two valid candidate spans whose
    # independently confirmed labels imply incompatible X-axis scales.
    monkeypatch.setattr(reconstruction, "associate_dimensions", lambda _detections: [
        {
            "dimension_value_id": "value-x",
            "candidate_lines": [{
                "dimension_line_id": "line-x",
                "orientation": "horizontal",
                "wall_spans": [{"wall_ids": ["wall-left", "wall-right"], "span_px": 160, "assignment_score": 0.9}],
            }],
        },
        {
            "dimension_value_id": "value-x2",
            "candidate_lines": [{
                "dimension_line_id": "line-x2",
                "orientation": "horizontal",
                "wall_spans": [{"wall_ids": ["wall-inner-left", "wall-inner-right"], "span_px": 70, "assignment_score": 0.8}],
            }],
        },
        {
            "dimension_value_id": "value-y",
            "candidate_lines": [{
                "dimension_line_id": "line-y",
                "orientation": "vertical",
                "wall_spans": [{"wall_ids": ["wall-top", "wall-bottom"], "span_px": 160, "assignment_score": 0.9}],
            }],
        },
    ])

    with pytest.raises(ValueError, match="dimensions disagree"):
        reconstruct_wall_edges(request)


def test_reconstruction_endpoint_returns_a_reviewable_wall_draft() -> None:
    response = TestClient(app).post(
        "/api/reconstruct-wall-draft",
        json=sample_request().model_dump(mode="json"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["scale"]["pixels_per_mm_x"] == pytest.approx(0.04)
    assert payload["junction_tolerance_px"] == 2.0
    assert isinstance(payload["junction_candidates"], list)
    assert len(payload["segments"]) == 8


def test_reconstruction_endpoint_rejects_missing_axis_measurement() -> None:
    request = sample_request(dimensions=[
        {
            "detection_id": "value-x",
            "raw_text": "4000 mm",
            "text_verified": True,
            "association_confirmed": True,
            "dimension_line_id": "line-x",
            "wall_ids": ["wall-left", "wall-right"],
        }
    ])
    response = TestClient(app).post(
        "/api/reconstruct-wall-draft",
        json=request.model_dump(mode="json"),
    )
    assert response.status_code == 422
    assert "Y scale" in response.json()["detail"]

def test_reconstruction_rejects_reusing_one_dimension_value_for_multiple_spans() -> None:
    dimensions = [item.model_dump() for item in sample_request().dimensions]
    dimensions[1]["detection_id"] = "value-x"
    request = sample_request(dimensions=dimensions)
    with pytest.raises(ValueError, match="can only be used once"):
        reconstruct_wall_edges(request)


def test_reconstruction_rejects_dimension_entry_that_is_not_a_value_detection() -> None:
    dimensions = [item.model_dump() for item in sample_request().dimensions]
    dimensions[0]["detection_id"] = "wall-left"
    with pytest.raises(ValueError, match="dimension-value detection"):
        sample_request(dimensions=dimensions)

def test_junction_candidates_report_nearby_endpoints_without_snapping_geometry() -> None:
    segments = [
        {
            "id": "edge-a",
            "source_detection_id": "wall-a",
            "start_px": {"x": 0, "y": 0},
            "end_px": {"x": 10, "y": 0},
        },
        {
            "id": "edge-b",
            "source_detection_id": "wall-b",
            "start_px": {"x": 11, "y": 1},
            "end_px": {"x": 10, "y": 10},
        },
    ]
    before = [
        (dict(item["start_px"]), dict(item["end_px"]))
        for item in segments
    ]
    junctions = reconstruction._junction_candidates(segments, tolerance_px=2.0)
    assert len(junctions) == 1
    assert junctions[0]["source_detection_ids"] == ["wall-a", "wall-b"]
    assert set(junctions[0]["segment_ids"]) == {"edge-a", "edge-b"}
    assert junctions[0]["status"] == "candidate_requires_review"
    assert [
        (item["start_px"], item["end_px"])
        for item in segments
    ] == before

    same_wall = [
        {**segments[0], "id": "same-a"},
        {**segments[0], "id": "same-b"},
    ]
    assert reconstruction._junction_candidates(same_wall, tolerance_px=2.0) == []


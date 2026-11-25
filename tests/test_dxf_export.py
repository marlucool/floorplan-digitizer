from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from planline.api import app
from planline.dxf_export import (
    ManualGeometryDXFRequest,
    export_manual_geometry_dxf,
)


def sample_request(**overrides) -> ManualGeometryDXFRequest:
    values = {
        "source_width": 200,
        "source_height": 100,
        "pixels_per_mm": 2,
        "segments": [
            {
                "id": "manual-wall-001",
                "start_px": {"x": 20, "y": 10},
                "end_px": {"x": 60, "y": 10},
            }
        ],
        "rooms": [
            {
                "id": "manual-room-001",
                "vertices_px": [
                    {"x": 20, "y": 20},
                    {"x": 80, "y": 20},
                    {"x": 80, "y": 70},
                    {"x": 20, "y": 70},
                ],
            }
        ],
    }
    values.update(overrides)
    return ManualGeometryDXFRequest(**values)


def test_dxf_contains_wall_lines_and_closed_room_polylines_in_mm() -> None:
    text = export_manual_geometry_dxf(sample_request()).decode("ascii")
    assert "$INSUNITS" in text
    assert "AC1015" in text
    assert "WALLS" in text
    assert "ROOMS" in text
    assert "LWPOLYLINE" in text
    assert "LINE" in text
    # Image y=10 in a 100px-high image maps to CAD y=45mm at 2px/mm.
    pairs = text.splitlines()
    assert pairs[pairs.index("10", pairs.index("LINE") + 1) + 1] == "10"
    assert pairs[pairs.index("20", pairs.index("LINE") + 1) + 1] == "45"
    assert pairs[pairs.index("11", pairs.index("LINE") + 1) + 1] == "30"


def test_dxf_without_calibration_is_explicitly_unitless_and_flips_y() -> None:
    request = sample_request(pixels_per_mm=None, rooms=[])
    text = export_manual_geometry_dxf(request).decode("ascii")
    pairs = text.splitlines()
    insunits = pairs.index("$INSUNITS")
    assert pairs[insunits + 2] == "0"
    line = pairs.index("LINE")
    assert pairs[pairs.index("20", line) + 1] == "90"


def test_dxf_rejects_geometry_outside_source_bounds() -> None:
    with pytest.raises(ValidationError, match="inside the source image"):
        sample_request(segments=[{
            "id": "wall",
            "start_px": {"x": 20, "y": 10},
            "end_px": {"x": 201, "y": 10},
        }], rooms=[])


def test_dxf_rejects_zero_length_wall_and_self_intersecting_room() -> None:
    with pytest.raises(ValidationError, match="zero length"):
        sample_request(segments=[{
            "id": "wall",
            "start_px": {"x": 20, "y": 10},
            "end_px": {"x": 20, "y": 10},
        }], rooms=[])
    with pytest.raises(ValidationError, match="self-intersects"):
        sample_request(segments=[], rooms=[{
            "id": "bow-tie",
            "vertices_px": [
                {"x": 20, "y": 20},
                {"x": 80, "y": 70},
                {"x": 20, "y": 70},
                {"x": 80, "y": 20},
            ],
        }])


def test_export_dxf_endpoint_returns_downloadable_ascii_dxf() -> None:
    response = TestClient(app).post(
        "/api/export-dxf",
        json=sample_request().model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/dxf")
    assert "attachment;" in response.headers["content-disposition"]
    assert b"LWPOLYLINE" in response.content
    assert response.content.endswith(b"0\nEOF\n")


def test_export_dxf_endpoint_rejects_empty_geometry() -> None:
    response = TestClient(app).post(
        "/api/export-dxf",
        json={
            "source_width": 200,
            "source_height": 100,
            "segments": [],
            "rooms": [],
        },
    )
    assert response.status_code == 422

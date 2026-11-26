from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from planline.api import app
from planline.dimension_constraints import WallDimensionCheckRequest, compare_wall_dimension


def test_wall_dimension_comparison_within_tolerance() -> None:
    result = compare_wall_dimension(WallDimensionCheckRequest(
        wall_length_px="4200",
        pixels_per_mm="1",
        dimension_mm="4200",
        tolerance_percent="1",
    ))
    assert result["status"] == "within_tolerance"
    assert result["measured_length_mm"] == "4200"
    assert result["delta_mm"] == "0"
    assert result["geometry_modified"] is False
    assert result["requires_review"] is True


def test_wall_dimension_comparison_reports_mismatch_without_rescaling() -> None:
    result = compare_wall_dimension(WallDimensionCheckRequest(
        wall_length_px="4250",
        pixels_per_mm="1",
        dimension_mm="4200",
        tolerance_percent="0.5",
    ))
    assert result["status"] == "mismatch"
    assert result["delta_mm"] == "50"
    assert result["difference_percent"] == "1.19"
    assert result["geometry_modified"] is False


def test_wall_dimension_comparison_rejects_zero_or_invalid_values() -> None:
    with pytest.raises(ValidationError):
        WallDimensionCheckRequest(
            wall_length_px="0",
            pixels_per_mm="1",
            dimension_mm="4200",
        )
    with pytest.raises(ValidationError):
        WallDimensionCheckRequest(
            wall_length_px="4200",
            pixels_per_mm="1",
            dimension_mm="4200",
            tolerance_percent="10.1",
        )


def test_wall_dimension_comparison_accepts_full_precision_scale_values() -> None:
    result = compare_wall_dimension(WallDimensionCheckRequest(
        wall_length_px="230.2172886583",
        pixels_per_mm="0.08571428571428572",
        dimension_mm="2685",
        tolerance_percent="1.0",
    ))
    assert result["status"] == "within_tolerance"
    assert result["geometry_modified"] is False


def test_wall_dimension_comparison_handles_extreme_valid_decimal_ranges() -> None:
    # All values satisfy the API schema. The percentage result needs more than
    # Decimal's default 28-digit context when the verified dimension is tiny.
    result = compare_wall_dimension(WallDimensionCheckRequest(
        wall_length_px="9999999999.99999999999999999999",
        pixels_per_mm="0.000000000001",
        dimension_mm="0.00000001",
        tolerance_percent="1",
    ))
    assert result["status"] == "mismatch"
    assert result["measured_length_mm"] == "10000000000000000000000"
    assert result["difference_percent"] == "99999999999999999999999999999800"
    assert result["geometry_modified"] is False


def test_wall_dimension_endpoint_returns_review_only_result() -> None:
    response = TestClient(app).post(
        "/api/validate-wall-dimension",
        json={
            "wall_length_px": "4200",
            "pixels_per_mm": "1",
            "dimension_mm": "4200",
            "tolerance_percent": "1",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "within_tolerance"
    assert payload["calibration_source"] == "user_supplied_two_point_reference"
    assert payload["geometry_modified"] is False

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from planline.api import app
from planline.dimensions import interpret_dimension_text


@pytest.mark.parametrize(
    ("text", "expected_mm", "expected_type"),
    [
        ("4,200 mm", "4200", "linear"),
        ("4200mm", "4200", "linear"),
        ("4.2 m", "4200", "linear"),
        ("4,2 m", "4200", "linear"),
        ("250 cm", "2500", "linear"),
        ('12"', "304.8", "linear"),
        ('1/2"', "12.7", "linear"),
        ('2 1/2 in', "63.5", "linear"),
        ("4'6\u2033", "1371.6", "linear"),
        ("4'-6\u2033", "1371.6", "linear"),
        ("4 ft 6 in", "1371.6", "linear"),
        ("Ø12 mm", "12", "diameter"),
        ("R 25 mm", "25", "radius"),
        ("R25mm", "25", "radius"),
    ],
)
def test_explicit_dimension_formats_convert_to_mm(text: str, expected_mm: str, expected_type: str) -> None:
    result = interpret_dimension_text(text)
    assert result["status"] == "parsed"
    assert result["value_mm"] == expected_mm
    assert result["dimension_type"] == expected_type
    assert result["requires_review"] is True


def test_bare_number_never_assumes_millimetres() -> None:
    result = interpret_dimension_text("4200")
    assert result["status"] == "unit_missing"
    assert result["value"] == "4200"
    assert result["value_mm"] is None
    assert "unit is not written" in result["reason"]


def test_dot_thousands_separator_is_reported_as_ambiguous() -> None:
    result = interpret_dimension_text("4.200 mm")
    assert result["status"] == "ambiguous"
    assert result["value_mm"] is None


@pytest.mark.parametrize("text", ["0 mm", "-12 cm", "4 ft 12 in", "1/0 in", "999999999999 m", "not a dimension"])
def test_invalid_or_non_positive_dimensions_are_not_parsed(text: str) -> None:
    result = interpret_dimension_text(text)
    assert result["status"] != "parsed"
    assert result["value_mm"] is None


def test_dimension_interpreter_api_is_conservative() -> None:
    client = TestClient(app)
    parsed = client.post("/api/interpret-dimension", json={"text": "4,200 mm"})
    assert parsed.status_code == 200
    assert parsed.json()["value_mm"] == "4200"
    ambiguous = client.post("/api/interpret-dimension", json={"text": "4.200 mm"})
    assert ambiguous.json()["status"] == "ambiguous"
    missing = client.post("/api/interpret-dimension", json={"text": "4200"})
    assert missing.json()["value_mm"] is None
    assert client.post("/api/interpret-dimension", json={"text": ""}).status_code == 422

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from planline.constraints import (
    DimensionChainRequest,
    validate_dimension_chain,
)


def request(**overrides) -> DimensionChainRequest:
    values = {
        "segment_values": ["3000", "4500", "2500"],
        "segment_verified": [True, True, True],
        "overall_value": "10000",
        "overall_verified": True,
        "unit": "mm",
        "tolerance": "0",
    }
    values.update(overrides)
    return DimensionChainRequest(**values)


def test_dimension_chain_matches_exactly() -> None:
    result = validate_dimension_chain(request())
    assert result["status"] == "matches"
    assert result["segment_total"] == "10000"
    assert result["difference"] == "0"
    assert result["unit"] == "mm"


def test_dimension_chain_uses_explicit_tolerance() -> None:
    result = validate_dimension_chain(
        request(segment_values=["3000", "4500", "2500.5"], tolerance="1")
    )
    assert result["status"] == "matches"
    assert result["difference"] == "0.5"


def test_dimension_chain_mismatch_is_not_adjusted() -> None:
    result = validate_dimension_chain(request(overall_value="9990"))
    assert result["status"] == "mismatch"
    assert result["segment_total"] == "10000"
    assert result["overall_value"] == "9990"
    assert result["difference"] == "10"


def test_unverified_values_require_review_even_if_the_sum_matches() -> None:
    result = validate_dimension_chain(
        request(segment_verified=[True, False, True])
    )
    assert result["status"] == "needs_review"
    assert result["unverified_indices"] == [1]


def test_missing_values_remain_unresolved() -> None:
    result = validate_dimension_chain(
        request(segment_values=["3000", None, "2500"])
    )
    assert result["status"] == "unresolved"
    assert result["segment_total"] is None
    assert result["unresolved_indices"] == [1]


def test_dimension_chain_rejects_inconsistent_flags_and_invalid_values() -> None:
    with pytest.raises(ValidationError):
        request(segment_verified=[True, True])
    with pytest.raises(ValidationError):
        request(segment_values=["3000", "0", "2500"])
    with pytest.raises(ValidationError):
        request(tolerance="-1")

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


def test_missing_overall_dimension_is_reported_separately() -> None:
    result = validate_dimension_chain(
        request(overall_value=None, overall_verified=False)
    )
    assert result["status"] == "unresolved"
    assert result["overall_unresolved"] is True


def test_unverified_overall_dimension_requires_review() -> None:
    result = validate_dimension_chain(request(overall_verified=False))
    assert result["status"] == "needs_review"
    assert result["overall_verified"] is False


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


def test_single_missing_segment_is_proposed_from_verified_inputs() -> None:
    result = validate_dimension_chain(
        request(
            segment_values=["3000", None, "2500"],
            segment_verified=[True, False, True],
            overall_value="10000",
            overall_verified=True,
        )
    )
    assert result["status"] == "unresolved"
    assert result["candidate_available"] is True
    assert result["candidate_index"] == 1
    assert result["candidate_value"] == "4500"
    assert result["candidate_requires_confirmation"] is True


def test_single_missing_segment_is_not_proposed_from_unverified_inputs() -> None:
    result = validate_dimension_chain(
        request(
            segment_values=["3000", None, "2500"],
            segment_verified=[False, False, True],
            overall_value="10000",
            overall_verified=True,
        )
    )
    assert result["candidate_available"] is False
    assert result["candidate_value"] is None
    assert "Verify" in result["candidate_reason"]


def test_single_missing_segment_rejects_non_positive_remainder() -> None:
    result = validate_dimension_chain(
        request(
            segment_values=["6000", None, "5000"],
            segment_verified=[True, False, True],
            overall_value="10000",
            overall_verified=True,
        )
    )
    assert result["candidate_available"] is False
    assert result["candidate_value"] is None


def test_multiple_missing_segments_are_underdetermined() -> None:
    result = validate_dimension_chain(
        request(
            segment_values=["3000", None, None],
            segment_verified=[True, False, False],
            overall_value="10000",
            overall_verified=True,
        )
    )
    assert result["candidate_available"] is False
    assert "multiple unknowns" in result["candidate_reason"]

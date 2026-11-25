"""Explicit dimension-chain checks for reviewed measurements.

This module validates arithmetic only. It does not read OCR, infer units,
associate dimensions with walls, or estimate missing measurements.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


DimensionUnit = Literal["mm", "cm", "m", "in", "ft"]


class DimensionChainRequest(BaseModel):
    """Values for one manually reviewed dimension chain."""

    segment_values: list[Decimal | None] = Field(min_length=1)
    segment_verified: list[bool]
    overall_value: Decimal | None
    overall_verified: bool
    unit: DimensionUnit
    tolerance: Decimal = Decimal("0")

    @model_validator(mode="after")
    def validate_measurements(self) -> "DimensionChainRequest":
        if len(self.segment_verified) != len(self.segment_values):
            raise ValueError("segment_verified must match segment_values length")
        if not self.tolerance.is_finite() or self.tolerance < 0:
            raise ValueError("tolerance must be a finite non-negative value")
        for index, value in enumerate(self.segment_values):
            if value is not None and (not value.is_finite() or value <= 0):
                raise ValueError(f"segment_values[{index}] must be positive and finite")
        if self.overall_value is not None and (
            not self.overall_value.is_finite() or self.overall_value <= 0
        ):
            raise ValueError("overall_value must be positive and finite")
        return self


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def validate_dimension_chain(request: DimensionChainRequest) -> dict[str, object]:
    """Check a dimension sum without inventing or repairing any value."""
    unresolved_indices = [
        index for index, value in enumerate(request.segment_values) if value is None
    ]
    unverified_indices = [
        index for index, verified in enumerate(request.segment_verified) if not verified
    ]
    total = (
        sum((value for value in request.segment_values if value is not None), Decimal(0))
        if not unresolved_indices
        else None
    )
    difference = (
        total - request.overall_value
        if total is not None and request.overall_value is not None
        else None
    )

    if unresolved_indices or request.overall_value is None:
        status = "unresolved"
    elif unverified_indices or not request.overall_verified:
        status = "needs_review"
    elif abs(difference) <= request.tolerance:
        status = "matches"
    else:
        status = "mismatch"

    return {
        "status": status,
        "segment_total": _decimal_text(total),
        "overall_value": _decimal_text(request.overall_value),
        "difference": _decimal_text(difference),
        "tolerance": _decimal_text(request.tolerance),
        "unit": request.unit,
        "unresolved_indices": unresolved_indices,
        "overall_unresolved": request.overall_value is None,
        "unverified_indices": unverified_indices,
        "overall_verified": request.overall_verified,
    }

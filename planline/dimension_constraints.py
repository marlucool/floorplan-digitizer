"""Conservative comparison between a user-drawn wall and a verified dimension."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class WallDimensionCheckRequest(BaseModel):
    wall_length_px: Decimal = Field(gt=0, max_digits=30, decimal_places=20)
    pixels_per_mm: Decimal = Field(ge=Decimal("0.000000000001"), le=Decimal("1000000"), max_digits=30, decimal_places=20)
    dimension_mm: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    tolerance_percent: Decimal = Field(default=Decimal("1.0"), ge=0, le=10, max_digits=5, decimal_places=2)
    calibration_method: Literal["verified_dimension_association", "user_two_point_reference"] = "user_two_point_reference"

    @model_validator(mode="after")
    def validate_finite_values(self) -> "WallDimensionCheckRequest":
        for value in (self.wall_length_px, self.pixels_per_mm, self.dimension_mm, self.tolerance_percent):
            if not value.is_finite():
                raise ValueError("All dimension comparison values must be finite.")
        return self


def _format(value: Decimal) -> str:
    # The validated input ranges permit results wider than Decimal's default
    # 28-digit context (especially percentage differences for tiny dimensions).
    # Keep enough precision to round every supported result to 0.001 safely.
    with localcontext() as context:
        context.prec = 60
        rounded = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        return format(rounded.normalize(), "f")


def compare_wall_dimension(request: WallDimensionCheckRequest) -> dict[str, Any]:
    # Division and percentage calculation can also exceed the default Decimal
    # precision even when every individual request field is valid.
    with localcontext() as context:
        context.prec = 60
        measured_mm = request.wall_length_px / request.pixels_per_mm
        delta_mm = measured_mm - request.dimension_mm
        difference_percent = abs(delta_mm) / request.dimension_mm * Decimal("100")
        status = "within_tolerance" if difference_percent <= request.tolerance_percent else "mismatch"

    return {
        "status": status,
        "measured_length_mm": _format(measured_mm),
        "dimension_value_mm": _format(request.dimension_mm),
        "delta_mm": _format(delta_mm),
        "difference_percent": _format(difference_percent),
        "tolerance_percent": _format(request.tolerance_percent),
        "calibration_source": request.calibration_method,
        "requires_review": True,
        "geometry_modified": False,
        "note": (
            "This comparison uses a scale derived from a reviewer-confirmed dimension-to-wall-span association. "
            "It remains a candidate scale, does not independently validate the drawing, and does not alter geometry."
            if request.calibration_method == "verified_dimension_association"
            else "This comparison uses a user-supplied manual two-point scale and a manually verified dimension. "
            "It does not prove the wall association or alter geometry."
        ),
    }

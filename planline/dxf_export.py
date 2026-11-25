"""Minimal, validated DXF export for Planline's user-authored 2D geometry.

Only manually drawn wall segments and room outlines are exported. Detector
boxes, OCR suggestions and unverified dimensions are never converted to CAD.
"""
from __future__ import annotations

import math
from pydantic import BaseModel, Field, model_validator


class PointPx(BaseModel):
    x: float = Field(ge=0, le=25_000_000)
    y: float = Field(ge=0, le=25_000_000)


class WallSegmentInput(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    start_px: PointPx
    end_px: PointPx


class RoomPolygonInput(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    vertices_px: list[PointPx] = Field(min_length=3, max_length=10_000)


class ManualGeometryDXFRequest(BaseModel):
    """Source-space geometry plus optional user-supplied pixels/mm calibration."""

    source_width: int = Field(ge=1, le=25_000_000)
    source_height: int = Field(ge=1, le=25_000_000)
    pixels_per_mm: float | None = Field(default=None, ge=1e-12, le=1_000_000)
    segments: list[WallSegmentInput] = Field(default_factory=list, max_length=10_000)
    rooms: list[RoomPolygonInput] = Field(default_factory=list, max_length=2_000)

    @model_validator(mode="after")
    def validate_geometry(self) -> "ManualGeometryDXFRequest":
        if self.source_width * self.source_height > 25_000_000:
            raise ValueError("Source image exceeds the 25-megapixel geometry limit.")
        if not self.segments and not self.rooms:
            raise ValueError("Draw at least one wall or room before exporting DXF.")
        if self.pixels_per_mm is not None and (
            not math.isfinite(self.pixels_per_mm) or self.pixels_per_mm <= 0
        ):
            raise ValueError("pixels_per_mm must be finite and greater than zero.")

        point_count = 2 * len(self.segments) + sum(len(room.vertices_px) for room in self.rooms)
        if point_count > 100_000:
            raise ValueError("DXF export is limited to 100,000 geometry points.")

        identifiers: set[str] = set()
        for item in [*self.segments, *self.rooms]:
            if item.id in identifiers:
                raise ValueError("Geometry IDs must be unique within the export.")
            identifiers.add(item.id)

        def check_point(point: PointPx) -> None:
            if point.x > self.source_width or point.y > self.source_height:
                raise ValueError("Geometry coordinates must remain inside the source image.")

        for segment in self.segments:
            check_point(segment.start_px)
            check_point(segment.end_px)
            if math.hypot(
                segment.end_px.x - segment.start_px.x,
                segment.end_px.y - segment.start_px.y,
            ) <= 1e-9:
                raise ValueError(f"Wall {segment.id} has zero length.")

        for room in self.rooms:
            for point in room.vertices_px:
                check_point(point)
            if _polygon_area(room.vertices_px) <= 1e-9:
                raise ValueError(f"Room {room.id} has zero area.")
            if _polygon_self_intersects(room.vertices_px):
                raise ValueError(f"Room {room.id} self-intersects.")
        return self


def _polygon_area(points: list[PointPx]) -> float:
    return abs(sum(
        points[index].x * points[(index + 1) % len(points)].y
        - points[(index + 1) % len(points)].x * points[index].y
        for index in range(len(points))
    )) / 2


def _orientation(a: PointPx, b: PointPx, c: PointPx) -> float:
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _on_segment(a: PointPx, b: PointPx, p: PointPx) -> bool:
    return (
        min(a.x, b.x) - 1e-9 <= p.x <= max(a.x, b.x) + 1e-9
        and min(a.y, b.y) - 1e-9 <= p.y <= max(a.y, b.y) + 1e-9
    )


def _segments_intersect(a: PointPx, b: PointPx, c: PointPx, d: PointPx) -> bool:
    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    if ((o1 > 1e-9 and o2 < -1e-9) or (o1 < -1e-9 and o2 > 1e-9)) and (
        (o3 > 1e-9 and o4 < -1e-9) or (o3 < -1e-9 and o4 > 1e-9)
    ):
        return True
    return (
        (abs(o1) <= 1e-9 and _on_segment(a, b, c))
        or (abs(o2) <= 1e-9 and _on_segment(a, b, d))
        or (abs(o3) <= 1e-9 and _on_segment(c, d, a))
        or (abs(o4) <= 1e-9 and _on_segment(c, d, b))
    )


def _polygon_self_intersects(points: list[PointPx]) -> bool:
    count = len(points)
    for first in range(count):
        a, b = points[first], points[(first + 1) % count]
        for second in range(first + 1, count):
            # Adjacent edges share a legitimate endpoint, including first/last.
            if second == first or second == (first + 1) % count or first == (second + 1) % count:
                continue
            c, d = points[second], points[(second + 1) % count]
            if _segments_intersect(a, b, c, d):
                return True
    return False


def _number(value: float) -> str:
    if abs(value) < 0.0000005:
        value = 0.0
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _pair(code: int, value: object) -> str:
    return f"{code}\\n{value}\\n"


def export_manual_geometry_dxf(request: ManualGeometryDXFRequest) -> bytes:
    """Build an ASCII R2000 DXF; calibrated coordinates are millimetres."""
    calibrated = request.pixels_per_mm is not None
    scale = request.pixels_per_mm or 1.0

    def cad_point(point: PointPx) -> tuple[str, str]:
        # Source images use top-left origin and downward-positive Y. CAD uses
        # bottom-left origin and upward-positive Y.
        x = point.x / scale
        y = (request.source_height - point.y) / scale
        return _number(x), _number(y)

    chunks = [
        _pair(999, "Planline user-authored 2D geometry; not inferred CAD."),
        _pair(0, "SECTION"), _pair(2, "HEADER"),
        _pair(9, "$ACADVER"), _pair(1, "AC1015"),
        _pair(9, "$INSUNITS"), _pair(70, 4 if calibrated else 0),
        _pair(9, "$MEASUREMENT"), _pair(70, 1 if calibrated else 0),
        _pair(9, "$LUNITS"), _pair(70, 2),
        _pair(9, "$LUPREC"), _pair(70, 3),
        _pair(999, "Calibrated millimetres use a user-supplied two-point reference; it is not verified."),
        _pair(0, "ENDSEC"),
        _pair(0, "SECTION"), _pair(2, "TABLES"),
        _pair(0, "TABLE"), _pair(2, "LAYER"), _pair(70, 2),
        _pair(0, "LAYER"), _pair(2, "WALLS"), _pair(70, 0), _pair(62, 7), _pair(6, "CONTINUOUS"),
        _pair(0, "LAYER"), _pair(2, "ROOMS"), _pair(70, 0), _pair(62, 3), _pair(6, "CONTINUOUS"),
        _pair(0, "ENDTAB"), _pair(0, "ENDSEC"),
        _pair(0, "SECTION"), _pair(2, "ENTITIES"),
    ]

    for segment in request.segments:
        x1, y1 = cad_point(segment.start_px)
        x2, y2 = cad_point(segment.end_px)
        chunks.extend([
            _pair(0, "LINE"), _pair(8, "WALLS"),
            _pair(10, x1), _pair(20, y1), _pair(30, "0"),
            _pair(11, x2), _pair(21, y2), _pair(31, "0"),
        ])

    for room in request.rooms:
        chunks.extend([
            _pair(0, "LWPOLYLINE"), _pair(8, "ROOMS"),
            _pair(90, len(room.vertices_px)), _pair(70, 1),
        ])
        for point in room.vertices_px:
            x, y = cad_point(point)
            chunks.extend([_pair(10, x), _pair(20, y)])

    chunks.extend([_pair(0, "ENDSEC"), _pair(0, "EOF")])
    return "".join(chunks).encode("ascii")

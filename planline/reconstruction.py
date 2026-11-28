"""Conservative, dimension-constrained wall-edge reconstruction.

The detector supplies candidate wall regions. This module only turns those
regions into editable draft linework after the user has verified a complete
linear dimension string and explicitly confirmed its dimension-line/wall-pair
association. It does not infer rooms, openings, diagonal walls or topology.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .association import associate_dimensions
from .dimensions import interpret_dimension_text


class ReconstructionDetection(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    class_name: str = Field(min_length=1, max_length=40)
    confidence: float = Field(ge=0, le=1)
    bbox: dict[str, float]


class ConfirmedDimensionInput(BaseModel):
    detection_id: str = Field(min_length=1, max_length=100)
    raw_text: str = Field(default="", max_length=128)
    text_verified: bool = False
    association_confirmed: bool = False
    dimension_line_id: str | None = Field(default=None, max_length=100)
    wall_ids: list[str] = Field(default_factory=list, max_length=2)


class WallReconstructionRequest(BaseModel):
    source_width: int = Field(ge=1, le=25_000_000)
    source_height: int = Field(ge=1, le=25_000_000)
    source_page_index: int = Field(default=0, ge=0, le=10_000)
    detections: list[ReconstructionDetection] = Field(min_length=1, max_length=5_000)
    dimensions: list[ConfirmedDimensionInput] = Field(default_factory=list, max_length=500)
    scale_consistency_percent: float = Field(default=5.0, gt=0, le=15)

    @model_validator(mode="after")
    def validate_source(self) -> "WallReconstructionRequest":
        if self.source_width * self.source_height > 25_000_000:
            raise ValueError("Source image exceeds the 25-megapixel reconstruction limit.")
        ids = [item.id for item in self.detections]
        if len(ids) != len(set(ids)):
            raise ValueError("Detection IDs must be unique.")
        by_id = {item.id: item for item in self.detections}
        dimension_ids = [item.detection_id for item in self.dimensions]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError(
                "Each detected dimension value can only be used once in a reconstruction."
            )
        for dimension_id in dimension_ids:
            detection = by_id.get(dimension_id)
            if detection is None or detection.class_name != "dimension_value":
                raise ValueError(
                    f"Dimension {dimension_id} must reference an existing dimension-value detection."
                )
        for item in self.detections:
            box = item.bbox
            try:
                x1, y1, x2, y2 = (float(box[key]) for key in ("x1", "y1", "x2", "y2"))
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Detection {item.id} has an invalid bounding box.") from exc
            if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
                raise ValueError(f"Detection {item.id} has non-finite coordinates.")
            if x1 < 0 or y1 < 0 or x2 > self.source_width or y2 > self.source_height:
                raise ValueError(f"Detection {item.id} lies outside the source image.")
            if x2 <= x1 or y2 <= y1:
                raise ValueError(f"Detection {item.id} has an empty bounding box.")
        return self


def _rect(detection: ReconstructionDetection) -> dict[str, float]:
    box = detection.bbox
    x1, y1, x2, y2 = (float(box[key]) for key in ("x1", "y1", "x2", "y2"))
    return {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "width": x2 - x1, "height": y2 - y1,
    }


def _axis(rect: dict[str, float]) -> str | None:
    if rect["width"] >= rect["height"] * 1.5:
        return "horizontal"
    if rect["height"] >= rect["width"] * 1.5:
        return "vertical"
    return None


def _verified_measurements(
    request: WallReconstructionRequest,
) -> tuple[list[dict[str, Any]], list[str]]:
    detections = [item.model_dump() for item in request.detections]
    by_id = {item.id: item for item in request.detections}
    associations = {
        item["dimension_value_id"]: item
        for item in associate_dimensions(detections)
    }
    measurements: list[dict[str, Any]] = []
    skipped: list[str] = []
    seen_spans: set[tuple[str, tuple[str, str]]] = set()

    for entry in request.dimensions:
        if not (entry.text_verified and entry.association_confirmed):
            skipped.append(entry.detection_id)
            continue
        if not entry.raw_text.strip():
            raise ValueError(
                f"Dimension {entry.detection_id} is marked verified but has no transcription."
            )
        interpretation = interpret_dimension_text(entry.raw_text)
        if interpretation.get("status") != "parsed" or interpretation.get("dimension_type") != "linear":
            reason = interpretation.get("reason") or "Use a readable linear dimension with an explicit unit."
            raise ValueError(
                f"Dimension {entry.detection_id} cannot constrain geometry: {reason}"
            )
        value_mm = float(interpretation["value_mm"])
        if not math.isfinite(value_mm) or value_mm <= 0:
            raise ValueError(f"Dimension {entry.detection_id} is not a positive linear measurement.")
        if not entry.dimension_line_id or len(entry.wall_ids) != 2 or entry.wall_ids[0] == entry.wall_ids[1]:
            raise ValueError(
                f"Dimension {entry.detection_id} needs one confirmed line and two distinct bounding walls."
            )

        line_detection = by_id.get(entry.dimension_line_id)
        wall_detections = [by_id.get(wall_id) for wall_id in entry.wall_ids]
        if line_detection is None or line_detection.class_name != "dimension_line":
            raise ValueError(f"Dimension {entry.detection_id} refers to a missing dimension line.")
        if any(wall is None or wall.class_name != "wall" for wall in wall_detections):
            raise ValueError(f"Dimension {entry.detection_id} must be bounded by two detected walls.")

        association = associations.get(entry.detection_id)
        if association is None:
            raise ValueError(f"Dimension {entry.detection_id} has no geometric association candidates.")
        selected_line = next(
            (candidate for candidate in association["candidate_lines"]
             if candidate["dimension_line_id"] == entry.dimension_line_id),
            None,
        )
        selected_span = next(
            (span for span in (selected_line or {}).get("wall_spans", [])
             if set(span["wall_ids"]) == set(entry.wall_ids)),
            None,
        )
        if selected_span is None:
            raise ValueError(
                f"The confirmed wall pair for dimension {entry.detection_id} no longer matches "
                "the drawing's geometric candidates. Recheck the association."
            )

        orientation = selected_line["orientation"]
        span_axis = "x" if orientation == "horizontal" else "y"
        key = (span_axis, tuple(sorted(entry.wall_ids)))
        if key in seen_spans:
            raise ValueError(
                f"The same wall gap has been assigned to more than one verified dimension ({entry.detection_id})."
            )
        seen_spans.add(key)

        span_px = float(selected_span["span_px"])
        pixels_per_mm = span_px / value_mm
        if not math.isfinite(pixels_per_mm) or pixels_per_mm <= 0:
            raise ValueError(f"Dimension {entry.detection_id} produces an invalid scale.")
        measurements.append({
            "detection_id": entry.detection_id,
            "raw_text": entry.raw_text.strip(),
            "value_mm": round(value_mm, 3),
            "unit": interpretation.get("unit"),
            "dimension_line_id": entry.dimension_line_id,
            "wall_ids": list(entry.wall_ids),
            "orientation": orientation,
            "axis": span_axis,
            "span_px": round(span_px, 3),
            "pixels_per_mm": pixels_per_mm,
            "association_score": selected_span.get("assignment_score"),
        })

    if not measurements:
        raise ValueError(
            "Verify at least one dimension transcription and its matching dimension line and wall pair."
        )
    return measurements, skipped


def _axis_scale(measurements: list[dict[str, Any]], axis: str, tolerance_percent: float) -> float:
    values = [item["pixels_per_mm"] for item in measurements if item["axis"] == axis]
    if not values:
        orientation = "horizontal" if axis == "x" else "vertical"
        raise ValueError(
            f"A confirmed {orientation} dimension is required to establish the {axis.upper()} scale. "
            "Verify a dimension whose line runs in that direction."
        )
    centre = median(values)
    conflicts = [
        item for item in measurements
        if item["axis"] == axis
        and abs(item["pixels_per_mm"] - centre) / centre * 100 > tolerance_percent
    ]
    if conflicts:
        details = ", ".join(
            f"{item['detection_id']} ({item['pixels_per_mm']:.6f} px/mm)"
            for item in conflicts
        )
        raise ValueError(
            f"Confirmed {axis.upper()} dimensions disagree by more than "
            f"{tolerance_percent:g}%. Check the text, wall pairs or scan distortion: {details}."
        )
    return float(centre)


def _junction_candidates(
    segments: list[dict[str, Any]],
    tolerance_px: float = 2.0,
) -> list[dict[str, Any]]:
    """Report directly near-coincident endpoints without changing linework.

    Each result is a pairwise observation. Avoiding transitive clustering
    prevents a chain of individually close endpoints from being presented as
    one junction when the endpoints at either end are farther apart than the
    configured tolerance. A multi-wall junction may therefore produce several
    pairwise review candidates.
    """
    endpoints: list[dict[str, Any]] = []
    for segment in segments:
        for endpoint_name in ("start_px", "end_px"):
            point = segment[endpoint_name]
            endpoints.append({
                "segment_id": segment["id"],
                "source_detection_id": segment["source_detection_id"],
                "endpoint": endpoint_name,
                "x": float(point["x"]),
                "y": float(point["y"]),
            })

    candidates: list[dict[str, Any]] = []
    buckets: dict[tuple[int, int], list[int]] = {}
    for index, endpoint in enumerate(endpoints):
        cell_x = math.floor(endpoint["x"] / tolerance_px)
        cell_y = math.floor(endpoint["y"] / tolerance_px)
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                for other_index in buckets.get((cell_x + offset_x, cell_y + offset_y), []):
                    other = endpoints[other_index]
                    if other["source_detection_id"] == endpoint["source_detection_id"]:
                        continue
                    distance = math.hypot(
                        endpoint["x"] - other["x"],
                        endpoint["y"] - other["y"],
                    )
                    if distance > tolerance_px:
                        continue
                    candidates.append({
                        "point_px": {
                            "x": round((endpoint["x"] + other["x"]) / 2, 2),
                            "y": round((endpoint["y"] + other["y"]) / 2, 2),
                        },
                        "source_detection_ids": sorted({
                            endpoint["source_detection_id"],
                            other["source_detection_id"],
                        }),
                        "segment_ids": sorted({
                            endpoint["segment_id"],
                            other["segment_id"],
                        }),
                        "endpoints": [
                            {
                                "segment_id": item["segment_id"],
                                "endpoint": item["endpoint"],
                                "original_point_px": {
                                    "x": item["x"],
                                    "y": item["y"],
                                },
                            }
                            for item in sorted((endpoint, other), key=lambda value: (value["segment_id"], value["endpoint"]))
                        ],
                        "endpoint_count": 2,
                        "status": "candidate_requires_review",
                        "review_status": "pending",
                    })
        buckets.setdefault((cell_x, cell_y), []).append(index)

    candidates.sort(key=lambda item: (
        item["point_px"]["y"],
        item["point_px"]["x"],
        item["source_detection_ids"],
        item["segment_ids"],
    ))
    return candidates


def _opening_candidates(
    wall_detections: list[ReconstructionDetection],
    pixels_per_mm_x: float,
    pixels_per_mm_y: float,
    minimum_width_mm: float = 450.0,
    maximum_width_mm: float = 3000.0,
    minimum_overlap_ratio: float = 0.65,
) -> list[dict[str, Any]]:
    """Suggest possible openings between aligned wall detections.

    This is a deliberately conservative gap heuristic, not a door/window
    classifier. It only reports candidates; it never changes wall geometry.
    """
    walls = [
        (detection, _rect(detection), _axis(_rect(detection)))
        for detection in wall_detections
    ]
    candidates: list[dict[str, Any]] = []
    for index, (first_detection, first, orientation) in enumerate(walls):
        if orientation is None:
            continue
        for second_detection, second, second_orientation in walls[index + 1:]:
            if second_orientation != orientation:
                continue
            if orientation == "horizontal":
                left_detection, left, right_detection, right = (
                    (first_detection, first, second_detection, second)
                    if first["x1"] <= second["x1"]
                    else (second_detection, second, first_detection, first)
                )
                overlap_start = max(left["y1"], right["y1"])
                overlap_end = min(left["y2"], right["y2"])
                overlap = overlap_end - overlap_start
                overlap_ratio = overlap / min(left["height"], right["height"])
                gap_px = right["x1"] - left["x2"]
                scale = pixels_per_mm_x
                start = {"x": left["x2"], "y": (overlap_start + overlap_end) / 2}
                end = {"x": right["x1"], "y": (overlap_start + overlap_end) / 2}
                gap_bbox = {
                    "x1": left["x2"], "y1": overlap_start,
                    "x2": right["x1"], "y2": overlap_end,
                }
                axis = "x"
            else:
                top_detection, top, bottom_detection, bottom = (
                    (first_detection, first, second_detection, second)
                    if first["y1"] <= second["y1"]
                    else (second_detection, second, first_detection, first)
                )
                overlap_start = max(top["x1"], bottom["x1"])
                overlap_end = min(top["x2"], bottom["x2"])
                overlap = overlap_end - overlap_start
                overlap_ratio = overlap / min(top["width"], bottom["width"])
                gap_px = bottom["y1"] - top["y2"]
                scale = pixels_per_mm_y
                start = {"x": (overlap_start + overlap_end) / 2, "y": top["y2"]}
                end = {"x": (overlap_start + overlap_end) / 2, "y": bottom["y1"]}
                gap_bbox = {
                    "x1": overlap_start, "y1": top["y2"],
                    "x2": overlap_end, "y2": bottom["y1"],
                }
                axis = "y"

            if overlap <= 0 or overlap_ratio < minimum_overlap_ratio or gap_px <= 0:
                continue
            width_mm = gap_px / scale
            if not minimum_width_mm <= width_mm <= maximum_width_mm:
                continue

            pair_ids = {first_detection.id, second_detection.id}
            blocked = False
            for other_detection, other, other_orientation in walls:
                if other_detection.id in pair_ids or other_orientation != orientation:
                    continue
                if orientation == "horizontal":
                    crosses_gap = other["x1"] < gap_bbox["x2"] and other["x2"] > gap_bbox["x1"]
                    overlaps_wall = min(other["y2"], gap_bbox["y2"]) > max(other["y1"], gap_bbox["y1"])
                else:
                    crosses_gap = other["y1"] < gap_bbox["y2"] and other["y2"] > gap_bbox["y1"]
                    overlaps_wall = min(other["x2"], gap_bbox["x2"]) > max(other["x1"], gap_bbox["x1"])
                if crosses_gap and overlaps_wall:
                    blocked = True
                    break
            if blocked:
                continue

            wall_ids = sorted(pair_ids)
            candidates.append({
                "id": f"opening-candidate-{len(candidates) + 1:03d}",
                "wall_ids": wall_ids,
                "axis": axis,
                "start_px": {key: round(value, 2) for key, value in start.items()},
                "end_px": {key: round(value, 2) for key, value in end.items()},
                "gap_bbox": {key: round(value, 2) for key, value in gap_bbox.items()},
                "width_mm": round(width_mm, 2),
                "status": "candidate_requires_review",
                "review_status": "pending",
            })
    candidates.sort(key=lambda item: (
        item["gap_bbox"]["y1"], item["gap_bbox"]["x1"], item["wall_ids"]
    ))
    for index, candidate in enumerate(candidates, start=1):
        candidate["id"] = f"opening-candidate-{index:03d}"
    return candidates


def reconstruct_wall_edges(
    request: WallReconstructionRequest,
) -> dict[str, Any]:
    """Create editable wall-face line candidates using confirmed X/Y dimensions."""
    measurements, skipped_dimensions = _verified_measurements(request)
    px_per_mm_x = _axis_scale(measurements, "x", request.scale_consistency_percent)
    px_per_mm_y = _axis_scale(measurements, "y", request.scale_consistency_percent)

    wall_detections = [item for item in request.detections if item.class_name == "wall"]
    segments: list[dict[str, Any]] = []
    skipped_walls: list[dict[str, str]] = []

    for wall in wall_detections:
        rect = _rect(wall)
        orientation = _axis(rect)
        if orientation is None:
            skipped_walls.append({
                "detection_id": wall.id,
                "reason": "The wall candidate is not clearly horizontal or vertical.",
            })
            continue

        if orientation == "horizontal":
            edges = [
                ({"x": rect["x1"], "y": rect["y1"]}, {"x": rect["x2"], "y": rect["y1"]}),
                ({"x": rect["x1"], "y": rect["y2"]}, {"x": rect["x2"], "y": rect["y2"]}),
            ]
        else:
            edges = [
                ({"x": rect["x1"], "y": rect["y1"]}, {"x": rect["x1"], "y": rect["y2"]}),
                ({"x": rect["x2"], "y": rect["y1"]}, {"x": rect["x2"], "y": rect["y2"]}),
            ]

        for face_index, (start, end) in enumerate(edges, start=1):
            segments.append({
                "id": f"reconstructed-wall-{len(segments) + 1:04d}",
                "type": "wall_segment",
                "start_px": start,
                "end_px": end,
                "source_page_index": request.source_page_index,
                "created_by_reconstruction": True,
                "source_detection_id": wall.id,
                "detector_confidence": wall.confidence,
                "wall_orientation": orientation,
                "wall_face_index": face_index,
            })

    if not segments:
        raise ValueError(
            "No axis-aligned wall candidates could be converted to wall edges. "
            "The current detector does not reconstruct diagonal walls."
        )

    junction_candidates = _junction_candidates(segments)
    opening_candidates = _opening_candidates(wall_detections, px_per_mm_x, px_per_mm_y)
    return {
        "status": "draft",
        "geometry_kind": "detected_wall_face_edges",
        "segments": segments,
        "junction_candidates": junction_candidates,
        "opening_candidates": opening_candidates,
        "junction_tolerance_px": 2.0,
        "scale": {
            "pixels_per_mm_x": round(px_per_mm_x, 9),
            "pixels_per_mm_y": round(px_per_mm_y, 9),
            "source": "confirmed_dimension_to_wall_associations",
        },
        "measurements": [
            {**item, "pixels_per_mm": round(item["pixels_per_mm"], 9)}
            for item in measurements
        ],
        "skipped_dimensions": skipped_dimensions,
        "skipped_walls": skipped_walls,
        "wall_regions_used": len({item["source_detection_id"] for item in segments}),
        "warnings": [
            "This is editable draft wall-face linework, not a verified construction drawing.",
            "Each detected wall bounding box becomes two parallel face lines. Near-coincident endpoints include source endpoint references and can be joined only after explicit review; closed cycles can then be offered as room outlines, but no automatic topology repair or room creation is applied.",
            "Possible openings are heuristic gap candidates only; the reviewer must classify them. Doors, windows, room boundaries, diagonal walls and missing wall regions are not inferred automatically.",
            "X and Y scales are derived independently from confirmed dimensions. Local perspective, skew and paper distortion are not rectified.",
            "Inspect every generated edge against the source scan before relying on the DXF.",
        ],
    }

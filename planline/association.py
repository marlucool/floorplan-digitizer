"""Geometric hypotheses linking dimension labels, dimension lines and wall spans.

This module deliberately ranks candidates rather than making authoritative
assignments. The detector supplies axis-aligned boxes, not vector geometry;
all scores are geometric fit scores, not probabilities or measurement
confidence. A person must confirm both links in the review UI.
"""
from __future__ import annotations

from math import exp, isfinite
from typing import Any

MAX_CANDIDATES = 3
ORIENTATION_RATIO = 1.25


def _rect(detection: dict[str, Any]) -> dict[str, float] | None:
    bbox = detection.get("bbox")
    if not isinstance(bbox, dict):
        return None
    try:
        x1, y1, x2, y2 = (float(bbox[key]) for key in ("x1", "y1", "x2", "y2"))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not all(isfinite(value) for value in (x1, y1, x2, y2)):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "width": x2 - x1, "height": y2 - y1,
            "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2}


def _orientation(rect: dict[str, float]) -> str | None:
    """Infer an axis only when the detector box is sufficiently elongated."""
    if rect["width"] >= rect["height"] * ORIENTATION_RATIO:
        return "horizontal"
    if rect["height"] >= rect["width"] * ORIENTATION_RATIO:
        return "vertical"
    return None


def _interval_gap(a1: float, a2: float, b1: float, b2: float) -> float:
    return max(0.0, b1 - a2, a1 - b2)


def _fit_status(scores: list[float], minimum: float = 0.22) -> str:
    if not scores or scores[0] < minimum:
        return "unmatched"
    if len(scores) > 1 and scores[0] - scores[1] <= max(0.07, scores[0] * 0.12):
        return "ambiguous"
    return "candidate"


def _score_value_to_line(
    value_rect: dict[str, float],
    line_rect: dict[str, float],
    orientation: str,
) -> tuple[float, dict[str, float]]:
    if orientation == "horizontal":
        line_start, line_end = line_rect["x1"], line_rect["x2"]
        value_start, value_end = value_rect["x1"], value_rect["x2"]
        value_centre = value_rect["cx"]
        perpendicular_gap = _interval_gap(
            value_rect["y1"], value_rect["y2"], line_rect["y1"], line_rect["y2"]
        )
        perpendicular_scale = max(value_rect["height"], line_rect["height"], 8.0)
    else:
        line_start, line_end = line_rect["y1"], line_rect["y2"]
        value_start, value_end = value_rect["y1"], value_rect["y2"]
        value_centre = value_rect["cy"]
        perpendicular_gap = _interval_gap(
            value_rect["x1"], value_rect["x2"], line_rect["x1"], line_rect["x2"]
        )
        perpendicular_scale = max(value_rect["width"], line_rect["width"], 8.0)

    line_length = max(line_end - line_start, 1.0)
    projection_outside = max(0.0, line_start - value_centre, value_centre - line_end)
    projection_error = projection_outside / line_length
    overlap = max(0.0, min(value_end, line_end) - max(value_start, line_start))
    overlap_ratio = min(1.0, overlap / max(min(value_end - value_start, line_length), 1.0))
    perpendicular_error = perpendicular_gap / perpendicular_scale

    # Exponential ranking is intentionally uncalibrated: it compares candidate
    # fit within this drawing and must never be displayed as OCR confidence.
    score = exp(
        -2.5 * projection_error
        -1.5 * perpendicular_error
        -0.8 * (1.0 - overlap_ratio)
    )
    evidence = {
        "projection_error_ratio": round(projection_error, 4),
        "perpendicular_gap_px": round(perpendicular_gap, 2),
        "projection_overlap": round(overlap_ratio, 4),
    }
    return round(max(0.0, min(1.0, score)), 4), evidence


def _wall_span_candidates(
    line: dict[str, Any],
    line_rect: dict[str, float],
    orientation: str,
    walls: list[tuple[dict[str, Any], dict[str, float]]],
) -> list[dict[str, Any]]:
    """Find wall pairs whose facing edges bracket the detected dimension line."""
    line_start, line_end = (
        (line_rect["x1"], line_rect["x2"])
        if orientation == "horizontal"
        else (line_rect["y1"], line_rect["y2"])
    )
    line_centre = (line_start + line_end) / 2
    line_length = max(line_end - line_start, 1.0)
    perpendicular_centre = line_rect["cy"] if orientation == "horizontal" else line_rect["cx"]
    required_wall_orientation = "vertical" if orientation == "horizontal" else "horizontal"

    eligible: list[tuple[dict[str, Any], dict[str, float], float, float]] = []
    for wall, rect in walls:
        if _orientation(rect) != required_wall_orientation:
            continue
        if orientation == "horizontal":
            centre = rect["cx"]
            inner_edge = rect["x2"] if centre < line_centre else rect["x1"]
            low, high = rect["y1"], rect["y2"]
        else:
            centre = rect["cy"]
            inner_edge = rect["y2"] if centre < line_centre else rect["y1"]
            low, high = rect["x1"], rect["x2"]
        perpendicular_gap = _interval_gap(
            perpendicular_centre, perpendicular_centre, low, high
        )
        eligible.append((wall, rect, inner_edge, perpendicular_gap))

    before = [entry for entry in eligible if (
        (entry[1]["cx"] < line_centre) if orientation == "horizontal"
        else (entry[1]["cy"] < line_centre)
    )]
    after = [entry for entry in eligible if (
        (entry[1]["cx"] > line_centre) if orientation == "horizontal"
        else (entry[1]["cy"] > line_centre)
    )]

    candidates: list[dict[str, Any]] = []
    for first in before:
        for second in after:
            if orientation == "horizontal":
                span_start, span_end = first[2], second[2]
            else:
                span_start, span_end = first[2], second[2]
            span_length = span_end - span_start
            if span_length <= 0 or not (span_start < line_centre < span_end):
                continue

            endpoint_residual = (
                abs(span_start - line_start) + abs(span_end - line_end)
            ) / 2.0
            endpoint_error = endpoint_residual / line_length
            perpendicular_offset = max(first[3], second[3])
            perpendicular_error = perpendicular_offset / line_length
            score = exp(-3.0 * endpoint_error - 1.2 * perpendicular_error)

            first_id = first[0].get("id")
            second_id = second[0].get("id")
            if not isinstance(first_id, str) or not isinstance(second_id, str):
                continue
            candidates.append({
                "wall_ids": [first_id, second_id],
                "orientation": orientation,
                "method": "between_vertical_walls" if orientation == "horizontal"
                          else "between_horizontal_walls",
                "span_px": round(span_length, 2),
                "endpoint_residual_px": round(endpoint_residual, 2),
                "perpendicular_offset_px": round(perpendicular_offset, 2),
                "score": round(max(0.0, min(1.0, score)), 4),
                "evidence": (
                    "Facing wall-box edges bracket the dimension line along its axis; "
                    "endpoint alignment and perpendicular offset determine ranking."
                ),
            })

    candidates.sort(key=lambda item: (-item["score"], item["wall_ids"]))
    return candidates[:MAX_CANDIDATES]


def associate_dimensions(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ranked, unconfirmed value→line→wall-span hypotheses.

    The supported geometry is axis-aligned. Diagonal, curved, rotated or
    heavily skewed cases are not forced into horizontal/vertical assignments.
    """
    if not isinstance(detections, list):
        return []

    lines: list[tuple[dict[str, Any], dict[str, float], str]] = []
    walls: list[tuple[dict[str, Any], dict[str, float]]] = []
    values: list[tuple[dict[str, Any], dict[str, float]]] = []

    for detection in detections:
        if not isinstance(detection, dict):
            continue
        rect = _rect(detection)
        if rect is None:
            continue
        kind = detection.get("class_name")
        if kind == "dimension_line":
            orientation = _orientation(rect)
            if orientation:
                lines.append((detection, rect, orientation))
        elif kind == "wall":
            walls.append((detection, rect))
        elif kind == "dimension_value":
            values.append((detection, rect))

    results: list[dict[str, Any]] = []
    for value, value_rect in values:
        value_id = value.get("id")
        if not isinstance(value_id, str):
            continue
        line_candidates: list[dict[str, Any]] = []
        for line, line_rect, orientation in lines:
            score, evidence = _score_value_to_line(value_rect, line_rect, orientation)
            if score < 0.04:
                continue
            spans = _wall_span_candidates(line, line_rect, orientation, walls)
            line_id = line.get("id")
            if not isinstance(line_id, str):
                continue
            line_candidates.append({
                "dimension_line_id": line_id,
                "orientation": orientation,
                "score": score,
                "evidence": evidence,
                "wall_spans": spans,
                "wall_span_status": _fit_status(
                    [item["score"] for item in spans], minimum=0.30
                ),
            })

        line_candidates.sort(key=lambda item: (-item["score"], item["dimension_line_id"]))
        line_candidates = line_candidates[:MAX_CANDIDATES]
        results.append({
            "dimension_value_id": value_id,
            "status": _fit_status([item["score"] for item in line_candidates]),
            "candidate_lines": line_candidates,
            "confirmed": False,
        })

    return results

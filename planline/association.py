
"""Reviewable geometric hypotheses for dimension text → line → wall-span links.

The original CLI used a useful gap model: sort parallel walls, examine the
spaces between them, and relate dimension-text centres to those spaces. This
module retains that geometric idea but makes it local to each dimension line,
uses wall-box faces instead of wall centres, checks perpendicular overlap,
and globally assigns each detected dimension line to at most one text box.

All scores are relative candidate rankings, never probabilities. No candidate
is confirmed here and no pixel-to-unit scale is inferred.
"""
from __future__ import annotations

from math import exp, isfinite
from typing import Any

MAX_CANDIDATES = 3
MAX_ELIGIBLE_WALLS = 40
ORIENTATION_RATIO = 1.5
MIN_LINE_SCORE = 0.04
MIN_GLOBAL_ASSIGNMENT_SCORE = 0.28


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
    return {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "width": x2 - x1, "height": y2 - y1,
        "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2,
    }


def _orientation(rect: dict[str, float]) -> str | None:
    """Classify only clearly elongated boxes; near-square boxes stay unresolved."""
    if rect["width"] >= rect["height"] * ORIENTATION_RATIO:
        return "horizontal"
    if rect["height"] >= rect["width"] * ORIENTATION_RATIO:
        return "vertical"
    return None


def _axis_values(rect: dict[str, float], orientation: str) -> tuple[float, float, float]:
    if orientation == "horizontal":
        return rect["cx"], rect["x1"], rect["x2"]
    return rect["cy"], rect["y1"], rect["y2"]


def _perpendicular_values(rect: dict[str, float], orientation: str) -> tuple[float, float, float]:
    if orientation == "horizontal":
        return rect["cy"], rect["y1"], rect["y2"]
    return rect["cx"], rect["x1"], rect["x2"]


def _interval_gap(a1: float, a2: float, b1: float, b2: float) -> float:
    return max(0.0, b1 - a2, a1 - b2)


def _point_interval_gap(point: float, start: float, end: float) -> float:
    return max(0.0, start - point, point - end)


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
) -> tuple[float, dict[str, float]] | None:
    """Score shared axis, projected text position and annotation-band proximity."""
    value_centre, value_start, value_end = _axis_values(value_rect, orientation)
    line_centre, line_start, line_end = _axis_values(line_rect, orientation)
    value_perp, value_perp_start, value_perp_end = _perpendicular_values(value_rect, orientation)
    line_perp, line_perp_start, line_perp_end = _perpendicular_values(line_rect, orientation)

    line_length = max(line_end - line_start, 1.0)
    value_length = max(value_end - value_start, 1.0)
    line_thickness = max(line_perp_end - line_perp_start, 1.0)
    value_thickness = max(value_perp_end - value_perp_start, 1.0)

    projection_outside = max(0.0, line_start - value_centre, value_centre - line_end)
    projection_margin = max(value_length * 0.75, line_length * 0.08, 8.0)
    perpendicular_gap = _interval_gap(
        value_perp_start, value_perp_end, line_perp_start, line_perp_end
    )
    perpendicular_tolerance = max(value_thickness * 1.5, line_thickness * 6.0, 12.0)

    # Reject text that is clearly outside this line's projection or annotation band.
    if projection_outside > projection_margin or perpendicular_gap > perpendicular_tolerance:
        return None

    projection_error = projection_outside / max(projection_margin, 1.0)
    perpendicular_error = perpendicular_gap / perpendicular_tolerance
    overlap = max(0.0, min(value_end, line_end) - max(value_start, line_start))
    overlap_ratio = min(1.0, overlap / max(min(value_length, line_length), 1.0))
    centre_alignment_error = abs(value_centre - line_centre) / max(line_length / 2 + projection_margin, 1.0)

    score = exp(
        -1.2 * projection_error
        -1.35 * perpendicular_error
        -0.65 * (1.0 - overlap_ratio)
        -0.25 * centre_alignment_error
    )
    return round(max(0.0, min(1.0, score)), 4), {
        "projection_error_ratio": round(projection_error, 4),
        "perpendicular_gap_px": round(perpendicular_gap, 2),
        "projection_overlap": round(overlap_ratio, 4),
        "centre_alignment_error": round(centre_alignment_error, 4),
    }


def _wall_span_candidates(
    value_rect: dict[str, float],
    line_rect: dict[str, float],
    orientation: str,
    walls: list[tuple[dict[str, Any], dict[str, float]]],
) -> list[dict[str, Any]]:
    """Rank spaces between parallel walls that the dimension line could measure.

    This borrows the old implementation's gap-based reasoning but evaluates
    the walls against this line's local perpendicular corridor. It can retain
    an outer/overall span as an alternative, with a penalty for intervening
    walls, instead of assuming that only globally adjacent walls are valid.
    """
    line_centre, line_start, line_end = _axis_values(line_rect, orientation)
    text_centre, text_start, text_end = _axis_values(value_rect, orientation)
    line_perp, line_perp_start, line_perp_end = _perpendicular_values(line_rect, orientation)
    line_length = max(line_end - line_start, 1.0)
    line_thickness = max(line_perp_end - line_perp_start, 1.0)
    required_wall_orientation = "vertical" if orientation == "horizontal" else "horizontal"

    eligible: list[tuple[dict[str, Any], dict[str, float], float, float, float]] = []
    for wall, rect in walls:
        if _orientation(rect) != required_wall_orientation:
            continue
        wall_axis_centre, _, _ = _axis_values(rect, orientation)
        wall_perp_centre, wall_perp_start, wall_perp_end = _perpendicular_values(rect, orientation)
        wall_thickness = max(wall_perp_end - wall_perp_start, 1.0)
        perpendicular_gap = _point_interval_gap(line_perp, wall_perp_start, wall_perp_end)
        # Local tolerance scales with the detected line and this wall's thickness,
        # not with the full image size (the legacy 15% snap radius was too broad).
        local_tolerance = max(6.0, line_thickness * 3.0, wall_thickness * 1.5)
        if perpendicular_gap > local_tolerance:
            continue

        if orientation == "horizontal":
            inner_face = rect["x2"] if wall_axis_centre < line_centre else rect["x1"]
        else:
            inner_face = rect["y2"] if wall_axis_centre < line_centre else rect["y1"]
        eligible.append((wall, rect, wall_axis_centre, inner_face, perpendicular_gap))

    # The old implementation paired walls from globally sorted lists. Filtering
    # to the current line corridor first avoids pairing unrelated wall fragments
    # on different sides of a drawing.
    eligible.sort(key=lambda item: (item[2], str(item[0].get("id", ""))))
    if len(eligible) > MAX_ELIGIBLE_WALLS:
        eligible = sorted(
            eligible,
            key=lambda item: (abs(item[2] - line_centre), item[2]),
        )[:MAX_ELIGIBLE_WALLS]
        eligible.sort(key=lambda item: item[2])

    before = [item for item in eligible if item[2] < line_centre]
    after = [item for item in eligible if item[2] > line_centre]
    candidates: list[dict[str, Any]] = []

    for first_index, first in enumerate(before):
        for second_index, second in enumerate(after):
            span_start, span_end = first[3], second[3]
            span_length = span_end - span_start
            if span_length <= 0 or not (span_start < line_centre < span_end):
                continue

            margin = max((text_end - text_start) * 0.75, line_thickness * 3.0, span_length * 0.05, 6.0)
            if text_centre < span_start - margin or text_centre > span_end + margin:
                continue

            gap_centre = (span_start + span_end) / 2
            centre_error = abs(text_centre - gap_centre) / max(span_length / 2 + margin, 1.0)
            line_centre_error = abs(line_centre - gap_centre) / max(span_length / 2, 1.0)
            endpoint_error = (
                abs(span_start - line_start) + abs(span_end - line_end)
            ) / (2.0 * max(span_length, line_length, 1.0))
            overlap = max(0.0, min(span_end, line_end) - max(span_start, line_start))
            overlap_ratio = min(1.0, overlap / max(min(span_length, line_length), 1.0))
            perpendicular_error = max(first[4], second[4]) / max(
                6.0, line_thickness * 3.0,
                (first[1]["width"] if orientation == "horizontal" else first[1]["height"]) * 1.5,
                (second[1]["width"] if orientation == "horizontal" else second[1]["height"]) * 1.5,
            )
            intervening = max(0, len(eligible) - len(before) - len(after))
            intervening += max(0, len(before) - first_index - 1)
            intervening += second_index

            score = exp(
                -1.0 * centre_error
                -0.8 * line_centre_error
                -1.0 * endpoint_error
                -0.65 * (1.0 - overlap_ratio)
                -0.6 * perpendicular_error
                -0.12 * intervening
            )

            first_id, second_id = first[0].get("id"), second[0].get("id")
            if not isinstance(first_id, str) or not isinstance(second_id, str):
                continue
            candidates.append({
                "wall_ids": [first_id, second_id],
                "orientation": orientation,
                "method": "between_vertical_walls" if orientation == "horizontal"
                          else "between_horizontal_walls",
                "span_px": round(span_length, 2),
                "gap_center_px": round(gap_centre, 2),
                "text_center_offset_px": round(text_centre - gap_centre, 2),
                "line_center_offset_px": round(line_centre - gap_centre, 2),
                "endpoint_residual_px": round(
                    (abs(span_start - line_start) + abs(span_end - line_end)) / 2.0, 2
                ),
                "perpendicular_offset_px": round(max(first[4], second[4]), 2),
                "intervening_wall_count": intervening,
                "score": round(max(0.0, min(1.0, score)), 4),
                "evidence": (
                    "The text centre falls within the candidate gap; wall boxes "
                    "overlap the dimension line's local perpendicular corridor. "
                    "Line/gap centre and endpoint alignment rank the span."
                ),
            })

    candidates.sort(key=lambda item: (-item["score"], item["wall_ids"]))
    return candidates[:MAX_CANDIDATES]


def _maximum_weight_assignment(weights: list[list[float]]) -> dict[int, int]:
    """Maximum-weight one-to-one row/column assignment via the Hungarian method.

    Adds one zero-weight dummy column per row, so detections may remain
    unassigned. Returns only real column assignments.
    """
    row_count = len(weights)
    if row_count == 0:
        return {}
    column_count = max((len(row) for row in weights), default=0)
    if column_count == 0:
        return {}

    real = [list(row) + [0.0] * (column_count - len(row)) for row in weights]
    width = column_count + row_count
    cost = [
        [-value for value in row] + [0.0] * row_count
        for row in real
    ]

    u = [0.0] * (row_count + 1)
    v = [0.0] * (width + 1)
    p = [0] * (width + 1)
    way = [0] * (width + 1)

    for i in range(1, row_count + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (width + 1)
        used = [False] * (width + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, width + 1):
                if used[j]:
                    continue
                current = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if current < minv[j]:
                    minv[j] = current
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(width + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assignment: dict[int, int] = {}
    for j in range(1, column_count + 1):
        if p[j] != 0:
            assignment[p[j] - 1] = j - 1
    return assignment


def associate_dimensions(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return globally ranked, unconfirmed value→line→wall-span hypotheses.

    Each dimension-line detection can be globally recommended to at most one
    dimension-value detection. Reviewers may still choose another visible
    candidate, but the UI clearly distinguishes unique assignment suggestions
    from lines already recommended for another text region.
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
            axis = _orientation(rect)
            if axis:
                lines.append((detection, rect, axis))
        elif kind == "wall":
            walls.append((detection, rect))
        elif kind == "dimension_value":
            values.append((detection, rect))

    # Preserve detection order for stable API/export output.
    value_records: list[dict[str, Any]] = []
    unique_line_ids = list(dict.fromkeys(
        line.get("id") for line, _, _ in lines if isinstance(line.get("id"), str)
    ))
    line_column = {line_id: index for index, line_id in enumerate(unique_line_ids)}

    for value, value_rect in values:
        value_id = value.get("id")
        if not isinstance(value_id, str):
            continue
        candidates: list[dict[str, Any]] = []
        for line, line_rect, orientation in lines:
            line_id = line.get("id")
            if not isinstance(line_id, str):
                continue
            value_line = _score_value_to_line(value_rect, line_rect, orientation)
            if value_line is None:
                continue
            line_score, line_evidence = value_line
            if line_score < MIN_LINE_SCORE:
                continue
            spans = _wall_span_candidates(value_rect, line_rect, orientation, walls)
            best_span_score = spans[0]["score"] if spans else 0.0
            assignment_score = (
                0.42 * line_score + 0.58 * best_span_score
                if spans else 0.35 * line_score
            )
            candidates.append({
                "dimension_line_id": line_id,
                "orientation": orientation,
                "score": line_score,
                "assignment_score": round(assignment_score, 4),
                "evidence": line_evidence,
                "wall_spans": spans,
                "wall_span_status": _fit_status(
                    [item["score"] for item in spans], minimum=0.30
                ),
                "globally_assigned": False,
                "globally_assigned_to": None,
            })

        # Repeated box IDs should not produce duplicate line choices.
        deduplicated: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            previous = deduplicated.get(candidate["dimension_line_id"])
            if previous is None or candidate["assignment_score"] > previous["assignment_score"]:
                deduplicated[candidate["dimension_line_id"]] = candidate
        candidates = list(deduplicated.values())
        candidates.sort(key=lambda item: (
            -item["assignment_score"], -item["score"], item["dimension_line_id"]
        ))
        value_records.append({
            "dimension_value_id": value_id,
            "candidate_lines": candidates,
            "confirmed": False,
        })

    weights: list[list[float]] = []
    for record in value_records:
        row = [0.0] * len(unique_line_ids)
        for candidate in record["candidate_lines"]:
            row[line_column[candidate["dimension_line_id"]]] = candidate["assignment_score"]
        weights.append(row)
    assignment = _maximum_weight_assignment(weights)

    assigned_to: dict[str, str] = {}
    for row_index, column_index in assignment.items():
        if row_index >= len(value_records) or column_index >= len(unique_line_ids):
            continue
        score = weights[row_index][column_index]
        if score >= MIN_GLOBAL_ASSIGNMENT_SCORE:
            assigned_to[unique_line_ids[column_index]] = value_records[row_index]["dimension_value_id"]

    results: list[dict[str, Any]] = []
    for record in value_records:
        value_id = record["dimension_value_id"]
        candidates = record["candidate_lines"]
        for candidate in candidates:
            line_id = candidate["dimension_line_id"]
            owner = assigned_to.get(line_id)
            candidate["globally_assigned"] = owner == value_id
            candidate["globally_assigned_to"] = owner

        candidates = candidates[:MAX_CANDIDATES]
        eligible_scores = [
            candidate["assignment_score"]
            for candidate in candidates if candidate["wall_spans"]
        ]
        results.append({
            "dimension_value_id": value_id,
            "status": _fit_status(eligible_scores, minimum=MIN_GLOBAL_ASSIGNMENT_SCORE),
            "candidate_lines": candidates,
            "confirmed": False,
        })

    return results

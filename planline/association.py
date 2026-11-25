
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
    """Rank wall gaps at the text's position along a possibly chained line.

    A dimension-line detection may cover an entire chain containing multiple
    labels. The text coordinate therefore selects the local gap; the line box
    supplies orientation, annotation-band and projected-overlap evidence.
    """
    line_centre, line_start, line_end = _axis_values(line_rect, orientation)
    text_centre, text_start, text_end = _axis_values(value_rect, orientation)
    line_perp, line_perp_start, line_perp_end = _perpendicular_values(line_rect, orientation)
    _, text_perp_start, text_perp_end = _perpendicular_values(value_rect, orientation)
    line_length = max(line_end - line_start, 1.0)
    line_thickness = max(line_perp_end - line_perp_start, 1.0)
    text_thickness = max(text_perp_end - text_perp_start, 1.0)
    text_length = max(text_end - text_start, 1.0)
    required_wall_orientation = "vertical" if orientation == "horizontal" else "horizontal"

    eligible: list[tuple[dict[str, Any], dict[str, float], float, float, float, float]] = []
    for wall, rect in walls:
        if _orientation(rect) != required_wall_orientation:
            continue
        wall_axis_centre, _, _ = _axis_values(rect, orientation)
        _, wall_perp_start, wall_perp_end = _perpendicular_values(rect, orientation)
        # Thickness is the wall dimension normal to its long axis, not its run.
        wall_thickness = max(
            rect["width"] if orientation == "horizontal" else rect["height"], 1.0
        )
        perpendicular_gap = _point_interval_gap(line_perp, wall_perp_start, wall_perp_end)
        # Local corridor includes text height to allow normal extension-line offsets,
        # but rejects unrelated distant wall fragments.
        local_tolerance = max(
            6.0, line_thickness * 3.0, wall_thickness * 1.5, text_thickness * 2.0
        )
        if perpendicular_gap > local_tolerance:
            continue

        if orientation == "horizontal":
            inner_face = rect["x2"] if wall_axis_centre < text_centre else rect["x1"]
        else:
            inner_face = rect["y2"] if wall_axis_centre < text_centre else rect["y1"]
        eligible.append((wall, rect, wall_axis_centre, inner_face, perpendicular_gap, local_tolerance))

    eligible.sort(key=lambda item: (item[2], str(item[0].get("id", ""))))
    if len(eligible) > MAX_ELIGIBLE_WALLS:
        eligible = sorted(
            eligible, key=lambda item: (abs(item[2] - text_centre), item[2])
        )[:MAX_ELIGIBLE_WALLS]
        eligible.sort(key=lambda item: item[2])

    # Use the label's position, not the centre of the complete dimension-line
    # detection. This permits several labels on one chained line.
    before = [item for item in eligible if item[2] < text_centre]
    after = [item for item in eligible if item[2] > text_centre]
    candidates: list[dict[str, Any]] = []

    for first in before:
        for second in after:
            span_start, span_end = first[3], second[3]
            span_length = span_end - span_start
            if span_length <= 0 or not (span_start < text_centre < span_end):
                continue

            margin = max(text_length * 0.75, line_thickness * 3.0, 6.0)
            if text_centre < span_start - margin or text_centre > span_end + margin:
                continue

            gap_centre = (span_start + span_end) / 2
            # Compare text offset to the label's own size, not the gap size.
            # This favours the local gap around a label over an unrelated wider
            # overall gap whose centre is only marginally closer in raw pixels.
            centre_error = abs(text_centre - gap_centre) / max(text_length, 1.0)
            line_overlap = max(0.0, min(span_end, line_end) - max(span_start, line_start))
            line_overlap_ratio = min(1.0, line_overlap / max(span_length, 1.0))
            if line_overlap_ratio <= 0:
                continue

            endpoint_residual = (
                abs(span_start - line_start) + abs(span_end - line_end)
            ) / 2.0
            endpoint_error = endpoint_residual / max(span_length, line_length, 1.0)
            perpendicular_tolerance = max(first[5], second[5], 1.0)
            perpendicular_error = max(first[4], second[4]) / perpendicular_tolerance
            intervening = sum(
                1 for item in eligible if first[2] < item[2] < second[2]
            )
            line_centre_offset = line_centre - gap_centre

            # Text-to-gap position and line coverage dominate. Endpoint alignment
            # is only a small factor so one chain line can support inner segments.
            score = exp(
                -1.35 * centre_error
                -0.65 * (1.0 - line_overlap_ratio)
                -0.1 * endpoint_error
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
                "line_center_offset_px": round(line_centre_offset, 2),
                "endpoint_residual_px": round(endpoint_residual, 2),
                "perpendicular_offset_px": round(max(first[4], second[4]), 2),
                "intervening_wall_count": intervening,
                "line_overlap_ratio": round(line_overlap_ratio, 4),
                "score": round(max(0.0, min(1.0, score)), 4),
                "assignment_score": 0.0,
                "globally_assigned": False,
                "globally_assigned_to": None,
                "evidence": (
                    "The text centre falls within the candidate wall gap and the "
                    "dimension-line projection covers the gap. Local corridor, "
                    "gap-centre fit and intervening-wall count rank the span."
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
    """Return unconfirmed value→line→wall-span hypotheses with global gap matching.

    Dimension-line detections may be shared by several labels in a chain.
    Global one-to-one assignment is applied to wall-span gaps instead.
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

    value_records: list[dict[str, Any]] = []
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
            for span in spans:
                span["assignment_score"] = round(
                    0.42 * line_score + 0.58 * span["score"], 4
                )
            best_assignment_score = max(
                (span["assignment_score"] for span in spans), default=0.0
            )
            candidates.append({
                "dimension_line_id": line_id,
                "orientation": orientation,
                "score": line_score,
                "assignment_score": best_assignment_score,
                "evidence": line_evidence,
                "wall_spans": spans,
                "wall_span_status": _fit_status(
                    [item["score"] for item in spans], minimum=0.30
                ),
            })

        deduplicated: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            previous = deduplicated.get(candidate["dimension_line_id"])
            if previous is None or candidate["assignment_score"] > previous["assignment_score"]:
                deduplicated[candidate["dimension_line_id"]] = candidate
        candidates = list(deduplicated.values())
        candidates.sort(key=lambda item: (
            -item["assignment_score"], -item["score"], item["dimension_line_id"]
        ))
        candidates = candidates[:MAX_CANDIDATES]
        value_records.append({
            "dimension_value_id": value_id,
            "candidate_lines": candidates,
            "confirmed": False,
        })

    # Globally match labels to unique wall gaps, not dimension-line detections.
    # One dimension line can legitimately contain multiple chain segments.
    span_keys: list[tuple[str, tuple[str, str]]] = []
    span_column: dict[tuple[str, tuple[str, str]], int] = {}
    for record in value_records:
        for candidate in record["candidate_lines"]:
            for span in candidate["wall_spans"]:
                key = (span["orientation"], tuple(sorted(span["wall_ids"])))
                if key not in span_column:
                    span_column[key] = len(span_keys)
                    span_keys.append(key)

    weights: list[list[float]] = []
    for record in value_records:
        row = [0.0] * len(span_keys)
        for candidate in record["candidate_lines"]:
            for span in candidate["wall_spans"]:
                key = (span["orientation"], tuple(sorted(span["wall_ids"])))
                column = span_column[key]
                row[column] = max(row[column], span["assignment_score"])
        weights.append(row)

    assignment = _maximum_weight_assignment(weights)
    assigned_to: dict[tuple[str, tuple[str, str]], str] = {}
    for row_index, column_index in assignment.items():
        if row_index >= len(value_records) or column_index >= len(span_keys):
            continue
        if weights[row_index][column_index] >= MIN_GLOBAL_ASSIGNMENT_SCORE:
            assigned_to[span_keys[column_index]] = value_records[row_index]["dimension_value_id"]

    results: list[dict[str, Any]] = []
    for record in value_records:
        value_id = record["dimension_value_id"]
        candidate_lines = record["candidate_lines"]
        all_span_scores: list[float] = []
        has_own_global_assignment = False
        for candidate in candidate_lines:
            for span in candidate["wall_spans"]:
                key = (span["orientation"], tuple(sorted(span["wall_ids"])))
                owner = assigned_to.get(key)
                span["globally_assigned"] = owner == value_id
                span["globally_assigned_to"] = owner
                all_span_scores.append(span["assignment_score"])
                if owner == value_id:
                    has_own_global_assignment = True

        status = _fit_status(all_span_scores, minimum=MIN_GLOBAL_ASSIGNMENT_SCORE)
        if all_span_scores and not has_own_global_assignment:
            best_span = max(
                (span for candidate in candidate_lines for span in candidate["wall_spans"]),
                key=lambda item: item["assignment_score"],
                default=None,
            )
            if best_span and best_span["globally_assigned_to"] not in (None, value_id):
                status = "ambiguous"

        results.append({
            "dimension_value_id": value_id,
            "status": status,
            "candidate_lines": candidate_lines,
            "confirmed": False,
        })

    return results

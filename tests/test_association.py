
from __future__ import annotations

from planline.association import _maximum_weight_assignment, associate_dimensions


def detection(item_id: str, kind: str, box: tuple[float, float, float, float]) -> dict:
    x1, y1, x2, y2 = box
    return {
        "id": item_id, "class_name": kind,
        "bbox": {
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "width": x2 - x1, "height": y2 - y1,
        },
    }


def test_horizontal_value_to_line_to_vertical_wall_gap() -> None:
    detections = [
        detection("value-1", "dimension_value", (75, 31, 125, 49)),
        detection("line-near", "dimension_line", (20, 54, 180, 58)),
        detection("line-far", "dimension_line", (20, 130, 180, 134)),
        detection("wall-left", "wall", (10, 60, 20, 180)),
        detection("wall-right", "wall", (180, 60, 190, 180)),
    ]
    result = associate_dimensions(detections)[0]
    assert result["status"] == "candidate"
    assert result["candidate_lines"][0]["dimension_line_id"] == "line-near"
    span = result["candidate_lines"][0]["wall_spans"][0]
    assert span["wall_ids"] == ["wall-left", "wall-right"]
    assert span["span_px"] == 160
    assert span["method"] == "between_vertical_walls"
    assert span["text_center_offset_px"] == 0
    assert result["confirmed"] is False
    assert result["candidate_lines"][0]["globally_assigned"] is True


def test_vertical_value_to_line_to_horizontal_wall_gap() -> None:
    detections = [
        detection("value-v", "dimension_value", (30, 75, 48, 125)),
        detection("line-v", "dimension_line", (54, 20, 58, 180)),
        detection("wall-top", "wall", (60, 10, 180, 20)),
        detection("wall-bottom", "wall", (60, 180, 180, 190)),
    ]
    result = associate_dimensions(detections)[0]
    assert result["candidate_lines"][0]["dimension_line_id"] == "line-v"
    span = result["candidate_lines"][0]["wall_spans"][0]
    assert span["wall_ids"] == ["wall-top", "wall-bottom"]
    assert span["span_px"] == 160
    assert span["method"] == "between_horizontal_walls"


def test_gap_model_ranks_a_label_by_its_position_between_walls() -> None:
    detections = [
        detection("value", "dimension_value", (65, 31, 85, 49)),
        detection("line", "dimension_line", (20, 54, 90, 58)),
        detection("wall-left", "wall", (10, 60, 20, 180)),
        detection("wall-middle", "wall", (90, 60, 100, 180)),
        detection("wall-right", "wall", (180, 60, 190, 180)),
    ]
    result = associate_dimensions(detections)[0]
    spans = result["candidate_lines"][0]["wall_spans"]
    assert spans[0]["wall_ids"] == ["wall-left", "wall-middle"]
    assert spans[0]["text_center_offset_px"] > 0  # Text centre is right of this gap centre.


def test_value_outside_all_wall_gaps_is_not_assigned_to_a_span() -> None:
    detections = [
        detection("value", "dimension_value", (195, 31, 215, 49)),
        detection("line", "dimension_line", (10, 54, 230, 58)),
        detection("wall-left", "wall", (10, 60, 20, 180)),
        detection("wall-right", "wall", (180, 60, 190, 180)),
    ]
    result = associate_dimensions(detections)[0]
    assert result["status"] == "unmatched"
    assert result["candidate_lines"][0]["wall_spans"] == []


def test_walls_outside_the_local_dimension_corridor_are_rejected() -> None:
    detections = [
        detection("value", "dimension_value", (75, 31, 125, 49)),
        detection("line", "dimension_line", (20, 54, 180, 58)),
        detection("wall-left", "wall", (10, 500, 20, 620)),
        detection("wall-right", "wall", (180, 500, 190, 620)),
    ]
    result = associate_dimensions(detections)[0]
    assert result["candidate_lines"][0]["wall_spans"] == []


def test_close_line_fits_are_reported_as_ambiguous_not_auto_confirmed() -> None:
    detections = [
        detection("value", "dimension_value", (70, 30, 130, 48)),
        detection("line-a", "dimension_line", (20, 52, 180, 56)),
        detection("line-b", "dimension_line", (20, 53, 180, 57)),
        detection("wall-left", "wall", (10, 58, 20, 180)),
        detection("wall-right", "wall", (180, 58, 190, 180)),
    ]
    result = associate_dimensions(detections)[0]
    assert result["status"] == "ambiguous"
    assert {item["dimension_line_id"] for item in result["candidate_lines"]} == {"line-a", "line-b"}
    assert result["confirmed"] is False


def test_global_assignment_avoids_the_old_greedy_matching_trap() -> None:
    # Greedy would consume column 0 for row 0 (0.90) and leave row 1 unmatched.
    # The global optimum assigns row 1 to column 0 and row 0 to column 1.
    assignment = _maximum_weight_assignment([
        [0.90, 0.80],
        [0.85, 0.10],
    ])
    assert assignment[0] == 1
    assert assignment[1] == 0


def test_two_text_regions_are_not_globally_recommended_the_same_dimension_line() -> None:
    detections = [
        detection("value-a", "dimension_value", (75, 31, 125, 49)),
        detection("value-b", "dimension_value", (75, 32, 125, 50)),
        detection("line", "dimension_line", (20, 54, 180, 58)),
        detection("wall-left", "wall", (10, 60, 20, 180)),
        detection("wall-right", "wall", (180, 60, 190, 180)),
    ]
    results = associate_dimensions(detections)
    assert len(results) == 2
    assert sum(
        span["globally_assigned"]
        for result in results
        for candidate in result["candidate_lines"]
        for span in candidate["wall_spans"]
    ) == 1


def test_non_adjacent_wall_pairs_remain_available_for_overall_dimensions() -> None:
    detections = [
        detection("value", "dimension_value", (85, 31, 115, 49)),
        detection("line", "dimension_line", (10, 54, 190, 58)),
        detection("wall-left", "wall", (10, 60, 20, 180)),
        detection("wall-inner", "wall", (90, 60, 100, 180)),
        detection("wall-right", "wall", (180, 60, 190, 180)),
    ]
    result = associate_dimensions(detections)[0]
    wall_pairs = [span["wall_ids"] for span in result["candidate_lines"][0]["wall_spans"]]
    assert ["wall-left", "wall-right"] in wall_pairs or result["candidate_lines"][0]["wall_spans"][0]["intervening_wall_count"] > 0


def test_invalid_boxes_and_ambiguous_orientations_are_not_forced() -> None:
    detections = [
        detection("value", "dimension_value", (70, 30, 130, 48)),
        detection("square-line", "dimension_line", (60, 60, 70, 70)),
        {"id": "bad", "class_name": "wall", "bbox": {"x1": 2, "y1": 1}},
    ]
    assert associate_dimensions(detections)[0]["candidate_lines"] == []


def test_one_dimension_line_can_serve_multiple_labels_in_a_chain() -> None:
    detections = [
        detection("value-left", "dimension_value", (45, 31, 65, 49)),
        detection("value-right", "dimension_value", (135, 31, 155, 49)),
        detection("line-chain", "dimension_line", (20, 54, 180, 58)),
        detection("wall-left", "wall", (10, 60, 20, 300)),
        detection("wall-middle", "wall", (90, 60, 100, 300)),
        detection("wall-right", "wall", (180, 60, 190, 300)),
    ]
    results = associate_dimensions(detections)
    assert len(results) == 2
    left, right = results
    assert left["candidate_lines"][0]["dimension_line_id"] == "line-chain"
    assert right["candidate_lines"][0]["dimension_line_id"] == "line-chain"
    left_span = left["candidate_lines"][0]["wall_spans"][0]
    right_span = right["candidate_lines"][0]["wall_spans"][0]
    assert left_span["wall_ids"] == ["wall-left", "wall-middle"]
    assert right_span["wall_ids"] == ["wall-middle", "wall-right"]
    assert left_span["globally_assigned"] is True
    assert right_span["globally_assigned"] is True


def test_global_assignment_reserves_a_wall_gap_for_only_one_label() -> None:
    detections = [
        detection("value-a", "dimension_value", (75, 31, 125, 49)),
        detection("value-b", "dimension_value", (78, 31, 128, 49)),
        detection("line", "dimension_line", (20, 54, 180, 58)),
        detection("wall-left", "wall", (10, 60, 20, 180)),
        detection("wall-right", "wall", (180, 60, 190, 180)),
    ]
    results = associate_dimensions(detections)
    assert sum(
        span["globally_assigned"]
        for result in results
        for candidate in result["candidate_lines"]
        for span in candidate["wall_spans"]
    ) == 1


def test_dimension_corridor_uses_wall_thickness_not_wall_run_length() -> None:
    detections = [
        detection("value", "dimension_value", (75, 31, 125, 49)),
        detection("line", "dimension_line", (20, 54, 180, 58)),
        detection("wall-left-far", "wall", (10, 100, 20, 400)),
        detection("wall-right-far", "wall", (180, 100, 190, 400)),
    ]
    result = associate_dimensions(detections)[0]
    assert result["candidate_lines"][0]["wall_spans"] == []


def test_dimension_text_height_allows_nearby_extension_band() -> None:
    detections = [
        detection("value", "dimension_value", (75, 31, 125, 49)),
        detection("line", "dimension_line", (20, 54, 180, 58)),
        detection("wall-left", "wall", (10, 80, 20, 380)),
        detection("wall-right", "wall", (180, 80, 190, 380)),
    ]
    result = associate_dimensions(detections)[0]
    assert result["candidate_lines"][0]["wall_spans"]

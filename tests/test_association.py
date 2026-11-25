from __future__ import annotations

from planline.association import associate_dimensions


def detection(item_id: str, kind: str, box: tuple[float, float, float, float]) -> dict:
    x1, y1, x2, y2 = box
    return {
        "id": item_id, "class_name": kind,
        "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                 "width": x2 - x1, "height": y2 - y1},
    }


def test_horizontal_value_to_line_to_vertical_wall_pair() -> None:
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
    assert result["confirmed"] is False


def test_vertical_value_to_line_to_horizontal_wall_pair() -> None:
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


def test_close_line_fits_are_ambiguous_not_auto_selected() -> None:
    detections = [
        detection("value", "dimension_value", (70, 30, 130, 48)),
        detection("line-a", "dimension_line", (20, 53, 180, 57)),
        detection("line-b", "dimension_line", (20, 54, 180, 58)),
    ]
    result = associate_dimensions(detections)[0]
    assert result["status"] == "ambiguous"
    assert {item["dimension_line_id"] for item in result["candidate_lines"]} == {"line-a", "line-b"}
    assert result["confirmed"] is False


def test_missing_wall_pair_remains_unmatched() -> None:
    detections = [
        detection("value", "dimension_value", (70, 30, 130, 48)),
        detection("line", "dimension_line", (20, 52, 180, 56)),
        detection("only-one-wall", "wall", (10, 60, 20, 180)),
    ]
    result = associate_dimensions(detections)[0]
    assert result["candidate_lines"][0]["wall_spans"] == []
    assert result["candidate_lines"][0]["wall_span_status"] == "unmatched"


def test_invalid_boxes_and_non_axis_aligned_candidates_are_ignored() -> None:
    detections = [
        detection("value", "dimension_value", (70, 30, 130, 48)),
        detection("square-line", "dimension_line", (60, 60, 70, 70)),
        {"id": "bad", "class_name": "wall", "bbox": {"x1": 2, "y1": 1}},
    ]
    assert associate_dimensions(detections)[0]["candidate_lines"] == []

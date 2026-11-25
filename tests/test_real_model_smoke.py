from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_bundled_detector_loads_and_runs_on_a_representative_scan() -> None:
    """Opt-in smoke test for real weights; it does not score detection accuracy."""
    if os.getenv("PLANLINE_RUN_MODEL_SMOKE") != "1":
        pytest.skip("Set PLANLINE_RUN_MODEL_SMOKE=1 to run the real-weight smoke test.")

    weights = ROOT / "yolo_floorplan.pt"
    if not weights.is_file():
        pytest.skip(f"Detector weights are not present at {weights}.")

    image_value = os.getenv("PLANLINE_SMOKE_IMAGE")
    if not image_value:
        pytest.skip("Set PLANLINE_SMOKE_IMAGE to a representative raster scan.")
    image_path = Path(image_value).expanduser()
    if not image_path.is_file():
        pytest.fail(f"PLANLINE_SMOKE_IMAGE does not exist: {image_path}")

    from ultralytics import YOLO

    model = YOLO(str(weights))
    device = os.getenv("PLANLINE_SMOKE_DEVICE") or None
    results = model.predict(
        source=str(image_path),
        conf=0.25,
        imgsz=640,
        device=device,
        verbose=False,
    )

    assert len(results) == 1
    result = results[0]
    assert result.orig_shape is not None
    image_height, image_width = result.orig_shape
    assert image_width > 0 and image_height > 0

    names = model.names
    class_names = set(names.values()) if isinstance(names, dict) else set(names)
    assert {"wall", "dimension_line", "dimension_value"}.issubset(class_names)

    if result.boxes is not None and len(result.boxes):
        boxes = result.boxes.xyxy.cpu().numpy()
        assert np.isfinite(boxes).all()
        assert (boxes[:, 2] >= boxes[:, 0]).all()
        assert (boxes[:, 3] >= boxes[:, 1]).all()
        assert (boxes[:, 0] >= 0).all()
        assert (boxes[:, 1] >= 0).all()
        assert (boxes[:, 2] <= image_width + 1).all()
        assert (boxes[:, 3] <= image_height + 1).all()

from __future__ import annotations

import cv2
import numpy as np

from dataset_creator import create_dataset_from_sketches


def test_dataset_creator_keeps_final_row_and_right_edge_digit(tmp_path) -> None:
    source_dir = tmp_path / "sketches"
    output_dir = tmp_path / "my_dataset"
    source_dir.mkdir()

    # Two separated digits in the first row, followed by a final digit that
    # touches both the bottom and right image edges.
    image = np.zeros((120, 120, 3), dtype=np.uint8)
    image[10:35, 10:20, 2] = 255
    image[10:35, 35:45, 2] = 255
    image[80:120, 100:120, 2] = 255
    assert cv2.imwrite(str(source_dir / "0.jpg"), image)

    create_dataset_from_sketches(
        input_folder=str(source_dir),
        output_folder=str(output_dir),
    )

    samples = sorted((output_dir / "0").glob("*.png"))
    assert len(samples) == 3
    for sample_path in samples:
        sample = cv2.imread(str(sample_path), cv2.IMREAD_GRAYSCALE)
        assert sample is not None
        assert sample.shape == (64, 64)



def test_dataset_creator_skips_unreadable_sheet(tmp_path) -> None:
    source_dir = tmp_path / "sketches"
    output_dir = tmp_path / "my_dataset"
    source_dir.mkdir()
    (source_dir / "0.jpg").write_bytes(b"not a valid image")

    create_dataset_from_sketches(
        input_folder=str(source_dir),
        output_folder=str(output_dir),
    )

    assert not (output_dir / "0").exists()

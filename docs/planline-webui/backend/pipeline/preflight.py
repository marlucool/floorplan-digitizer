"""Deterministic checks that run before model inference.

These checks do not infer dimensions, text, walls, or geometry. They make input
quality and file identity explicit for later model adapters and review work.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def inspect_source(path: Path, suffix: str, image_size: dict[str, int] | None) -> dict[str, Any]:
    data = path.read_bytes()
    findings: list[dict[str, str]] = []
    if suffix == ".pdf":
        findings.append({
            "severity": "info",
            "code": "pdf_rendering_required",
            "message": "The PDF is stored, but page rendering and OCR preparation are not configured yet.",
        })
    elif image_size is None:
        findings.append({
            "severity": "warning",
            "code": "image_size_unknown",
            "message": "Image dimensions could not be read without a decoder. Configure the image-preparation adapter before OCR.",
        })
    else:
        width, height = image_size["width"], image_size["height"]
        if min(width, height) < 1200:
            findings.append({
                "severity": "warning",
                "code": "low_resolution",
                "message": "The scan is below 1,200 px on one side; small handwritten dimensions may need a higher-resolution scan.",
            })
        if max(width, height) / min(width, height) > 3.5:
            findings.append({
                "severity": "info",
                "code": "unusual_aspect_ratio",
                "message": "The source has an unusual aspect ratio; inspect page bounds and orientation before detection.",
            })
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes_checked": len(data),
        "image_size": image_size,
        "findings": findings,
    }

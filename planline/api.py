"""Local API for the Planline 2D floor-plan review interface.

This first integration deliberately stops at object detection. The bundled
YOLO model detects candidate regions; it does not read dimensions or create
measured geometry. The application does not intentionally persist source drawings
as project files; multipart parsing may spool uploads to temporary storage.
"""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
DETECTOR_PATH = ROOT_DIR / "yolo_floorplan.pt"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".pdf"}

app = FastAPI(
    title="Planline API",
    version="0.1.0",
    description="Local API for floor-plan region detection and review.",
)
_model_lock = Lock()


@lru_cache(maxsize=1)
def get_detector() -> Any:
    """Load the repository detector once, on the first analysis request."""
    if not DETECTOR_PATH.is_file():
        raise FileNotFoundError(
            f"Detector weights not found: {DETECTOR_PATH.name}. "
            "Restore the tracked model file before analysing."
        )
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Ultralytics is unavailable. Install the project requirements."
        ) from exc
    return YOLO(str(DETECTOR_PATH))


def _check_image_size(image: np.ndarray) -> None:
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("The drawing has invalid image dimensions.")
    if height * width > MAX_IMAGE_PIXELS:
        raise OverflowError(
            f"Decoded image is {width} × {height}px; the limit is "
            f"{MAX_IMAGE_PIXELS:,} pixels."
        )


def _decode_raster(data: bytes) -> np.ndarray:
    encoded = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The uploaded file is not a readable supported image.")
    _check_image_size(image)
    return image


def decode_upload(data: bytes, filename: str) -> tuple[np.ndarray, dict[str, Any]]:
    """Decode an image or rasterise page one of a PDF in memory."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("Use PNG, JPG, WEBP, TIFF or PDF.")
    if not data:
        raise ValueError("The uploaded file is empty.")

    if suffix != ".pdf":
        return _decode_raster(data), {
            "source_type": "image",
            "page_count": 1,
            "page_index": 0,
        }

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF support requires PyMuPDF.") from exc

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("The PDF is damaged, encrypted or unreadable.") from exc

    try:
        if document.is_encrypted:
            raise ValueError("Password-protected PDFs are not supported.")
        if document.page_count < 1:
            raise ValueError("The PDF contains no pages.")

        page = document.load_page(0)
        rect = page.rect
        page_area = max(float(rect.width * rect.height), 1.0)
        scale = min(2.0, (MAX_IMAGE_PIXELS / page_area) ** 0.5)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        channels = pixmap.n
        raster = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height, pixmap.width, channels
        )
        if channels == 4:
            image = cv2.cvtColor(raster, cv2.COLOR_RGBA2BGR)
        elif channels == 3:
            image = cv2.cvtColor(raster, cv2.COLOR_RGB2BGR)
        else:
            image = cv2.cvtColor(raster, cv2.COLOR_GRAY2BGR)
        _check_image_size(image)
        return image, {
            "source_type": "pdf",
            "page_count": document.page_count,
            "page_index": 0,
            "note": "Only the first PDF page is analysed in this version.",
        }
    finally:
        document.close()


def serialise_detections(result: Any, image_shape: tuple[int, ...]) -> list[dict[str, Any]]:
    """Convert an Ultralytics result into stable frontend records."""
    height, width = image_shape[:2]
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []

    names = getattr(result, "names", {}) or {}
    detections: list[dict[str, Any]] = []
    for index in range(len(boxes)):
        coords = boxes.xyxy[index].tolist()
        class_id = int(boxes.cls[index].item())
        confidence = float(boxes.conf[index].item())
        x1, y1, x2, y2 = (float(value) for value in coords)
        x1, x2 = max(0.0, min(float(width), x1)), max(0.0, min(float(width), x2))
        y1, y2 = max(0.0, min(float(height), y1)), max(0.0, min(float(height), y2))
        if x2 <= x1 or y2 <= y1:
            continue
        class_name = names.get(class_id, str(class_id)) if isinstance(names, dict) else str(class_id)
        detections.append({
            "id": f"det-{len(detections) + 1:03d}",
            "class_name": str(class_name),
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "bbox": {
                "x1": round(x1, 2), "y1": round(y1, 2),
                "x2": round(x2, 2), "y2": round(y2, 2),
                "width": round(x2 - x1, 2), "height": round(y2 - y1, 2),
            },
            "centre": {
                "x": round((x1 + x2) / 2, 2),
                "y": round((y1 + y2) / 2, 2),
            },
        })
    return detections


def make_preview_data_url(image: np.ndarray, max_edge: int = 1600) -> str:
    """Create a bounded JPEG preview for the browser without saving the upload."""
    height, width = image.shape[:2]
    scale = min(1.0, max_edge / max(height, width))
    if scale < 1.0:
        image = cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        raise RuntimeError("Could not generate a preview of the uploaded drawing.")
    return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


@app.get("/architecture", response_class=FileResponse)
def architecture_notes() -> FileResponse:
    """Serve the project architecture and research notes from the repository."""
    notes_path = ROOT_DIR / "docs" / "PLANLINE_ARCHITECTURE.md"
    if not notes_path.is_file():
        raise HTTPException(status_code=404, detail="Architecture notes are not installed.")
    return FileResponse(notes_path, media_type="text/markdown")


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Report readiness without loading model weights."""
    return {
        "status": "ok",
        "application": "Planline",
        "version": app.version,
        "detector_weights_present": DETECTOR_PATH.is_file(),
        "detector_loaded": get_detector.cache_info().currsize > 0,
        "ocr_available": False,
        "geometry_available": False,
    }


@app.post("/api/analyze")
async def analyze_drawing(file: UploadFile = File(...)) -> dict[str, Any]:
    """Detect candidate regions after multipart parsing and bounded in-memory decoding."""
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="The upload has no filename.")
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Use PNG, JPG, WEBP, TIFF or PDF.")

    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        await file.close()
        raise HTTPException(status_code=413, detail="Upload limit is 25 MB.")

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload limit is 25 MB.")

    try:
        image, source_info = decode_upload(data, filename)
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        detector = get_detector()
        with _model_lock:
            predictions = detector.predict(
                source=image, conf=0.25, imgsz=640, verbose=False
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="The detector failed. Check the local server log.",
        ) from exc

    result = predictions[0] if predictions else None
    detections = serialise_detections(result, image.shape) if result is not None else []
    counts: dict[str, int] = {}
    for detection in detections:
        label = detection["class_name"]
        counts[label] = counts.get(label, 0) + 1

    dimension_regions = [
        item for item in detections if item["class_name"] == "dimension_value"
    ]
    height, width = image.shape[:2]
    notes = [
        "Detected boxes are candidate regions, not recognised measurements.",
        "OCR has not run. Read and verify every dimension against the source drawing.",
        "No pixel-to-millimetre scale has been inferred.",
        "DXF export is disabled until dimensions and geometry are verified.",
        "The bundled detector was trained on a small dataset of simplified plans; review all detections.",
    ]
    if source_info["source_type"] == "pdf":
        notes.append(source_info["note"])

    return {
        "filename": Path(filename).name,
        "source": source_info,
        "image": {"width": width, "height": height},
        "preview_data_url": make_preview_data_url(image),
        "counts": counts,
        "detections": detections,
        "dimension_regions": dimension_regions,
        "notes": notes,
        "export_ready": False,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

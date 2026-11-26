"""Local API for Planline's floor-plan detection and association review.

The bundled YOLO model detects candidate regions. A geometric ranking stage
proposes value-to-line and line-to-wall-span hypotheses for human review; it
does not read dimensions or create measured geometry. The application does not intentionally persist source drawings
automatically; users can explicitly save portable project files. Multipart parsing may spool uploads to temporary storage.
"""
from __future__ import annotations

import base64
import io
import mimetypes
import math
import warnings
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

from . import __version__, updater

from .association import associate_dimensions
from .constraints import DimensionChainRequest, validate_dimension_chain
from .dxf_export import ManualGeometryDXFRequest, export_manual_geometry_dxf
from .dimensions import interpret_dimension_text
from .dimension_constraints import WallDimensionCheckRequest, compare_wall_dimension
from .architecture import render_architecture_page
from .documentation import (
    discover_documents,
    render_documentation_index,
    render_document_page,
    safe_document_path,
)
from .ocr_studio_api import router as ocr_studio_router

ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
DETECTOR_PATH = ROOT_DIR / "yolo_floorplan.pt"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".pdf"}

app = FastAPI(
    title="Planline API",
    version=__version__,
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


def _check_dimensions(width: int, height: int) -> None:
    if height <= 0 or width <= 0:
        raise ValueError("The drawing has invalid image dimensions.")
    if height * width > MAX_IMAGE_PIXELS:
        raise OverflowError(
            f"Image is {width} × {height}px; the limit is "
            f"{MAX_IMAGE_PIXELS:,} pixels."
        )


def _check_image_size(image: np.ndarray) -> None:
    height, width = image.shape[:2]
    _check_dimensions(width, height)


def apply_image_adjustments(
    image: np.ndarray,
    brightness: float = 0.0,
    contrast: float = 1.0,
) -> np.ndarray:
    """Adjust pixel intensity without changing image dimensions or coordinates."""
    if not math.isfinite(brightness) or not -100.0 <= brightness <= 100.0:
        raise ValueError("Brightness must be between -100 and 100.")
    if not math.isfinite(contrast) or not 0.5 <= contrast <= 2.0:
        raise ValueError("Contrast must be between 0.5 and 2.0.")
    return np.clip(
        image.astype(np.float32) * float(contrast) + float(brightness),
        0,
        255,
    ).astype(np.uint8)


def _decode_raster(data: bytes) -> np.ndarray:
    # Read dimensions from the image header before OpenCV allocates the full
    # decoded raster. The application limit is lower than Pillow's default
    # decompression-bomb threshold, so enforce our own limit here.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                width, height = probe.size
                _check_dimensions(width, height)
    except OverflowError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise OverflowError("The uploaded image exceeds the pixel limit.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("The uploaded file is not a readable supported image.") from exc

    encoded = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The uploaded file is not a readable supported image.")
    _check_image_size(image)
    return image


def decode_upload(data: bytes, filename: str, page_index: int = 0) -> tuple[np.ndarray, dict[str, Any]]:
    """Decode an image or rasterise the selected zero-based PDF page in memory."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("Use PNG, JPG, WEBP, TIFF or PDF.")
    if not data:
        raise ValueError("The uploaded file is empty.")

    if suffix != ".pdf":
        if page_index != 0:
            raise ValueError("Page selection is only available for PDF files.")
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
        if page_index < 0 or page_index >= document.page_count:
            raise ValueError(
                f"Page {page_index + 1} is outside this PDF. "
                f"Choose a page from 1 to {document.page_count}."
            )

        page = document.load_page(page_index)
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
            "page_index": page_index,
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
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2, confidence)):
            continue
        x1, x2 = max(0.0, min(float(width), x1)), max(0.0, min(float(width), x2))
        y1, y2 = max(0.0, min(float(height), y1)), max(0.0, min(float(height), y2))
        if x2 <= x1 or y2 <= y1:
            continue
        if isinstance(names, dict):
            class_name = names.get(class_id, str(class_id))
        elif isinstance(names, (list, tuple)) and 0 <= class_id < len(names):
            class_name = names[class_id]
        else:
            class_name = str(class_id)
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


MAX_DIMENSION_CROPS = 30


def make_region_crop(image: np.ndarray, bbox: dict[str, float]) -> dict[str, Any] | None:
    """Create a bounded, padded crop from the original-resolution source image."""
    height, width = image.shape[:2]
    pad_x = max(6, int(round(bbox["width"] * 0.15)))
    pad_y = max(6, int(round(bbox["height"] * 0.25)))
    x1 = max(0, int(math.floor(bbox["x1"])) - pad_x)
    y1 = max(0, int(math.floor(bbox["y1"])) - pad_y)
    x2 = min(width, int(math.ceil(bbox["x2"])) + pad_x)
    y2 = min(height, int(math.ceil(bbox["y2"])) + pad_y)
    if x2 <= x1 or y2 <= y1:
        return None
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    edge = max(crop.shape[:2])
    scale = min(4.0, 384.0 / edge) if edge < 384 else 384.0 / edge
    if abs(scale - 1.0) > 0.01:
        interpolation = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        crop = cv2.resize(
            crop,
            (max(1, int(round(crop.shape[1] * scale))), max(1, int(round(crop.shape[0] * scale)))),
            interpolation=interpolation,
        )
    ok, encoded = cv2.imencode(".png", crop, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        return None
    return {
        "crop_bbox": {
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "width": x2 - x1, "height": y2 - y1,
        },
        "crop_data_url": "data:image/png;base64," + base64.b64encode(encoded).decode("ascii"),
    }


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


@app.get("/architecture", response_class=HTMLResponse)
def architecture_notes() -> HTMLResponse:
    """Render the maintained architecture notes inside the Planline UI."""
    notes_path = ROOT_DIR / "docs" / "PLANLINE_ARCHITECTURE.md"
    if not notes_path.is_file():
        raise HTTPException(status_code=404, detail="Architecture notes are not installed.")
    page = render_architecture_page(
        notes_path.read_text(encoding="utf-8"),
        asset_prefix="/",
        home_href="/",
        drawing_href="/drawing",
        ocr_href="/ocr",
        settings_href="/settings",
        architecture_href="/architecture",
    )
    return HTMLResponse(content=page)


@app.get("/documentation", response_class=HTMLResponse)
@app.get("/documentation/", response_class=HTMLResponse)
def documentation_home() -> HTMLResponse:
    """Show every discoverable document and reference file in docs/."""
    documents = discover_documents(ROOT_DIR / "docs")
    page = render_documentation_index(
        documents,
        home_href="/",
        drawing_href="/drawing",
        ocr_href="/ocr",
        settings_href="/settings",
        documentation_href="/documentation",
    )
    return HTMLResponse(content=page)


@app.get("/documentation/{doc_path:path}", response_class=HTMLResponse)
def documentation_file(doc_path: str) -> HTMLResponse:
    """Render Markdown, images, PDFs, source files and attachments from docs/."""
    try:
        source_path = safe_document_path(ROOT_DIR / "docs", doc_path)
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=404, detail="Documentation file not found.") from None

    documents = discover_documents(ROOT_DIR / "docs")
    document = next((item for item in documents if item["path"] == source_path.relative_to(ROOT_DIR / "docs").as_posix()), None)
    if document is None:
        raise HTTPException(status_code=404, detail="Documentation file not found.")

    page = render_document_page(
        document,
        source_path.read_bytes(),
        documents,
        static_site=False,
        current_output_path=f"documentation/{doc_path}",
        asset_prefix="/",
        home_href="/",
        drawing_href="/drawing",
        ocr_href="/ocr",
        settings_href="/settings",
        documentation_href="/documentation",
    )
    return HTMLResponse(content=page)


@app.get("/docs/{doc_path:path}", response_class=FileResponse)
def documentation_asset(doc_path: str) -> FileResponse:
    """Serve original documentation assets for images, PDFs and downloads."""
    try:
        source_path = safe_document_path(ROOT_DIR / "docs", doc_path)
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=404, detail="Documentation asset not found.") from None
    media_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
    return FileResponse(source_path, media_type=media_type)


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
        "dimension_chain_validation_available": True,
        "geometry_available": False,
    }


@app.get("/api/updates/check")
def check_for_updates() -> dict[str, Any]:
    """Check the latest stable Planline GitHub release without changing files."""
    try:
        return updater.check_for_updates()
    except updater.UpdateError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/updates/install")
def install_update() -> dict[str, str]:
    """Download, verify and hand off a stable Windows release update."""
    try:
        return updater.stage_and_launch_update()
    except updater.UpdateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/validate-wall-dimension")
def validate_wall_dimension_endpoint(request: WallDimensionCheckRequest) -> dict[str, Any]:
    """Compare a user-drawn wall to a manually verified explicit dimension."""
    return compare_wall_dimension(request)


class DimensionTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=128)


@app.post("/api/interpret-dimension")
def interpret_dimension_endpoint(request: DimensionTextRequest) -> dict[str, Any]:
    """Interpret explicitly written dimension syntax without assuming missing units."""
    return interpret_dimension_text(request.text)


@app.post("/api/validate-dimension-chain")
def validate_dimension_chain_endpoint(
    request: DimensionChainRequest,
) -> dict[str, object]:
    """Check a manually supplied dimension chain; this route does not run OCR."""
    return validate_dimension_chain(request)


@app.post("/api/export-dxf")
def export_manual_geometry_dxf_endpoint(
    request: ManualGeometryDXFRequest,
) -> Response:
    """Export only user-authored wall segments and room outlines as DXF."""
    try:
        content = export_manual_geometry_dxf(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/dxf",
        headers={"Content-Disposition": 'attachment; filename="planline-manual-geometry.dxf"'},
    )


@app.post("/api/analyze")
async def analyze_drawing(
    file: UploadFile = File(...),
    confidence_threshold: float = Form(0.25),
    page_index: int = Form(0),
    brightness: float = Form(0.0),
    contrast: float = Form(1.0),
) -> dict[str, Any]:
    """Detect candidate regions after multipart parsing and bounded in-memory decoding."""
    if not math.isfinite(confidence_threshold) or not 0.0 < confidence_threshold <= 1.0:
        raise HTTPException(
            status_code=422,
            detail="confidence_threshold must be greater than 0 and at most 1.",
        )
    if not math.isfinite(brightness) or not -100.0 <= brightness <= 100.0:
        raise HTTPException(status_code=422, detail="brightness must be between -100 and 100.")
    if not math.isfinite(contrast) or not 0.5 <= contrast <= 2.0:
        raise HTTPException(status_code=422, detail="contrast must be between 0.5 and 2.0.")

    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="The upload has no filename.")
    if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Use PNG, JPG, WEBP, TIFF or PDF.")

    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        await file.close()
        raise HTTPException(status_code=413, detail="Upload limit is 25 MB.")

    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload limit is 25 MB.")

    try:
        image, source_info = decode_upload(data, filename, page_index=page_index)
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    processed_image = apply_image_adjustments(image, brightness=brightness, contrast=contrast)

    try:
        # Serialize lazy model construction as well as inference. lru_cache
        # protects its cache bookkeeping, but concurrent first calls can still
        # execute the wrapped loader more than once.
        with _model_lock:
            detector = get_detector()
            predictions = detector.predict(
                source=processed_image, conf=confidence_threshold, imgsz=640, verbose=False
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
    detections = serialise_detections(result, processed_image.shape) if result is not None else []
    counts: dict[str, int] = {}
    for detection in detections:
        label = detection["class_name"]
        counts[label] = counts.get(label, 0) + 1

    dimension_candidates = [
        item for item in detections if item["class_name"] == "dimension_value"
    ]
    association_candidates = associate_dimensions(detections)
    association_by_value = {
        item["dimension_value_id"]: item for item in association_candidates
    }
    dimension_regions = []
    for index, item in enumerate(dimension_candidates):
        region = dict(item)
        region["association"] = association_by_value.get(
            item["id"],
            {"dimension_value_id": item["id"], "status": "unmatched", "candidate_lines": [], "confirmed": False},
        )
        if index < MAX_DIMENSION_CROPS:
            crop = make_region_crop(processed_image, item["bbox"])
            if crop is not None:
                region.update(crop)
        dimension_regions.append(region)
    height, width = processed_image.shape[:2]
    notes = [
        "Detected boxes are candidate regions, not recognised measurements.",
        "OCR has not run. Read and verify every dimension against the source drawing.",
        "Geometric association candidates rank dimension-value boxes against dimension lines and wall pairs; they are unconfirmed hypotheses, not verified measurements.",
        "Association scores are relative geometric-fit rankings, not probabilities or measurement confidence.",
        "No pixel-to-millimetre scale has been inferred.",
        "DXF export is disabled until dimensions and geometry are verified.",
        "The bundled detector was trained on a small dataset of simplified plans; review all detections.",
    ]
    if len(dimension_candidates) > MAX_DIMENSION_CROPS:
        notes.append(
            f"Only the first {MAX_DIMENSION_CROPS} dimension-value candidates include review crops."
        )
    if source_info.get("note"):
        notes.append(source_info["note"])

    return {
        "filename": Path(filename).name,
        "source": source_info,
        "image": {"width": width, "height": height},
        "preprocessing": {"brightness": brightness, "contrast": contrast, "method": "linear_intensity_only"},
        "preview_data_url": make_preview_data_url(processed_image),
        "counts": counts,
        "confidence_threshold": confidence_threshold,
        "detections": detections,
        "dimension_regions": dimension_regions,
        "association_candidates": association_candidates,
        "notes": notes,
        "export_ready": False,
    }


@app.get("/")
def index() -> FileResponse:
    """Open the dashboard as the single application entry point."""
    return FileResponse(WEB_DIR / "dashboard.html")


@app.get("/dashboard", response_class=FileResponse)
def dashboard_page() -> FileResponse:
    """Serve the Planline workspace dashboard."""
    return FileResponse(WEB_DIR / "dashboard.html")

@app.get("/drawing", response_class=FileResponse)
def drawing_page() -> FileResponse:
    """Serve the drawing and geometry workspace."""
    return FileResponse(WEB_DIR / "index.html")


@app.get("/settings", response_class=FileResponse)
def settings_page() -> FileResponse:
    """Serve application settings and the in-app release updater."""
    return FileResponse(WEB_DIR / "settings.html")


@app.get("/ocr", response_class=FileResponse)
def ocr_studio() -> FileResponse:
    """Serve the local OCR annotation and training workbench."""
    return FileResponse(WEB_DIR / "ocr.html")


app.include_router(ocr_studio_router)

app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

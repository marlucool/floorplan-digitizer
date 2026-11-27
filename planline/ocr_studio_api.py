"""Local-only API routes for the OCR dataset and training workbench."""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import os
import shutil
import stat
import sys
import re
import threading
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .dataset import (
    MANIFEST_NAME,
    SPLITS_NAME,
    _connected_group_ids,
    _read_manifest,
    add_crop_sample,
    create_grouped_splits,
    delete_crop_sample,
    import_crop_csv,
    validate_dataset,
    update_crop_sample,
)
from .ocr_training import cancel_job, get_job, list_jobs, start_benchmark_job, start_training_job
from .ocr_training_assets import ensure_training_assets, training_assets_status
from .ocr_quality import audit_dataset

_OCR_INFERENCE_LOCK = threading.Lock()
BASE_RECOGNITION_MODELS = {
    "base:PP-OCRv5_mobile_rec": "PP-OCRv5_mobile_rec",
    "base:PP-OCRv5_server_rec": "PP-OCRv5_server_rec",
}

def _get_ocr_dataset_root() -> Path:
    """Use user data storage for installed builds, repo-local storage in development."""
    configured_root = os.environ.get("PLANLINE_DATA_DIR")
    if configured_root:
        return Path(configured_root).expanduser().resolve() / "ocr"
    return Path(__file__).resolve().parents[1] / "datasets" / "ocr"


OCR_DATASET_ROOT = _get_ocr_dataset_root()
MAX_CROP_BYTES = 25 * 1024 * 1024
DATASET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")

router = APIRouter(prefix="/api/ocr", tags=["OCR Studio"])


class CreateDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class UpdateSampleRequest(BaseModel):
    text: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    writer_id: str | None = Field(default=None, max_length=128)
    text_style: str = "handwritten"
    verified: bool = False


class CreateSplitsRequest(BaseModel):
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    force: bool = False


class TrainingAssetsRequest(BaseModel):
    model_variant: str = "mobile"


class StartTrainingRequest(BaseModel):
    paddleocr_dir: str | None = Field(default=None, min_length=1, max_length=2048)
    pretrained_model: str | None = Field(default=None, min_length=1, max_length=2048)
    model_variant: str = "mobile"
    epochs: int = Field(default=30, ge=1, le=500)
    batch_size: int = Field(default=8, ge=1, le=32)
    use_gpu: bool = False


class StartBenchmarkRequest(BaseModel):
    model: str = Field(default="PP-OCRv5_mobile_rec", max_length=128)
    model_dir: str | None = Field(default=None, max_length=2048)
    device: str = "cpu"


def _dataset_dir(dataset_id: str, *, must_exist: bool = True) -> Path:
    if not DATASET_ID_RE.fullmatch(dataset_id):
        raise HTTPException(status_code=400, detail="Invalid dataset ID.")
    root = OCR_DATASET_ROOT.resolve()
    target = (root / dataset_id).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Dataset path is outside the local dataset folder.")
    if must_exist and not target.is_dir():
        raise HTTPException(status_code=404, detail="OCR dataset not found.")
    return target


def _dataset_summary(dataset_dir: Path) -> dict[str, Any]:
    entries = _read_manifest(dataset_dir)
    summary: dict[str, Any] = {
        "samples": len(entries),
        "sources": len({item.get("source_id") for item in entries if item.get("source_id")}),
        "writers": len({item.get("writer_id") for item in entries if item.get("writer_id")}),
        "by_text_style": {},
        "splits_present": (dataset_dir / SPLITS_NAME).is_file(),
        "independent_groups": len(_connected_group_ids(entries)) if entries else 0,
        "verified_samples": sum(item.get("verified") is True for item in entries),
    }
    for item in entries:
        style = item.get("text_style", "unknown")
        summary["by_text_style"][style] = summary["by_text_style"].get(style, 0) + 1
    if entries:
        try:
            validate_dataset(dataset_dir)
            summary["valid"] = True
        except (OSError, ValueError) as exc:
            summary["valid"] = False
            summary["validation_error"] = str(exc)
    else:
        summary["valid"] = True
    if summary["splits_present"]:
        try:
            split_data = json.loads((dataset_dir / SPLITS_NAME).read_text(encoding="utf-8"))
            if not isinstance(split_data, dict):
                raise ValueError(f"{SPLITS_NAME} must contain a JSON object.")
            summary["split_counts"] = split_data.get("sample_counts", {})
            summary["split_group_counts"] = split_data.get("group_counts", {})
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            summary["split_counts"] = {}
            summary["split_group_counts"] = {}
            summary["split_error"] = str(exc)
            summary["valid"] = False
            summary.setdefault("validation_error", str(exc))
    else:
        summary["split_counts"] = {}
        summary["split_group_counts"] = {}
    return summary


def _dataset_payload(dataset_id: str, dataset_dir: Path) -> dict[str, Any]:
    entries = _read_manifest(dataset_dir)
    split_data: dict[str, Any] = {}
    split_path = dataset_dir / SPLITS_NAME
    if split_path.is_file():
        try:
            split_data = json.loads(split_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            split_data = {}
    if not isinstance(split_data, dict):
        split_data = {}
    assignments = split_data.get("assignments", {})
    if not isinstance(assignments, dict):
        assignments = {}
    samples = []
    for item in entries:
        crop_id = item.get("crop_id")
        if not isinstance(crop_id, str):
            continue
        samples.append({
            "crop_id": crop_id,
            "text": item.get("text", ""),
            "text_style": item.get("text_style", "unknown"),
            "source_id": item.get("source_id", ""),
            "writer_id": item.get("writer_id") or "",
            "verified": item.get("verified") is True,
            "split": assignments.get(crop_id),
            "image_url": f"/api/ocr/datasets/{dataset_id}/samples/{crop_id}/image",
            "origin": item.get("origin", ""),
        })
    available_models = []
    runs_dir = dataset_dir / "training_runs"
    if runs_dir.is_dir():
        for run_dir in sorted(runs_dir.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True):
            model_dir = run_dir / "inference"
            if model_dir.is_dir() and any(model_dir.glob("*.pdiparams")):
                available_models.append({
                    "model_dir": str(model_dir.resolve()),
                    "label": run_dir.name,
                })
    return {
        "dataset_id": dataset_id,
        "dataset_dir": str(dataset_dir),
        "summary": _dataset_summary(dataset_dir),
        "samples": samples,
        "available_models": available_models,
    }


def paddle_python_supported(version_info: tuple[int, ...] | Any = sys.version_info) -> bool:
    """PaddlePaddle's published wheels currently target CPython 3.9 through 3.13."""
    try:
        major, minor = int(version_info[0]), int(version_info[1])
    except (TypeError, ValueError, IndexError):
        return False
    return (major, minor) >= (3, 9) and (major, minor) <= (3, 13)


def _paddle_gpu_available() -> bool:
    """Return true only when the installed Paddle build can see a CUDA device."""
    try:
        import paddle

        return bool(
            paddle.device.is_compiled_with_cuda()
            and paddle.device.cuda.device_count() > 0
        )
    except Exception:
        return False


def _require_supported_paddle_python() -> None:
    """Reject OCR jobs before spawning a process on an unsupported interpreter."""
    if not paddle_python_supported():
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        raise HTTPException(
            status_code=422,
            detail=(
                f"Planline is running Python {version}; PaddlePaddle wheels are "
                "supported here only on CPython 3.9–3.13. Install a compatible "
                "Planline runtime before starting OCR inference or training."
            ),
        )


@router.get("/status")
def ocr_studio_status() -> dict[str, Any]:
    """Report OCR dependencies and whether the installed Paddle build can use a GPU."""
    try:
        paddleocr_installed = importlib.util.find_spec("paddleocr") is not None
    except (ImportError, ValueError):
        paddleocr_installed = False
    try:
        paddle_installed = importlib.util.find_spec("paddle") is not None
    except (ImportError, ValueError):
        paddle_installed = False

    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_compatible = paddle_python_supported()
    paddle_cuda_available = _paddle_gpu_available() if paddle_installed and python_compatible else False
    if not python_compatible:
        training_note = (
            f"Planline is running Python {version}. PaddlePaddle's current published wheels "
            "support Python 3.9–3.13, so this runtime cannot host the OCR engine. "
            "Dataset annotation and crop storage still work; a separate compatible runtime is required."
        )
    elif not paddle_installed:
        training_note = (
            "This Python version is compatible, but PaddlePaddle is not installed. "
            "Run the Planline installer again to provision the PaddlePaddle and PaddleOCR runtime."
        )
    elif not paddleocr_installed:
        training_note = (
            "PaddlePaddle is installed, but the PaddleOCR inference package is missing. "
            "Run the Planline installer again to install the PaddleOCR inference package."
        )
    else:
        training_note = (
            "PaddlePaddle and PaddleOCR are available. OCR Studio can automatically prepare the pinned "
            "PaddleOCR source checkout and matching pretrained checkpoint before fine-tuning."
        )
    if paddle_installed and not paddle_cuda_available:
        training_note += " The installed PaddlePaddle runtime is CPU-only; GPU training and recognition are disabled."
    return {
        "status": "ok",
        "python_version": version,
        "python_executable": sys.executable,
        "python_compatible_for_paddle": python_compatible,
        "paddleocr_installed": paddleocr_installed,
        "paddle_installed": paddle_installed,
        "paddle_cuda_available": paddle_cuda_available,
        "training_supported": python_compatible,
        "training_runtime_ready": python_compatible and paddle_installed,
        "inference_runtime_ready": python_compatible and paddle_installed and paddleocr_installed,
        "dataset_root": str(OCR_DATASET_ROOT),
        "training_note": training_note,
    }


@router.get("/training-assets")
def get_training_assets(model_variant: str = "mobile") -> dict[str, Any]:
    try:
        return training_assets_status(model_variant)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/training-assets/prepare")
def prepare_training_assets(request: TrainingAssetsRequest) -> dict[str, Any]:
    try:
        return ensure_training_assets(request.model_variant)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not prepare official PaddleOCR training assets: {exc}",
        ) from exc


@router.get("/models")
def list_ocr_recognition_models() -> dict[str, Any]:
    """List supported base recognisers and exported models from local datasets."""
    models = [
        {"model_id": model_id, "label": model_name.replace("_", " "), "kind": "base"}
        for model_id, model_name in BASE_RECOGNITION_MODELS.items()
    ]
    if OCR_DATASET_ROOT.is_dir():
        for dataset_dir in sorted(OCR_DATASET_ROOT.iterdir(), key=lambda path: path.name.lower()):
            if not dataset_dir.is_dir() or not DATASET_ID_RE.fullmatch(dataset_dir.name):
                continue
            runs_dir = dataset_dir / "training_runs"
            if not runs_dir.is_dir():
                continue
            for run_dir in sorted(runs_dir.iterdir(), key=lambda path: path.name):
                inference_dir = run_dir / "inference"
                if run_dir.is_dir() and re.fullmatch(r"[a-f0-9]{12}", run_dir.name) and inference_dir.is_dir() and any(inference_dir.glob("*.pdiparams")):
                    models.append({
                        "model_id": f"trained:{dataset_dir.name}:{run_dir.name}",
                        "label": f"{dataset_dir.name} · {run_dir.name}",
                        "kind": "trained",
                    })
    return {"models": models}


@router.post("/recognize-review")
def recognize_review_crops(
    file: UploadFile = File(...),
    review_json: str = Form(...),
    model_id: str = Form("base:PP-OCRv5_mobile_rec"),
    device: str = Form("cpu"),
) -> dict[str, Any]:
    """Run optional PaddleOCR recognition on the dimension crops in a review export."""
    if device not in {"cpu", "gpu:0"}:
        raise HTTPException(status_code=422, detail="device must be cpu or gpu:0.")
    if device == "gpu:0" and not _paddle_gpu_available():
        raise HTTPException(status_code=422, detail="PaddlePaddle GPU support is not available in this installation; choose CPU.")
    if len(review_json.encode("utf-8")) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Review JSON limit is 2 MB.")
    if file.size is not None and file.size > MAX_CROP_BYTES:
        file.file.close()
        raise HTTPException(status_code=413, detail="Source drawing limit is 25 MB.")
    try:
        source_bytes = file.file.read(MAX_CROP_BYTES + 1)
    finally:
        file.file.close()
    if len(source_bytes) > MAX_CROP_BYTES:
        raise HTTPException(status_code=413, detail="Source drawing limit is 25 MB.")
    try:
        review = json.loads(review_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Review JSON is not valid.") from exc
    if not isinstance(review, dict) or review.get("schema_version") != "planline-detection-review/v1":
        raise HTTPException(status_code=422, detail="Unsupported Planline review format.")
    source = review.get("source") if isinstance(review.get("source"), dict) else {}
    page_index = source.get("page_index", 0)
    if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0:
        raise HTTPException(status_code=422, detail="Review source page index is invalid.")

    try:
        from .api import apply_image_adjustments, decode_upload
        from .ocr_paddle import recognize_review_crops

        filename = (file.filename or source.get("filename") or "drawing.png").strip()
        image, _source_info = decode_upload(source_bytes, filename, page_index=page_index)
        analysis = review.get("analysis", {})
        if not isinstance(analysis, dict):
            raise ValueError("Review analysis section is invalid.")
        preprocessing = analysis.get("preprocessing", {})
        if not isinstance(preprocessing, dict):
            preprocessing = {}
        try:
            brightness = float(preprocessing.get("brightness", 0.0))
            contrast = float(preprocessing.get("contrast", 1.0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Review image preprocessing settings are invalid.") from exc
        image = apply_image_adjustments(image, brightness=brightness, contrast=contrast)

        model_dir: Path | None = None
        model_name: str | None = None
        if model_id in BASE_RECOGNITION_MODELS:
            model_name = BASE_RECOGNITION_MODELS[model_id]
        elif model_id.startswith("trained:"):
            parts = model_id.split(":")
            if len(parts) != 3 or not re.fullmatch(r"[a-f0-9]{12}", parts[2]):
                raise ValueError("Selected fine-tuned model ID is invalid.")
            dataset_dir = _dataset_dir(parts[1])
            training_root = (dataset_dir / "training_runs").resolve()
            model_dir = (training_root / parts[2] / "inference").resolve()
            if not model_dir.is_relative_to(training_root) or not model_dir.is_dir() or not any(model_dir.glob("*.pdiparams")):
                raise ValueError("Selected fine-tuned model is missing or is outside this dataset's training_runs folder.")
        else:
            raise ValueError("Select a supported base recogniser or a local fine-tuned model.")

        from paddleocr import TextRecognition
        with _OCR_INFERENCE_LOCK:
            if model_dir is not None:
                recognizer = TextRecognition(model_dir=str(model_dir), device=device)
            else:
                recognizer = TextRecognition(model_name=model_name, device=device)
            predictions, skipped = recognize_review_crops(review, image, recognizer)
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="PaddleOCR is optional. Install a compatible PaddlePaddle runtime and PaddleOCR in the Planline Python environment.",
        ) from exc
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="OCR recognition failed. Check the local server log.") from exc

    return {
        "engine": "PaddleOCR",
        "model": model_name or str(model_dir),
        "device": device,
        "predictions": predictions,
        "skipped_crops": skipped,
        "notes": [
            "Predictions are unverified suggestions. Check every character against the source drawing.",
            "No unit parsing, dimension correction, wall association or geometry inference is performed.",
        ],
    }


@router.get("/datasets")
def list_ocr_datasets() -> dict[str, Any]:
    OCR_DATASET_ROOT.mkdir(parents=True, exist_ok=True)
    datasets = []
    for child in sorted(OCR_DATASET_ROOT.iterdir(), key=lambda path: path.name.lower()):
        if child.is_dir() and DATASET_ID_RE.fullmatch(child.name):
            datasets.append({
                "dataset_id": child.name,
                "summary": _dataset_summary(child),
            })
    return {"datasets": datasets, "dataset_root": str(OCR_DATASET_ROOT)}


@router.post("/datasets", status_code=201)
def create_ocr_dataset(request: CreateDatasetRequest) -> dict[str, Any]:
    slug = re.sub(r"[^a-z0-9_-]+", "-", request.name.strip().lower()).strip("-_")
    if not DATASET_ID_RE.fullmatch(slug):
        raise HTTPException(status_code=422, detail="Use a dataset name containing letters, numbers, dashes or underscores.")
    OCR_DATASET_ROOT.mkdir(parents=True, exist_ok=True)
    target = _dataset_dir(slug, must_exist=False)
    try:
        target.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="A dataset with that name already exists.") from exc
    (target / MANIFEST_NAME).write_text("", encoding="utf-8")
    return _dataset_payload(slug, target)


@router.get("/datasets/{dataset_id}")
def get_ocr_dataset(dataset_id: str) -> dict[str, Any]:
    dataset_dir = _dataset_dir(dataset_id)
    return _dataset_payload(dataset_id, dataset_dir)

@router.get("/datasets/{dataset_id}/export")
def export_ocr_dataset(dataset_id: str) -> FileResponse:
    """Download verified labels, crop images and split metadata without model checkpoints."""
    dataset_dir = _dataset_dir(dataset_id)
    try:
        validate_dataset(dataset_dir)
        entries = _read_manifest(dataset_dir)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    descriptor, archive_name = tempfile.mkstemp(prefix=f"planline-{dataset_id}-", suffix=".zip")
    os.close(descriptor)
    archive_path = Path(archive_name)
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(dataset_dir / MANIFEST_NAME, arcname=MANIFEST_NAME)
            split_path = dataset_dir / SPLITS_NAME
            if split_path.is_file():
                archive.write(split_path, arcname=SPLITS_NAME)
            for entry in entries:
                relative = entry.get("image_path")
                if not isinstance(relative, str):
                    raise ValueError("Dataset contains an invalid crop image path.")
                image_path = (dataset_dir / relative).resolve()
                if not image_path.is_relative_to(dataset_dir.resolve()) or not image_path.is_file():
                    raise ValueError("Dataset contains a missing or unsafe crop image path.")
                archive.write(image_path, arcname=relative)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        archive_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"planline-{dataset_id}-dataset.zip",
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )


@router.post("/datasets/{dataset_id}/import-archive", status_code=201)
async def import_ocr_dataset_archive(
    dataset_id: str,
    file: UploadFile = File(...),
    text_style: str = Form("handwritten"),
) -> dict[str, Any]:
    """Import verified pre-cropped samples from a ZIP containing one annotation CSV."""
    dataset_dir = _dataset_dir(dataset_id)
    if file.size is not None and file.size > 100 * 1024 * 1024:
        await file.close()
        raise HTTPException(status_code=413, detail="Dataset archive upload limit is 100 MB.")
    try:
        archive_bytes = await file.read(100 * 1024 * 1024 + 1)
    finally:
        await file.close()
    if len(archive_bytes) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Dataset archive upload limit is 100 MB.")

    try:
        with tempfile.TemporaryDirectory(prefix="planline-ocr-import-") as temporary:
            extract_root = Path(temporary).resolve()
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                all_members = archive.infolist()
                if not all_members or len(all_members) > 5000:
                    raise ValueError("The archive must contain no more than 5,000 entries.")
                members = [item for item in all_members if not item.is_dir()]
                if not members:
                    raise ValueError("The archive must contain at least one file.")
                if sum(item.file_size for item in members) > 250 * 1024 * 1024:
                    raise ValueError("The expanded dataset archive exceeds 250 MB.")
                if any(item.file_size > 10 * 1024 * 1024 for item in members if item.filename.lower().endswith(".csv")):
                    raise ValueError("The annotation CSV must be 10 MB or smaller.")
                csv_members = [item for item in members if item.filename.lower().endswith(".csv")]
                if len(csv_members) != 1:
                    raise ValueError("Include exactly one annotation CSV in the dataset archive.")

                extracted: dict[str, Path] = {}
                seen: set[str] = set()
                for member in members:
                    name = member.filename
                    relative = PurePosixPath(name)
                    if (
                        relative.is_absolute()
                        or "\\" in name
                        or any(part in {"", ".", ".."} for part in relative.parts)
                        or (relative.parts and ":" in relative.parts[0])
                    ):
                        raise ValueError("The archive contains an unsafe file path.")
                    normalized = relative.as_posix()
                    if normalized in seen:
                        raise ValueError("The archive contains duplicate file paths.")
                    seen.add(normalized)
                    if stat.S_ISLNK(member.external_attr >> 16):
                        raise ValueError("Symbolic links are not allowed in dataset archives.")
                    if member.flag_bits & 0x1:
                        raise ValueError("Encrypted dataset archives are not supported.")
                    if member.file_size > 25 * 1024 * 1024 and not normalized.lower().endswith(".csv"):
                        raise ValueError("Each crop image must be 25 MB or smaller.")
                    target = (extract_root / Path(*relative.parts)).resolve()
                    if not target.is_relative_to(extract_root):
                        raise ValueError("The archive contains a file outside its extraction folder.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    extracted[normalized] = target

            csv_path = extracted[csv_members[0].filename]
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if "image" not in (reader.fieldnames or []):
                    raise ValueError("The annotation CSV must include an image column.")
                for row_number, row in enumerate(reader, start=2):
                    raw_image = (row.get("image") or "").strip()
                    image_path = Path(raw_image)
                    if not raw_image or image_path.is_absolute():
                        raise ValueError(f"CSV image path must be relative on row {row_number}.")
                    resolved_image = (csv_path.parent / image_path).resolve()
                    if not resolved_image.is_relative_to(extract_root) or not resolved_image.is_file():
                        raise ValueError(f"CSV image on row {row_number} is missing or outside the archive.")
            result = import_crop_csv(csv_path, dataset_dir, text_style=text_style)
    except (OSError, ValueError, zipfile.BadZipFile, csv.Error) as exc:
        raise HTTPException(status_code=422, detail=f"Dataset archive could not be imported: {exc}") from exc

    return {**result, "dataset": _dataset_payload(dataset_id, dataset_dir)}


@router.get("/datasets/{dataset_id}/samples/{crop_id}/image")
def get_ocr_crop_image(dataset_id: str, crop_id: str) -> FileResponse:
    dataset_dir = _dataset_dir(dataset_id)
    item = next((entry for entry in _read_manifest(dataset_dir) if entry.get("crop_id") == crop_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Crop sample not found.")
    image_rel = item.get("image_path")
    if not isinstance(image_rel, str):
        raise HTTPException(status_code=400, detail="Crop image path is invalid.")
    image_path = (dataset_dir / image_rel).resolve()
    if not image_path.is_relative_to(dataset_dir.resolve()) or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Crop image file is missing.")
    return FileResponse(image_path, media_type="image/png", filename=f"{crop_id}.png")


@router.post("/datasets/{dataset_id}/samples", status_code=201)
async def add_ocr_crop(
    dataset_id: str,
    file: UploadFile = File(...),
    text: str = Form(...),
    source_id: str = Form(...),
    writer_id: str = Form(""),
    text_style: str = Form("handwritten"),
    verified: bool = Form(False),
) -> dict[str, Any]:
    dataset_dir = _dataset_dir(dataset_id)
    if not verified:
        raise HTTPException(status_code=422, detail="Check the transcription against the source drawing before saving it as a verified training label.")
    filename = (file.filename or "crop.png").strip()
    if file.size is not None and file.size > MAX_CROP_BYTES:
        await file.close()
        raise HTTPException(status_code=413, detail="Crop image limit is 25 MB.")
    try:
        image_bytes = await file.read(MAX_CROP_BYTES + 1)
    finally:
        await file.close()
    if len(image_bytes) > MAX_CROP_BYTES:
        raise HTTPException(status_code=413, detail="Crop image limit is 25 MB.")
    try:
        result = add_crop_sample(
            dataset_dir,
            image_bytes,
            filename,
            text=text,
            source_id=source_id,
            writer_id=writer_id,
            text_style=text_style,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "dataset": _dataset_payload(dataset_id, dataset_dir)}


@router.patch("/datasets/{dataset_id}/samples/{crop_id}")
def edit_ocr_crop(dataset_id: str, crop_id: str, request: UpdateSampleRequest) -> dict[str, Any]:
    dataset_dir = _dataset_dir(dataset_id)
    if not request.verified:
        raise HTTPException(status_code=422, detail="Only verified transcriptions can be saved to the training dataset.")
    try:
        result = update_crop_sample(
            dataset_dir,
            crop_id,
            text=request.text,
            source_id=request.source_id,
            writer_id=request.writer_id,
            text_style=request.text_style,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "dataset": _dataset_payload(dataset_id, dataset_dir)}


@router.delete("/datasets/{dataset_id}/samples/{crop_id}")
def remove_ocr_crop(dataset_id: str, crop_id: str) -> dict[str, Any]:
    dataset_dir = _dataset_dir(dataset_id)
    try:
        result = delete_crop_sample(dataset_dir, crop_id)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**result, "dataset": _dataset_payload(dataset_id, dataset_dir)}


@router.post("/datasets/{dataset_id}/splits")
def create_ocr_splits(dataset_id: str, request: CreateSplitsRequest) -> dict[str, Any]:
    dataset_dir = _dataset_dir(dataset_id)
    try:
        result = create_grouped_splits(dataset_dir, seed=request.seed, force=request.force)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"splits": result, "dataset": _dataset_payload(dataset_id, dataset_dir)}




@router.get("/datasets/{dataset_id}/quality")
def audit_ocr_dataset(dataset_id: str) -> dict[str, Any]:
    """Return a read-only audit of OCR labels, crop hashes and grouped splits."""
    dataset_dir = _dataset_dir(dataset_id)
    try:
        return audit_dataset(dataset_dir)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post("/datasets/{dataset_id}/train", status_code=202)
def start_ocr_training(dataset_id: str, request: StartTrainingRequest) -> dict[str, Any]:
    _require_supported_paddle_python()
    if request.use_gpu and not _paddle_gpu_available():
        raise HTTPException(status_code=422, detail="PaddlePaddle GPU support is not available in this installation; uncheck Use NVIDIA GPU.")
    if bool(request.paddleocr_dir) != bool(request.pretrained_model):
        raise HTTPException(status_code=422, detail="Provide both training asset paths or leave both empty for automatic setup.")
    try:
        if request.paddleocr_dir and request.pretrained_model:
            paddleocr_dir = Path(request.paddleocr_dir)
            pretrained_model = Path(request.pretrained_model)
        else:
            assets = ensure_training_assets(request.model_variant)
            paddleocr_dir = Path(assets["paddleocr_dir"])
            pretrained_model = Path(assets["pretrained_model"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not prepare official PaddleOCR training assets: {exc}") from exc

    dataset_dir = _dataset_dir(dataset_id)
    try:
        return start_training_job(
            dataset_dir,
            paddleocr_dir,
            pretrained_model,
            model_variant=request.model_variant,
            epochs=request.epochs,
            batch_size=request.batch_size,
            use_gpu=request.use_gpu,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/datasets/{dataset_id}/benchmark", status_code=202)
def start_ocr_benchmark(dataset_id: str, request: StartBenchmarkRequest) -> dict[str, Any]:
    _require_supported_paddle_python()
    if request.device.startswith("gpu") and not _paddle_gpu_available():
        raise HTTPException(status_code=422, detail="PaddlePaddle GPU support is not available in this installation; choose CPU.")
    dataset_dir = _dataset_dir(dataset_id)
    try:
        model_dir = Path(request.model_dir) if request.model_dir else None
        return start_benchmark_job(
            dataset_dir,
            model=request.model,
            model_dir=model_dir,
            device=request.device,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/jobs")
def list_ocr_jobs() -> dict[str, Any]:
    return {"jobs": list_jobs()}


@router.get("/jobs/{job_id}")
def get_ocr_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="OCR job not found.")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_ocr_job(job_id: str) -> dict[str, Any]:
    job = cancel_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="OCR job not found.")
    return job

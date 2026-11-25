"""Local-only API routes for the OCR dataset and training workbench."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
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
    validate_dataset,
    update_crop_sample,
)
from .ocr_training import cancel_job, get_job, start_benchmark_job, start_training_job

OCR_DATASET_ROOT = Path(__file__).resolve().parents[1] / "datasets" / "ocr"
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
    verified: bool = True


class CreateSplitsRequest(BaseModel):
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    force: bool = False


class StartTrainingRequest(BaseModel):
    paddleocr_dir: str = Field(min_length=1, max_length=2048)
    pretrained_model: str = Field(min_length=1, max_length=2048)
    model_variant: str = "mobile"
    epochs: int = Field(default=30, ge=1, le=500)
    batch_size: int = Field(default=8, ge=1, le=32)
    use_gpu: bool = True


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
            summary["split_counts"] = split_data.get("sample_counts", {})
            summary["split_group_counts"] = split_data.get("group_counts", {})
        except (OSError, json.JSONDecodeError):
            summary["split_counts"] = {}
            summary["split_group_counts"] = {}
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
        except json.JSONDecodeError:
            split_data = {}
    assignments = split_data.get("assignments", {})
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


@router.get("/status")
def ocr_studio_status() -> dict[str, Any]:
    """Check optional OCR dependencies without importing GPU libraries."""
    try:
        paddleocr_installed = importlib.util.find_spec("paddleocr") is not None
    except (ImportError, ValueError):
        paddleocr_installed = False
    try:
        paddle_installed = importlib.util.find_spec("paddle") is not None
    except (ImportError, ValueError):
        paddle_installed = False
    return {
        "status": "ok",
        "paddleocr_installed": paddleocr_installed,
        "paddle_installed": paddle_installed,
        "dataset_root": str(OCR_DATASET_ROOT),
        "training_supported": True,
        "training_note": "Fine-tuning requires a local PaddleOCR source checkout and a matching .pdparams checkpoint.",
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


@router.post("/datasets/{dataset_id}/train", status_code=202)
def start_ocr_training(dataset_id: str, request: StartTrainingRequest) -> dict[str, Any]:
    dataset_dir = _dataset_dir(dataset_id)
    try:
        return start_training_job(
            dataset_dir,
            Path(request.paddleocr_dir),
            Path(request.pretrained_model),
            model_variant=request.model_variant,
            epochs=request.epochs,
            batch_size=request.batch_size,
            use_gpu=request.use_gpu,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/datasets/{dataset_id}/benchmark", status_code=202)
def start_ocr_benchmark(dataset_id: str, request: StartBenchmarkRequest) -> dict[str, Any]:
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

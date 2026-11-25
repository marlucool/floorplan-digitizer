"""Planline local API.

This service deliberately keeps processing stages explicit. It stores source files
locally and exposes a stable project/review/export API; it does not claim to run
OCR or reconstruct geometry unless an analyser is configured.
"""

from __future__ import annotations

import json
import re
import struct
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from backend.pipeline.preflight import inspect_source

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "runtime" / "projects"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".pdf"}

app = FastAPI(title="Planline local API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


class MeasurementPatch(BaseModel):
    value_mm: int = Field(gt=0, le=1_000_000)
    verified: bool


def now() -> str:
    return datetime.now(UTC).isoformat()


def project_dir(project_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9-]{36}", project_id):
        raise HTTPException(404, "Project not found")
    return DATA / project_id


def record_path(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def read_project(project_id: str) -> dict[str, Any]:
    path = record_path(project_id)
    if not path.is_file():
        raise HTTPException(404, "Project not found")
    return json.loads(path.read_text(encoding="utf-8"))


def write_project(project: dict[str, Any]) -> None:
    path = record_path(project["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(project, indent=2), encoding="utf-8")


def image_size(data: bytes, suffix: str) -> tuple[int, int] | None:
    """Read PNG/JPEG/WebP dimensions without image decoding dependencies."""
    if suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if suffix in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 < len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            length = struct.unpack(">H", data[offset:offset + 2])[0]
            if marker in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0)):
                return struct.unpack(">HH", data[offset + 3:offset + 7])[::-1]
            offset += length
    if suffix == ".webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8X" and len(data) >= 30:
            return (1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little"))
    return None


def public_project(project: dict[str, Any]) -> dict[str, Any]:
    copy = dict(project)
    copy.pop("source_path", None)
    copy["source_url"] = f"/api/projects/{project['id']}/source"
    return copy


def dxf_for_measurements(measurements: list[dict[str, Any]]) -> str:
    width = sum(item["value_mm"] for item in measurements)
    x1 = measurements[0]["value_mm"]
    x2 = x1 + measurements[1]["value_mm"]
    height = 7000
    lines = [(0, 0, width, 0), (width, 0, width, height), (width, height, 0, height), (0, height, 0, 0),
             (x1, 0, x1, height), (x2, 0, x2, height)]
    pairs: list[str] = []
    def add(code: int, value: Any) -> None:
        pairs.extend((str(code), str(value)))
    add(0, "SECTION"); add(2, "HEADER"); add(9, "$INSUNITS"); add(70, 4); add(0, "ENDSEC")
    add(0, "SECTION"); add(2, "ENTITIES")
    for x_a, y_a, x_b, y_b in lines:
        add(0, "LINE"); add(8, "WALLS"); add(10, x_a); add(20, y_a); add(11, x_b); add(21, y_b)
    add(0, "ENDSEC"); add(0, "EOF")
    return "\r\n".join(pairs) + "\r\n"


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "planline-local-api", "ocr": "not_configured", "geometry": "not_configured"}


@app.post("/api/projects", status_code=201)
async def create_project(file: UploadFile = File(...)) -> JSONResponse:
    filename = Path(file.filename or "drawing").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, "Use PNG, JPG, WEBP, TIFF, or PDF.")
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 50 MB.")
    project_id = str(uuid.uuid4())
    folder = project_dir(project_id)
    folder.mkdir(parents=True, exist_ok=False)
    source_path = folder / f"source{suffix}"
    source_path.write_bytes(contents)
    size = image_size(contents, suffix)
    project = {
        "id": project_id,
        "created_at": now(),
        "updated_at": now(),
        "filename": filename,
        "content_type": file.content_type or "application/octet-stream",
        "size_bytes": len(contents),
        "image_size": {"width": size[0], "height": size[1]} if size else None,
        "source_path": str(source_path),
        "analysis": {
            "state": "waiting",
            "message": "Ready for a configured local analysis pipeline.",
            "stages": [
                {"name": "preprocess", "state": "not_started"},
                {"name": "detect", "state": "not_started"},
                {"name": "ocr", "state": "not_started"},
                {"name": "constraints", "state": "not_started"},
                {"name": "reconstruct", "state": "not_started"},
            ],
        },
        "measurements": [],
        "geometry": None,
    }
    write_project(project)
    return JSONResponse(public_project(project), status_code=201)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    return public_project(read_project(project_id))


@app.get("/api/projects/{project_id}/source")
def get_source(project_id: str) -> FileResponse:
    project = read_project(project_id)
    source = Path(project["source_path"])
    if not source.is_file():
        raise HTTPException(404, "Source file missing")
    return FileResponse(source, media_type=project["content_type"], filename=project["filename"])


@app.post("/api/projects/{project_id}/analyze")
def analyze(project_id: str) -> dict[str, Any]:
    project = read_project(project_id)
    preflight = inspect_source(
        Path(project["source_path"]),
        Path(project["filename"]).suffix.lower(),
        project.get("image_size"),
    )
    (project_dir(project_id) / "preflight.json").write_text(json.dumps(preflight, indent=2), encoding="utf-8")
    project["analysis"] = {
        "state": "blocked",
        "message": "Source preflight is complete. No OCR or geometry analyser is configured.",
        "next_step": "Configure a detector/OCR adapter, then rerun analysis.",
        "preflight": {"image_size": preflight["image_size"], "findings": preflight["findings"]},
        "stages": [
            {"name": "preprocess", "state": "complete", "kind": "source_preflight", "findings": preflight["findings"]},
            {"name": "detect", "state": "blocked"},
            {"name": "ocr", "state": "blocked"},
            {"name": "constraints", "state": "blocked"},
            {"name": "reconstruct", "state": "blocked"},
        ],
    }
    project["updated_at"] = now()
    write_project(project)
    return public_project(project)


@app.patch("/api/projects/{project_id}/measurements/{measurement_id}")
def update_measurement(project_id: str, measurement_id: str, patch: MeasurementPatch) -> dict[str, Any]:
    project = read_project(project_id)
    for measurement in project["measurements"]:
        if measurement.get("id") == measurement_id:
            measurement.update(patch.model_dump())
            project["updated_at"] = now()
            write_project(project)
            return public_project(project)
    raise HTTPException(404, "Measurement not found. Analysis must create measurements before review.")


@app.get("/api/projects/{project_id}/export.dxf")
def export_dxf(project_id: str) -> PlainTextResponse:
    project = read_project(project_id)
    measurements = project["measurements"]
    if not measurements or not all(item.get("verified") for item in measurements):
        raise HTTPException(409, "DXF export requires reviewed measurements and verified geometry.")
    if not project.get("geometry"):
        raise HTTPException(409, "DXF export requires verified geometry from the local analyser.")
    return PlainTextResponse(dxf_for_measurements(measurements), media_type="application/dxf", headers={"Content-Disposition": "attachment; filename=planline-floorplan.dxf"})


app.mount("/", StaticFiles(directory=ROOT, html=True), name="frontend")

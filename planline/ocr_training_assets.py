"""Provision pinned PaddleOCR source and official recognition checkpoints."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

PADDLEOCR_VERSION = "v3.3.1"
SOURCE_URL = f"https://github.com/PaddlePaddle/PaddleOCR/archive/refs/tags/{PADDLEOCR_VERSION}.zip"
WEIGHT_BASE_URL = (
    "https://paddle-model-ecology.bj.bcebos.com/"
    "paddlex/official_pretrained_model"
)
MODEL_VARIANTS = {"mobile", "server"}
_MIN_ASSET_BYTES = 1024 * 1024
_MAX_SOURCE_BYTES = 250 * 1024 * 1024
_MAX_WEIGHT_BYTES = 1024 * 1024 * 1024
_PROVISION_LOCK = threading.Lock()


def training_assets_root() -> Path:
    """Keep downloaded source and weights beside, but separate from, user datasets."""
    configured = os.environ.get("PLANLINE_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve() / "ocr" / "_training_assets"
    return Path(__file__).resolve().parents[1] / "datasets" / "ocr" / "_training_assets"


def _paths(root: Path, model_variant: str) -> dict[str, Path]:
    if model_variant not in MODEL_VARIANTS:
        raise ValueError("model_variant must be mobile or server.")
    source_dir = root / f"PaddleOCR-{PADDLEOCR_VERSION}"
    config_name = f"PP-OCRv5_{model_variant}_rec.yml"
    config_path = source_dir / "configs" / "rec" / "PP-OCRv5" / config_name
    weights_name = f"PP-OCRv5_{model_variant}_rec_pretrained.pdparams"
    weights_path = root / "weights" / weights_name
    return {
        "root": root,
        "source_dir": source_dir,
        "config_path": config_path,
        "weights_path": weights_path,
        "archive_path": root / "archives" / f"PaddleOCR-{PADDLEOCR_VERSION}.zip",
    }


def training_assets_status(model_variant: str = "mobile", *, root: Path | None = None) -> dict[str, Any]:
    paths = _paths(root or training_assets_root(), model_variant)
    source_ready = (paths["source_dir"] / "tools" / "train.py").is_file()
    config_ready = paths["config_path"].is_file()
    weights_ready = paths["weights_path"].is_file() and paths["weights_path"].stat().st_size >= _MIN_ASSET_BYTES
    missing = []
    if not source_ready or not config_ready:
        missing.append("source")
    if not weights_ready:
        missing.append("weights")
    return {
        "ready": not missing,
        "model_variant": model_variant,
        "source_version": PADDLEOCR_VERSION,
        "paddleocr_dir": str(paths["source_dir"]) if source_ready else "",
        "config_path": str(paths["config_path"]) if config_ready else "",
        "pretrained_model": str(paths["weights_path"]) if weights_ready else "",
        "missing": missing,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_atomic(url: str, destination: Path, *, max_bytes: int) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and _MIN_ASSET_BYTES <= destination.stat().st_size <= max_bytes:
        return _sha256_file(destination)

    temporary = destination.with_name(destination.name + f".{os.getpid()}.part")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Planline-OCR-Asset-Setup/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise OSError(f"Download returned HTTP {status}: {url}")
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise ValueError(f"Download exceeds the permitted size: {url}")
            total = 0
            with temporary.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"Download exceeds the permitted size: {url}")
                    output.write(chunk)
        if total < _MIN_ASSET_BYTES:
            raise OSError(f"Downloaded asset is unexpectedly small ({total} bytes): {url}")
        digest = _sha256_file(temporary)
        os.replace(temporary, destination)
        return digest
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _extract_paddleocr_source(archive_path: Path, destination: Path) -> None:
    temporary_root = Path(tempfile.mkdtemp(prefix="paddleocr-extract-", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise zipfile.BadZipFile(f"Corrupt source archive member: {bad_member}")
            names = archive.namelist()
            prefix = next(
                (
                    PurePosixPath(name).parts[0]
                    for name in names
                    if name.endswith("tools/train.py") and len(PurePosixPath(name).parts) > 1
                ),
                None,
            )
            if prefix is None:
                raise zipfile.BadZipFile("PaddleOCR archive does not contain tools/train.py.")

            root = temporary_root.resolve()
            for member in archive.infolist():
                parts = PurePosixPath(member.filename).parts
                if not parts or parts[0] != prefix:
                    continue
                relative = Path(*parts[1:])
                if not relative.parts or any(part in {"..", ""} for part in relative.parts):
                    continue
                target = (temporary_root / relative).resolve()
                if not target.is_relative_to(root):
                    raise zipfile.BadZipFile("PaddleOCR source archive contains an unsafe path.")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)

        if not (temporary_root / "tools" / "train.py").is_file():
            raise zipfile.BadZipFile("Extracted PaddleOCR source is missing tools/train.py.")
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(temporary_root, destination)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise


def ensure_training_assets(
    model_variant: str = "mobile",
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Download and validate the pinned source checkout and matching official weights."""
    paths = _paths(root or training_assets_root(), model_variant)
    with _PROVISION_LOCK:
        paths["root"].mkdir(parents=True, exist_ok=True)
        source_archive_sha256 = None
        if not (paths["source_dir"] / "tools" / "train.py").is_file() or not paths["config_path"].is_file():
            source_archive_sha256 = _download_atomic(
                SOURCE_URL, paths["archive_path"], max_bytes=_MAX_SOURCE_BYTES
            )
            try:
                _extract_paddleocr_source(paths["archive_path"], paths["source_dir"])
            except zipfile.BadZipFile:
                # A truncated cached archive must not poison every future retry.
                paths["archive_path"].unlink(missing_ok=True)
                source_archive_sha256 = _download_atomic(
                    SOURCE_URL, paths["archive_path"], max_bytes=_MAX_SOURCE_BYTES
                )
                _extract_paddleocr_source(paths["archive_path"], paths["source_dir"])

        weight_url = f"{WEIGHT_BASE_URL}/PP-OCRv5_{model_variant}_rec_pretrained.pdparams"
        _download_atomic(weight_url, paths["weights_path"], max_bytes=_MAX_WEIGHT_BYTES)

        status = training_assets_status(model_variant, root=paths["root"])
        if not status["ready"]:
            raise OSError(
                "PaddleOCR training assets are incomplete after download: "
                + ", ".join(status["missing"])
            )

        manifest = {
            "source_version": PADDLEOCR_VERSION,
            "model_variant": model_variant,
            "paddleocr_dir": status["paddleocr_dir"],
            "config_path": status["config_path"],
            "pretrained_model": status["pretrained_model"],
            "source_archive_sha256": source_archive_sha256,
            "weights_sha256": _sha256_file(paths["weights_path"]),
        }
        manifest_path = paths["root"] / "asset_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return status

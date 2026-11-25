"""Local PaddleOCR recognition fine-tuning jobs for Planline datasets.

Training uses an external PaddleOCR source checkout and a local pretrained
checkpoint. Dataset preparation and all subprocess logs stay under datasets/.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dataset import export_paddle_rec_dataset

MODEL_CONFIGS = {
    "mobile": "configs/rec/PP-OCRv5/PP-OCRv5_mobile_rec.yml",
    "server": "configs/rec/PP-OCRv5/PP-OCRv5_server_rec.yml",
}

_JOBS: dict[str, dict[str, Any]] = {}
_PROCESSES: dict[str, subprocess.Popen[str]] = {}
_JOB_LOCK = threading.RLock()


def _yaml_string(value: Path | str) -> str:
    """JSON strings are also valid YAML scalars and safely preserve spaces."""
    return json.dumps(str(value))


def build_training_command(
    paddleocr_dir: Path,
    config_path: Path,
    pretrained_model: Path,
    training_data: Path,
    output_dir: Path,
    *,
    epochs: int = 30,
    batch_size: int = 8,
    use_gpu: bool = True,
    python_executable: str = sys.executable,
) -> list[str]:
    """Build a shell-free PaddleOCR fine-tuning command."""
    if epochs < 1 or epochs > 500:
        raise ValueError("epochs must be between 1 and 500.")
    if batch_size not in {1, 2, 4, 8, 16, 32}:
        raise ValueError("batch_size must be one of 1, 2, 4, 8, 16 or 32.")
    for path, description in (
        (paddleocr_dir / "tools" / "train.py", "PaddleOCR tools/train.py"),
        (config_path, "PaddleOCR recognition config"),
        (pretrained_model, "pretrained .pdparams file"),
        (training_data / "train_list.txt", "training labels"),
        (training_data / "val_list.txt", "validation labels"),
    ):
        if not path.is_file():
            raise ValueError(f"Could not find {description}: {path}")

    overrides = [
        f"Global.pretrained_model={_yaml_string(pretrained_model.resolve())}",
        f"Global.save_model_dir={_yaml_string(output_dir.resolve())}",
        f"Global.epoch_num={epochs}",
        f"Global.use_gpu={'true' if use_gpu else 'false'}",
        "Global.distributed=false",
        "Global.save_epoch_step=1",
        f"Train.dataset.data_dir={_yaml_string(training_data.resolve())}",
        f"Train.dataset.label_file_list=[{_yaml_string((training_data / 'train_list.txt').resolve())}]",
        f"Eval.dataset.data_dir={_yaml_string(training_data.resolve())}",
        f"Eval.dataset.label_file_list=[{_yaml_string((training_data / 'val_list.txt').resolve())}]",
        f"Train.sampler.first_bs={batch_size}",
        f"Train.loader.batch_size_per_card={batch_size}",
        f"Eval.loader.batch_size_per_card={batch_size}",
        "Train.loader.num_workers=2",
        "Eval.loader.num_workers=1",
    ]
    return [
        python_executable,
        str((paddleocr_dir / "tools" / "train.py").resolve()),
        "-c",
        str(config_path.resolve()),
        "-o",
        *overrides,
    ]


def _append_log(job_id: str, line: str) -> None:
    clean = line.rstrip("\r\n")
    if not clean:
        return
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["_log_lines"].append(clean)
        job["_log_lines"] = job["_log_lines"][-300:]
        match = re.search(r"epoch\s*:\s*\[\s*(\d+)\s*/\s*(\d+)\s*\]", clean, re.I)
        if match:
            job["epoch"] = int(match.group(1))
            job["epochs"] = int(match.group(2))


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in job.items()
        if not key.startswith("_") and key not in {"thread", "cancel_event"}
    } | {"logs": "\n".join(job.get("_log_lines", []))}


def get_job(job_id: str) -> dict[str, Any] | None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        return _public_job(job) if job else None


def _run_process(job_id: str, command: list[str], cwd: Path, step: str) -> int:
    with _JOB_LOCK:
        job = _JOBS[job_id]
        if job["cancel_event"].is_set():
            return 130
        job["current_step"] = step
        job["status"] = "running"
    _append_log(job_id, "$ " + subprocess.list2cmdline(command))
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=os.environ.copy(),
    )
    with _JOB_LOCK:
        _PROCESSES[job_id] = process
    assert process.stdout is not None
    for line in process.stdout:
        _append_log(job_id, line)
        with _JOB_LOCK:
            should_stop = _JOBS[job_id]["cancel_event"].is_set()
        if should_stop and process.poll() is None:
            process.terminate()
    return_code = process.wait()
    with _JOB_LOCK:
        _PROCESSES.pop(job_id, None)
    return return_code


def _finish(job_id: str, status: str, **fields: Any) -> None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.update(fields)
        job["status"] = status
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
        job["current_step"] = "finished" if status == "completed" else status


def _start_thread(job: dict[str, Any], target, args: tuple[Any, ...]) -> dict[str, Any]:
    with _JOB_LOCK:
        _JOBS[job["job_id"]] = job
    thread = threading.Thread(target=target, args=args, daemon=True, name=f"planline-ocr-{job['job_id']}")
    job["thread"] = thread
    thread.start()
    return get_job(job["job_id"]) or {}


def start_training_job(
    dataset_dir: Path,
    paddleocr_dir: Path,
    pretrained_model: Path,
    *,
    model_variant: str = "mobile",
    epochs: int = 30,
    batch_size: int = 8,
    use_gpu: bool = True,
) -> dict[str, Any]:
    """Validate paths/splits, prepare data and start a background fine-tune."""
    if model_variant not in MODEL_CONFIGS:
        raise ValueError("model_variant must be mobile or server.")
    if epochs < 1 or epochs > 500:
        raise ValueError("epochs must be between 1 and 500.")
    if batch_size not in {1, 2, 4, 8, 16, 32}:
        raise ValueError("batch_size must be one of 1, 2, 4, 8, 16 or 32.")
    source_dir = paddleocr_dir.expanduser().resolve()
    checkpoint = pretrained_model.expanduser().resolve()
    config_path = source_dir / MODEL_CONFIGS[model_variant]
    if not (source_dir / "tools" / "train.py").is_file():
        raise ValueError("PaddleOCR source folder must contain tools/train.py.")
    if not config_path.is_file():
        raise ValueError(f"PaddleOCR config not found: {config_path}")
    if not checkpoint.is_file() or checkpoint.suffix.lower() != ".pdparams":
        raise ValueError("Select the matching PaddleOCR pretrained .pdparams checkpoint file.")

    job_id = uuid.uuid4().hex[:12]
    run_dir = (dataset_dir / "training_runs" / job_id).resolve()
    if not run_dir.is_relative_to(dataset_dir.resolve()):
        raise ValueError("Training output path escapes the selected dataset.")
    split_path = dataset_dir / "splits.json"
    if not split_path.is_file():
        raise ValueError("Build source/writer-grouped train/validation/test splits before training.")
    split_data = json.loads(split_path.read_text(encoding="utf-8"))
    assignments = split_data.get("assignments", {})
    if not any(value == "test" for value in assignments.values()):
        raise ValueError("The split plan has no held-out test samples. Rebuild splits with at least three independent groups.")
    training_data = run_dir / "train_data"
    exported = export_paddle_rec_dataset(dataset_dir, training_data)
    if exported["test_samples"] < 1:
        raise ValueError("No held-out test samples are available. Rebuild the dataset splits.")
    checkpoint_dir = run_dir / "checkpoints"
    command = build_training_command(
        source_dir, config_path, checkpoint, training_data, checkpoint_dir,
        epochs=epochs, batch_size=batch_size, use_gpu=use_gpu,
    )
    job = {
        "job_id": job_id,
        "kind": "training",
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "current_step": "queued",
        "epoch": 0,
        "epochs": epochs,
        "model_variant": model_variant,
        "training_samples": exported["training_samples"],
        "validation_samples": exported["validation_samples"],
        "test_samples": exported["test_samples"],
        "output_dir": str(run_dir),
        "model_dir": None,
        "cancel_event": threading.Event(),
        "_log_lines": [
            f"Prepared {exported['training_samples']} training and {exported['validation_samples']} validation crops.",
            f"Held-out test crops excluded from optimisation: {exported['test_samples']}.",
            "Fine-tuning starts from the selected pretrained recogniser; a small dataset can overfit.",
        ],
    }
    return _start_thread(job, _training_worker, (job_id, command, source_dir, config_path, checkpoint_dir, use_gpu))


def _training_worker(
    job_id: str,
    command: list[str],
    paddleocr_dir: Path,
    config_path: Path,
    checkpoint_dir: Path,
    use_gpu: bool,
) -> None:
    try:
        return_code = _run_process(job_id, command, paddleocr_dir, "fine-tuning")
        with _JOB_LOCK:
            cancelled = _JOBS[job_id]["cancel_event"].is_set()
        if cancelled:
            _finish(job_id, "cancelled")
            return
        if return_code != 0:
            _finish(job_id, "failed", error=f"PaddleOCR training exited with code {return_code}.")
            return

        weights = next(
            (path for path in (checkpoint_dir / "best_accuracy.pdparams", checkpoint_dir / "latest.pdparams") if path.is_file()),
            None,
        )
        if weights is None:
            _finish(
                job_id,
                "completed_no_export",
                error="Training exited successfully, but no best_accuracy.pdparams or latest.pdparams checkpoint was produced.",
            )
            return
        run_dir = checkpoint_dir.parent
        inference_dir = run_dir / "inference"
        export_command = [
            sys.executable,
            str((paddleocr_dir / "tools" / "export_model.py").resolve()),
            "-c",
            str(config_path.resolve()),
            "-o",
            f"Global.pretrained_model={_yaml_string(weights.resolve())}",
            f"Global.save_inference_dir={_yaml_string(inference_dir.resolve())}",
            f"Global.use_gpu={'true' if use_gpu else 'false'}",
            "Global.distributed=false",
        ]
        export_return = _run_process(job_id, export_command, paddleocr_dir, "exporting-inference-model")
        with _JOB_LOCK:
            cancelled = _JOBS[job_id]["cancel_event"].is_set()
        if cancelled:
            _finish(job_id, "cancelled", checkpoint=str(weights))
            return
        if export_return != 0:
            _finish(job_id, "completed_no_export", error=f"Training succeeded but model export exited with code {export_return}.", checkpoint=str(weights))
            return
        _finish(
            job_id,
            "completed",
            checkpoint=str(weights),
            model_dir=str(inference_dir),
        )
        _append_log(job_id, f"Exported inference model: {inference_dir}")
    except Exception as exc:
        _append_log(job_id, f"ERROR: {type(exc).__name__}: {exc}")
        _finish(job_id, "failed", error=str(exc))


def start_benchmark_job(
    dataset_dir: Path,
    *,
    model: str = "PP-OCRv5_mobile_rec",
    model_dir: Path | None = None,
    device: str = "cpu",
) -> dict[str, Any]:
    """Run OCR over all crops, then score only the held-out test split."""
    if device not in {"cpu", "gpu:0"}:
        raise ValueError("device must be cpu or gpu:0.")
    from .dataset import validate_dataset

    validate_dataset(dataset_dir)
    split_path = dataset_dir / "splits.json"
    if not split_path.is_file():
        raise ValueError("Build source/writer-grouped train/validation/test splits before benchmarking OCR.")
    split_data = json.loads(split_path.read_text(encoding="utf-8"))
    assignments = split_data.get("assignments", {})
    if not any(value == "test" for value in assignments.values()):
        raise ValueError("The dataset split plan has no held-out test samples. Rebuild splits with at least three independent groups.")
    if model_dir is not None:
        selected_model_dir = model_dir.expanduser().resolve()
        if (
            not selected_model_dir.is_dir()
            or not selected_model_dir.is_relative_to((dataset_dir / "training_runs").resolve())
            or not any(selected_model_dir.glob("*.pdiparams"))
        ):
            raise ValueError("Select an exported fine-tuned model from this dataset's training_runs folder.")
    else:
        selected_model_dir = None
    job_id = uuid.uuid4().hex[:12]
    result_dir = dataset_dir / "benchmarks" / job_id
    result_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = result_dir / "predictions.json"
    metrics_path = result_dir / "metrics.json"
    command = [
        sys.executable,
        "-m",
        "planline.ocr_paddle",
        "--dataset",
        str(dataset_dir.resolve()),
        "--output",
        str(prediction_path.resolve()),
        "--device",
        device,
    ]
    if selected_model_dir:
        command.extend(["--model-dir", str(selected_model_dir)])
        selected_model = str(selected_model_dir)
    else:
        command.extend(["--model", model])
        selected_model = model
    job = {
        "job_id": job_id,
        "kind": "benchmark",
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "current_step": "queued",
        "model": selected_model,
        "metrics": None,
        "metrics_path": str(metrics_path),
        "cancel_event": threading.Event(),
        "_log_lines": ["OCR predictions are generated for the dataset; evaluation scores only the held-out test split."],
    }
    return _start_thread(job, _benchmark_worker, (job_id, command, dataset_dir.resolve(), prediction_path, metrics_path))


def _benchmark_worker(
    job_id: str,
    command: list[str],
    dataset_dir: Path,
    prediction_path: Path,
    metrics_path: Path,
) -> None:
    try:
        code = _run_process(job_id, command, Path(__file__).resolve().parents[1], "OCR inference")
        with _JOB_LOCK:
            cancelled = _JOBS[job_id]["cancel_event"].is_set()
        if cancelled:
            _finish(job_id, "cancelled")
            return
        if code != 0:
            _finish(job_id, "failed", error=f"OCR inference exited with code {code}. Is PaddleOCR installed in this Python environment?")
            return
        eval_command = [
            sys.executable,
            "-m",
            "planline.ocr_eval",
            "--dataset",
            str(dataset_dir),
            "--predictions",
            str(prediction_path),
            "--output",
            str(metrics_path),
        ]
        eval_code = _run_process(job_id, eval_command, Path(__file__).resolve().parents[1], "held-out test evaluation")
        with _JOB_LOCK:
            cancelled = _JOBS[job_id]["cancel_event"].is_set()
        if cancelled:
            _finish(job_id, "cancelled")
            return
        if eval_code != 0:
            _finish(job_id, "failed", error=f"Held-out test evaluation exited with code {eval_code}.")
            return
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        _finish(job_id, "completed", metrics=metrics, predictions=str(prediction_path))
    except Exception as exc:
        _append_log(job_id, f"ERROR: {type(exc).__name__}: {exc}")
        _finish(job_id, "failed", error=str(exc))


def cancel_job(job_id: str) -> dict[str, Any] | None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        job["cancel_event"].set()
        process = _PROCESSES.get(job_id)
        if process is not None and process.poll() is None:
            process.terminate()
        return _public_job(job)

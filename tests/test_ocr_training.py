from __future__ import annotations

from pathlib import Path

import pytest

from planline.ocr_training import build_training_command


def test_build_training_command_overrides_data_checkpoint_and_small_batch(tmp_path: Path) -> None:
    source = tmp_path / "PaddleOCR"
    (source / "tools").mkdir(parents=True)
    (source / "tools" / "train.py").write_text("# training entrypoint")
    config = source / "configs" / "rec.yml"
    config.parent.mkdir(parents=True)
    config.write_text("Global: {}")
    checkpoint = tmp_path / "mobile.pdparams"
    checkpoint.write_bytes(b"test")
    data = tmp_path / "train data"
    data.mkdir()
    (data / "train_list.txt").write_text("images/a.png\t4200\n")
    (data / "val_list.txt").write_text("images/b.png\t3000\n")

    command = build_training_command(
        source, config, checkpoint, data, tmp_path / "output",
        epochs=12, batch_size=4, use_gpu=True,
    )

    assert command[1] == str((source / "tools" / "train.py").resolve())
    assert "Global.epoch_num=12" in command
    assert "Train.sampler.first_bs=4" in command
    assert any(item.startswith("Train.dataset.data_dir=") and "train data" in item for item in command)
    assert any(item.startswith("Global.pretrained_model=") and "mobile.pdparams" in item for item in command)


def test_build_training_command_rejects_unsafe_settings(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="epochs"):
        build_training_command(tmp_path, tmp_path / "config", tmp_path / "weights", tmp_path, tmp_path, epochs=0)
    with pytest.raises(ValueError, match="batch_size"):
        build_training_command(tmp_path, tmp_path / "config", tmp_path / "weights", tmp_path, tmp_path, batch_size=3)



def test_quiet_training_process_is_cancelled_without_waiting_for_output(tmp_path: Path) -> None:
    """Cancellation must work even when the child process never writes to stdout."""
    import sys
    import threading
    import time
    import uuid

    from planline import ocr_training

    job_id = uuid.uuid4().hex
    cancel_event = threading.Event()
    with ocr_training._JOB_LOCK:
        ocr_training._JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "cancel_event": cancel_event,
            "_log_lines": [],
        }

    result: dict[str, int] = {}
    runner = threading.Thread(
        target=lambda: result.setdefault(
            "return_code",
            ocr_training._run_process(
                job_id,
                [sys.executable, "-c", "import time; time.sleep(30)"],
                tmp_path,
                "quiet-process-test",
            ),
        ),
        daemon=True,
    )
    runner.start()

    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with ocr_training._JOB_LOCK:
                process_started = job_id in ocr_training._PROCESSES
            if process_started:
                break
            time.sleep(0.01)
        assert process_started, "The child process did not start."

        cancel_event.set()
        runner.join(timeout=5)
        assert not runner.is_alive(), "Cancellation waited for output from a silent process."
        assert result["return_code"] != 0
        with ocr_training._JOB_LOCK:
            assert job_id not in ocr_training._PROCESSES
    finally:
        with ocr_training._JOB_LOCK:
            process = ocr_training._PROCESSES.get(job_id)
        if process is not None and process.poll() is None:
            process.kill()
        runner.join(timeout=5)
        with ocr_training._JOB_LOCK:
            ocr_training._PROCESSES.pop(job_id, None)
            ocr_training._JOBS.pop(job_id, None)



@pytest.mark.parametrize(
    "split_payload",
    ["[]", '{"assignments": []}', '{"assignments": null}'],
)
def test_start_training_rejects_malformed_split_metadata(
    tmp_path: Path, split_payload: str
) -> None:
    from planline.ocr_training import MODEL_CONFIGS, start_training_job

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "splits.json").write_text(split_payload, encoding="utf-8")

    source = tmp_path / "PaddleOCR"
    (source / "tools").mkdir(parents=True)
    (source / "tools" / "train.py").write_text("# training entrypoint", encoding="utf-8")
    config = source / MODEL_CONFIGS["mobile"]
    config.parent.mkdir(parents=True)
    config.write_text("Global: {}", encoding="utf-8")
    checkpoint = tmp_path / "mobile.pdparams"
    checkpoint.write_bytes(b"checkpoint")

    with pytest.raises(ValueError, match="split plan|Split plan"):
        start_training_job(dataset, source, checkpoint)


def test_exported_inference_model_requires_nonempty_parameter_file(tmp_path: Path) -> None:
    from planline.ocr_training import _has_exported_inference_weights

    inference_dir = tmp_path / "inference"
    assert not _has_exported_inference_weights(inference_dir)

    inference_dir.mkdir()
    weights = inference_dir / "inference.pdiparams"
    weights.write_bytes(b"")
    assert not _has_exported_inference_weights(inference_dir)

    weights.write_bytes(b"model-weights")
    assert _has_exported_inference_weights(inference_dir)

def test_persisted_running_job_is_restored_as_interrupted_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import threading

    from planline import ocr_training

    data_root = tmp_path / "user-data"
    monkeypatch.setenv("PLANLINE_DATA_DIR", str(data_root))
    job_id = "0123456789ab"
    state_dir = data_root / "ocr" / "handwriting" / "training_runs" / job_id
    state_dir.mkdir(parents=True)
    state_path = state_dir / "job.json"
    job = {
        "job_id": job_id,
        "kind": "training",
        "status": "running",
        "created_at": "2026-11-27T00:00:00+00:00",
        "current_step": "fine-tuning",
        "output_dir": str(state_dir),
        "_state_path": str(state_path),
        "_log_lines": ["training started", "epoch 1/10"],
        "cancel_event": threading.Event(),
    }

    with ocr_training._JOB_LOCK:
        ocr_training._JOBS[job_id] = job
        ocr_training._persist_job_locked(job)
        ocr_training._JOBS.pop(job_id)

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "running"
    assert persisted["logs"].splitlines() == ["training started", "epoch 1/10"]

    restored = ocr_training.get_job(job_id)
    assert restored is not None
    assert restored["status"] == "interrupted"
    assert restored["current_step"] == "interrupted"
    assert "application restarted" in restored["error"]
    assert restored["logs"].splitlines() == ["training started", "epoch 1/10"]
    assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "interrupted"

from __future__ import annotations

from pathlib import Path


def test_windows_installer_provisions_a_verified_paddleocr_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = (root / "packaging" / "windows" / "Program.cs").read_text(encoding="utf-8")
    requirements = (root / "requirements-ocr-paddle.txt").read_text(encoding="utf-8")

    assert 'private const string PaddleVersion = "3.3.0";' in installer
    assert "PaddleGpuIndex" in installer
    assert "PaddleCpuIndex" in installer
    assert '"--extra-index-url", PaddleGpuIndex' in installer
    assert '"--extra-index-url", PaddleCpuIndex' in installer
    assert "InstallPaddleOcrAsync(" in installer
    assert "requestGpu: useGpu && !cpuFallback" in installer
    assert "capability > 75" in installer
    assert "paddlepaddle-gpu=={PaddleVersion}" in installer
    assert "paddlepaddle=={PaddleVersion}" in installer
    assert "paddle.utils.run_check()" in installer
    assert "PADDLE_OCR_READY=" in installer
    assert "paddleocr==3.3.1" in requirements


def test_installer_reports_the_separate_ocr_accelerator() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = (root / "packaging" / "windows" / "Program.cs").read_text(encoding="utf-8")

    assert "ocr_accelerator = ocrAccelerator" in installer
    assert "PaddleOCR runtime: {ocrAccelerator}" in installer

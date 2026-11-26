# Windows installer

The Windows installer is a native, single-file WinForms application. Setup displays live byte counts and percentages for direct downloads, plus a per-asset activity list; package installation progress is surfaced separately from download progress. The person installing Planline downloads and opens **Planline-Setup.exe**; no terminal, system Python installation, or package commands are required.

## What the installer does

1. Offers an installation folder and detects a supported NVIDIA driver.
2. Downloads the official Python 3.13.17 x64 installer and verifies its SHA-256 before use.
3. Installs Python privately under the selected Planline directory. It does not modify PATH or replace another Python installation.
4. Installs Microsoft Edge WebView2 if it is not already present.
5. Extracts the exact Planline source snapshot embedded in the setup executable.
6. Installs PyTorch 2.10.0 with CUDA 12.6 when selected, verifies that CUDA can actually initialise, and falls back to the CPU build if the GPU runtime is unavailable.
7. Installs the application requirements, including the shared Markdown page renderer.
8. Installs PaddlePaddle and the pinned PaddleOCR 3.3.1 recognition runtime. The installer selects a compatible CPU/GPU runtime and verifies PaddleOCR initialisation.
9. Performs an import/runtime smoke test, then creates Start-menu and optional desktop shortcuts plus a per-user Windows uninstall entry.

The installer does not request administrator privileges. NVIDIA drivers are supplied by the computer manufacturer / NVIDIA and are not silently changed by Planline.

## User data

Installed builds set PLANLINE_DATA_DIR to:

"%LOCALAPPDATA%\Planline"

OCR datasets are stored below:

"%LOCALAPPDATA%\Planline\ocr"

This keeps crop images, labels, split files and training outputs outside the application installation directory. Updating or removing the app does not delete them by default. The uninstaller offers a separate explicit choice to delete them.

Source/development runs without PLANLINE_DATA_DIR continue using the repository's ignored datasets/ocr directory.

## OCR training assets and evaluation

The installer includes the PaddlePaddle runtime and pinned PaddleOCR 3.3.1 recognition package used by the optional local OCR feature. The Drawing workspace can use this recogniser for suggestions; every prediction remains unverified until a person checks it against the source crop.

Training assets are larger and are **not bundled in the installer**. When requested from OCR Studio, Planline downloads the matching PaddleOCR v3.3.1 source checkout and official PP-OCRv5 mobile/server pretrained checkpoint into the local OCR data directory. Training jobs can also prepare these assets automatically when no explicit paths are supplied.

Training orchestration and asset provisioning are implemented, but a successful training run is not guaranteed by installation. It still depends on a compatible local PaddlePaddle environment, a rights-cleared and representative dataset, and a properly grouped held-out evaluation set. Do not present the installer smoke test as evidence that a Planline-specific recogniser has been trained or validated.

## Build and distribution

The GitHub Actions workflow at .github/workflows/windows-installer.yml builds the installer for win-x64 whenever this branch is updated, on pull requests targeting main, and on manual workflow dispatch. It uploads a Planline-Setup-windows-x64 artifact.

Pushing a version tag such as planline-v0.1.0 runs the same build and attaches Planline-Setup.exe to a GitHub Release. No release is created by ordinary branch pushes.

Build prerequisites for maintainers: Windows runner, .NET 10 SDK and the tracked project source. The workflow creates a ZIP source snapshot and embeds it into a self-contained .NET installer; end users do not need .NET installed.

### Distribution limitations

The first installer is not code-signed. Windows SmartScreen may show an unknown-publisher warning until the application has a trusted code-signing certificate and sufficient reputation. Do not advise users to bypass security warnings blindly. The setup downloads Python from python.org and WebView2 from Microsoft's official distribution endpoint over HTTPS.

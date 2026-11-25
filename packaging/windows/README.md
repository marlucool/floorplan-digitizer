# Windows installer

The Windows installer is a native, single-file WinForms application. Setup displays live byte counts and percentages for direct downloads, plus a per-asset activity list; package installation progress is surfaced separately from download progress. The person installing Planline downloads and opens **Planline-Setup.exe**; no terminal, system Python installation, or package commands are required.

## What the installer does

1. Offers an installation folder and detects a supported NVIDIA driver.
2. Downloads the official Python 3.14.10 x64 installer and verifies its SHA-256 before use.
3. Installs Python privately under the selected Planline directory. It does not modify PATH or replace another Python installation.
4. Installs Microsoft Edge WebView2 if it is not already present.
5. Extracts the exact Planline source snapshot embedded in the setup executable.
6. Installs PyTorch 2.10.0 with CUDA 12.6 when selected, verifies that CUDA can actually initialise, and falls back to the CPU build if the GPU runtime is unavailable.
7. Installs the remaining app requirements and performs an import smoke test.
8. Creates Start-menu and optional desktop shortcuts, plus a per-user Windows uninstall entry.

The installer does not request administrator privileges. NVIDIA drivers are supplied by the computer manufacturer / NVIDIA and are not silently changed by Planline.

## User data

Installed builds set PLANLINE_DATA_DIR to:

"%LOCALAPPDATA%\Planline"

OCR datasets are stored below:

"%LOCALAPPDATA%\Planline\ocr"

This keeps crop images, labels, split files and training outputs outside the application installation directory. Updating or removing the app does not delete them by default. The uninstaller offers a separate explicit choice to delete them.

Source/development runs without PLANLINE_DATA_DIR continue using the repository's ignored datasets/ocr directory.

## OCR training runtime status

The first Windows installer installs the desktop app, drawing detector, and the normal application dependencies. It does **not** currently install the optional PaddlePaddle/PaddleOCR training stack. PaddlePaddle's supported Windows Python range does not yet include the Python 3.14 runtime used by this base installer. Training needs a separately managed compatible environment, PaddleOCR source checkout and matching pretrained checkpoint. The next installer phase should provision and validate that environment through an in-app setup screen, without requiring terminal commands.

Do not present the current installer as proof that fine-tuning has been run successfully. The training orchestration exists, but the actual GPU training and export still need a real environment test.

## Build and distribution

The GitHub Actions workflow at .github/workflows/windows-installer.yml builds the installer for win-x64 whenever this branch is updated, on pull requests targeting main, and on manual workflow dispatch. It uploads a Planline-Setup-windows-x64 artifact.

Pushing a version tag such as planline-v0.1.0 runs the same build and attaches Planline-Setup.exe to a GitHub Release. No release is created by ordinary branch pushes.

Build prerequisites for maintainers: Windows runner, .NET 10 SDK and the tracked project source. The workflow creates a ZIP source snapshot and embeds it into a self-contained .NET installer; end users do not need .NET installed.

### Distribution limitations

The first installer is not code-signed. Windows SmartScreen may show an unknown-publisher warning until the application has a trusted code-signing certificate and sufficient reputation. Do not advise users to bypass security warnings blindly. The setup downloads Python from python.org and WebView2 from Microsoft's official distribution endpoint over HTTPS.

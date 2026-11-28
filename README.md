# Planline — Scanned Floor Plan Digitisation

Planline is a local-first project for turning scanned or hand-drawn 2D floor plans into **editable, dimensionally constrained CAD geometry**.

> **Desktop UI preview:** [Open the current Planline workspace](https://marlucool.github.io/floorplan-digitizer/). This multi-page static preview includes the dashboard, drawing workspace, OCR Studio, settings and the documentation library. It uses illustrative sample data; OCR, model inference, uploads and backend operations are disabled. The repository owner must enable **Settings → Pages → Build and deployment → GitHub Actions** once before the site can publish.
>
> **Pull request previews:** the `preview` label publishes that PR's version of the multi-page Planline workspace at `https://marlucool.github.io/floorplan-digitizer/pr-preview/<PR-number>/`. The link is posted in the PR conversation and refreshes whenever new commits are pushed. Removing the label or closing the PR removes its preview. The main website and all currently labelled PR previews are rebuilt together on every push to `main`.

> **Documentation:** [Browse the full documentation library](https://marlucool.github.io/floorplan-digitizer/documentation/), including architecture notes, OCR dataset guidance, examples and archived source references. The same library is available locally from the Dashboard and workspace navigation.

The important problem is not tracing pixels. Survey drawings can be skewed, faded, low-resolution, or drawn approximately rather than to scale. Planline is being developed to read written dimensions, relate them to the correct parts of the drawing, detect contradictions, and keep uncertain results in a human review workflow.

> **Current status: drawing review plus OCR Studio workbench.** The local app now includes a crop editor, verified-label library, source/writer-safe dataset splits, background PP-OCRv5 fine-tuning jobs and held-out benchmark reporting. The desktop app opens the workspace dashboard first. Drawing, OCR Studio and application settings are available from the global navigation at `/`, `/ocr` and `/settings`. The dashboard is served locally at `/dashboard`; the static preview exposes it as `dashboard.html`. The drawing-analysis workflow ranks geometric candidates linking dimension-value regions to dimension lines and wall spans, with explicit human confirmation. The Windows installer provisions PaddlePaddle and PaddleOCR in Planline's private Python runtime; local recognition remains optional and every suggestion remains unverified until reviewed. A confirmed dimension-to-wall association can derive a candidate pixel scale; manual two-point calibration remains available as a fallback. Manual wall/room geometry can be exported to SVG and DXF. A first dimension-driven draft step now converts axis-aligned detected wall regions into editable wall-face edges after the reviewer confirms at least one horizontal and one vertical dimension-to-wall match. It derives independent X/Y scales, exports generated edges on a separate DXF layer, and reports near-coincident wall-face endpoints as review-only junction candidates. The reviewer can join an individual endpoint pair or undo that join; no connections are applied automatically. Full wall topology, room reconstruction, openings, diagonal walls, scan dewarping and certified measured CAD output are still not implemented.

![Example survey drawing](docs/rysunek.png)

## What works today

| Area | Current capability |
| --- | --- |
| Web app | Browser UI served by the local FastAPI application, with a workspace dashboard at `/dashboard` |
| Input | PNG, JPG, WEBP, TIFF and PDF uploads up to 25 MB |
| PDF handling | Select and analyse any page in a multi-page PDF without re-uploading the source |
| Scale calibration | Manual two-point reference in mm, cm, m, inches or feet; the draft builder can also derive separate X/Y scales from multiple explicitly confirmed dimensions; neither is a geometry certification |
| Projects | Save/open portable `.planline` files with the source drawing, analysis, manual review, generated wall-edge draft and its X/Y scale provenance; saving is explicit and local |
| Room boundaries | Draw and edit closed room polygons; calculate area in px² or calibrated m² using a user-supplied reference |
| OCR assist | Automatically run local PaddleOCR on detected dimension crops when the runtime is available; choose base or fine-tuned models and review every suggestion |
| Geometry authoring and draft | Draw/edit walls and rooms manually; after confirming horizontal and vertical dimension text and wall matches, generate two editable face edges per axis-aligned wall detection. Draft edges retain detection provenance and export on a separate `DETECTED_WALL_DRAFT` DXF layer; near-coincident endpoints are reported as review-only junction candidates, individually joinable only after explicit review |
| Image preparation | Bounded brightness/contrast adjustments before detection and crop generation; source coordinates remain unchanged |
| Detection | Bundled YOLO model proposes wall, dimension_line and dimension_value regions |
| Review | Detection overlays, zoom, confidence-threshold control, class filtering, selected-box highlighting and dimension-region crops |
| Manual transcription | Reviewer-entered text can be linked to detection IDs and marked as printed, handwritten or unclear; individually verified dimension crops can be saved directly into an OCR dataset without uploading the full drawing |
| Review export | Versioned planline-detection-review/v1 JSON export with source dimensions, bounding boxes, detector scores and limitations |
| Dimension association | Uses local parallel-wall gaps, text/line alignment, wall-face spans and global one-to-one text-to-wall-gap recommendations (dimension-line detections can be shared by chained labels); the reviewer confirms each relationship |
| Dimension chain | Dimension-chain checker validates explicit values and can propose the remainder for exactly one missing segment when all other inputs are verified; the proposed value remains unverified until the user confirms it |
| Optional OCR | Standalone PaddleOCR recognition runner for saved dimension crops; raw results remain unverified |
| OCR evaluation | Compare predictions against verified review labels or curated crop datasets using exact-match rate, coverage and character error rate |
| Crop dataset curation | Bulk-import verified crops from Drawing reviews, import CSV + image ZIP archives, export verified datasets and create source/writer-safe splits |
| OCR dataset quality | Read-only audit of label quality, character coverage, duplicate crops, source/writer counts and split leakage |
| OCR Studio | Crop editor, verified label library, dataset management, split creation and training-job monitor |
| Fine-tuning | Local PaddleOCR PP-OCRv5 mobile/server training from a matching `.pdparams` checkpoint |
| Benchmarking | Base and fine-tuned recogniser evaluation on the held-out test split only |

### Audit an OCR dataset before training

Run a read-only quality report after collecting and splitting crops:

```bash
python -m planline.ocr_quality --dataset datasets/ocr/handwriting --output datasets/ocr/handwriting/quality-report.json
```

The report flags duplicate images, conflicting labels, suspicious transcription formatting, weak source/writer coverage and split problems. It also reports character frequencies so the recogniser's supported character set can be checked. See [the OCR dataset quality guide](docs/OCR_DATASET_QUALITY.md). A clean report is only a data-hygiene check; it does not prove the dataset is large or representative enough to train a reliable model.

### Start collecting handwritten dimension samples

Open OCR Studio from Planline's desktop window to create a dataset, add one or more scans, draw around each complete dimension string, enter the exact reading, and verify it before saving. In installed Windows builds, crops and dataset files are stored locally under %LOCALAPPDATA%/Planline/ocr; the full source scan remains in the browser and is not sent to the OCR dataset endpoint. Source/development runs use the ignored datasets/ocr/ directory.

For new drawings, crop the **whole dimension string** as one image (for example, “4,200 mm”), not individual digits. Transcribe exactly what is visible, preserve decimals and units, and only mark a label verified after checking it against the drawing. Keep crops from one plan under the same source ID. Use the same pseudonymous writer ID for samples written by the same person.

The dataset is local and excluded from Git. OCR Studio supports bulk import from a review JSON plus its source raster, CSV + crop ZIP import, and verified dataset ZIP export. Detailed commands and the CSV format are in [the crop-data guide](web/README.md#handwritten-dimension-crop-dataset).

A detector score is **not** OCR confidence or a probability that a measurement is correct. A bounding box is a candidate region, not a wall centreline or a measurement. Pixel distances are not millimetres.

## Install Planline on Windows

**You should not need to open Command Prompt or PowerShell to install or launch Planline.** The Windows build is distributed as one interactive Planline-Setup.exe installer.

1. Open the repository's [Releases page](https://github.com/marlucool/floorplan-digitizer/releases). Download Planline-Setup.exe from the latest Planline release.
2. Double-click the installer. Choose the installation folder and NVIDIA GPU or CPU mode, then select **Install Planline**.
3. The installer downloads a private Python runtime, installs the application and PaddleOCR dependencies, selects a compatible Paddle CPU/GPU wheel, installs WebView2 when needed, checks the runtimes, and creates the Start-menu and optional desktop shortcuts.
4. Open **Planline** from the shortcut. The app launches its local service automatically and opens the desktop workspace.

No system Python, package installation commands, PATH edits, or administrator account are required. The Settings → Updates page checks the latest stable GitHub Release and can verify, download and install its Windows installer. Updates keep the private Python, PyTorch and PaddleOCR runtimes in place. The installer does not silently install or replace NVIDIA display drivers. If CUDA cannot initialise, it installs the CPU runtime instead.

The installer is built automatically by the Windows installer workflow. Until the first tagged release is published, its test build is available from the repository's **Actions → Windows installer → Planline-Setup-windows-x64** artifact.

Your OCR crops and labels are kept outside the application folder at %LOCALAPPDATA%/Planline/ocr. Normal updates and uninstalling Planline keep this data; the uninstaller asks separately before deleting it.

**OCR training note:** the Windows installer provisions PaddlePaddle and PaddleOCR automatically. OCR Studio can also download the pinned PaddleOCR v3.3.1 source checkout and the matching official mobile/server pretrained checkpoint; you no longer need to locate those files manually.

## Run from source (development only)

The following commands are for contributors running an editable checkout. They are not required for normal Windows installation.

Use Python 3.11 or newer from the repository root:

~~~bash
python -m pip install -r requirements-web.txt
python -m uvicorn planline.api:app --host 127.0.0.1 --port 8000
~~~

Open http://127.0.0.1:8000 for drawing review and /ocr for OCR Studio.

For a native desktop window from source on Windows, install the development requirements and run run_planline_desktop.bat. On macOS/Linux, install the requirements and run sh run_planline_desktop.sh. The source launcher starts the API on a loopback-only random port.

The API binds to loopback by default. Do not expose the development server directly to the public internet. If remote access is ever required, put an authenticated, encrypted access layer in front of it and configure the deployment deliberately.

See [the web guide](web/README.md) for the current workflow, API routes, upload lifecycle, optional OCR runner, benchmark evaluation and development checks.

### Upload and privacy boundary

Planline does not intentionally save uploaded drawings as project files. However, FastAPI/Starlette parse multipart uploads using spooled temporary files; larger uploads may roll over to temporary disk storage before the endpoint reads and closes them. The 25 MB application check occurs after multipart parsing, so it is not a pre-parser disk-spooling limit. Browser caches, server logs, reverse-proxy buffering and temporary directories also matter. The current API should therefore **not** be described as guaranteeing memory-only handling. Review the detailed precautions in [the web guide](web/README.md) before processing sensitive drawings.

## What is not implemented yet

- Automatic, unattended OCR of the entire drawing. The Drawing workspace now runs PaddleOCR on detected dimension crops (up to 30 per analysis) when the local runtime is available; every suggestion remains unverified until a person checks it.
- Fully automatic, verified dimension association. Current box-based candidates require human confirmation and do not handle arbitrary rotated/diagonal geometry. The global assignment is a recommendation, not a verified measurement.
- Multi-dimension scale reconciliation and robust scale inference. One verified dimension plus a reviewer-confirmed wall-span association can derive a candidate scale; manual two-point calibration remains an explicitly user-supplied fallback.
- Automatic dimension-chain solving across a floor plan. The manual checker can calculate one missing segment from verified known values and a verified overall dimension, but the candidate still requires explicit confirmation.
- Full wall/opening/room topology reconstruction from detector and OCR results. The first draft stage creates two wall-face edges per axis-aligned wall detection using confirmed X/Y scales, but does not join corners, infer openings, create room polygons or resolve diagonals.
- Certified measured CAD export. Draft wall edges can be exported to DXF/SVG with scale provenance and a separate `DETECTED_WALL_DRAFT` layer, but the output is still explicitly unverified and requires human inspection; native DWG output is not implemented.

The manual dimension-chain endpoint checks arithmetic and can propose the remainder for exactly one missing segment when the overall dimension and all known segments are verified. The proposal is never marked verified automatically. The separate wall-draft builder rechecks the selected dimension-to-wall candidate geometry and only uses explicitly confirmed linear dimensions with units; its output remains draft linework, not a complete measured floorplan. The optional PaddleOCR tool produces raw candidate text; its output is never automatically accepted.

## Where the project is heading

The target is a reviewable 2D digitisation pipeline:

1. **Prepare the source.** Preserve the original scan, identify page bounds and orientation, inspect resolution, deskew and normalise contrast, and rasterise PDF pages.
2. **Detect drawing features.** Locate walls, openings, dimension strings/lines and relevant annotation regions. Use overlapping high-resolution tiles when small handwriting is lost at full-page scale.
3. **Read dimension numerals.** Prioritise printed and handwritten numbers before broad English OCR. Keep the source crop, raw candidates, model provenance, confidence and alternatives.
4. **Associate readings with geometry.** Determine which dimension line and wall span each number describes. Do not silently choose a nearby wall when more than one association is plausible.
5. **Solve dimensional constraints.** Compare segment chains with overall dimensions, identify missing values and contradictions, and keep under-constrained geometry unresolved. For non-scale drawings, written dimensions are the metric authority; pixel proportions are evidence about shape and adjacency only.
6. **Reconstruct editable 2D geometry.** Build walls and openings from verified constraints, validate connectivity and topology, and expose unresolved gaps or conflicts for manual correction.
7. **Gate CAD export.** Generate DXF/SVG only from verified geometry, with explicit units and layers. A drawing that merely looks plausible is not ready for export.

The OCR direction is deliberately numeric-first. General English room-label and note recognition is not an initial dependency unless evaluation shows it materially improves the dimension workflow. The optional PaddleOCR recogniser is a baseline to measure, not a claim that OCR is solved. Dimension association now builds local gaps between parallel wall boxes, checks the dimension text and line against those gaps, and uses a global one-to-one assignment for wall gaps while allowing several labels to share one detected dimension line in a chained dimension. It can retain non-adjacent wall pairs as overall-span alternatives. Every proposed link remains unconfirmed until the reviewer checks it.

Dataset capture, validation, grouped splits, a local fine-tuning interface and held-out benchmark orchestration are implemented. Actual training still requires a compatible local PaddlePaddle installation, a PaddleOCR source checkout and the matching pretrained checkpoint; no model has been trained on the user's own plan crops yet. OCR Studio does not claim a recogniser is reliable until it has been evaluated on representative, independent held-out drawings. Evaluation must be split by original drawing and writer, not by individual crops.

The existing RTX 2080 Ti (11 GB VRAM) is the initial local development target. Compact models, tiled inference, conservative batch sizes and staged processing are preferred over a large end-to-end model. Model selection should follow representative-plan evaluation.

**Scope:** 2D floor-plan digitisation and CAD output. 3D building reconstruction is not a current goal.

## Existing command-line experiment

The repository retains an earlier Python pipeline separate from the Planline web app:

- main.py — fixed-input detection, handwritten-digit OCR and DXF pipeline
- train_yolo.py and trainer.py — detector and digit-model training scripts
- detection.py, ocr.py, model.py, dxf_export.py — legacy pipeline modules
- yolo_floorplan.pt and digit_ocr_resnet18.pth — tracked experimental weights

That pipeline can produce a DXF from its test input, but its heuristic dimension matching and geometry are not validated for arbitrary scanned or non-scale plans. It is not called by the web API and should be treated as a research baseline, not the production reconstruction engine. The Windows installer intentionally excludes these retired scripts and the digit-only checkpoint from its source archive; they remain available in Git for research.

To run the separate experiment, install the root ML dependencies and use the repository's test.jpg input:

```bash
python -m pip install -r requirements.txt
python main.py
```

## Development checks

Install the lightweight test dependencies:

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=. python -m pytest -q tests/test_*.py
python -m planline.dataset --help
node --check web/app.js
node --check web/ocr-studio.js
```

Optional browser smoke test (requires Playwright and a local Chromium installation):

```bash
python -m pip install -r requirements-e2e.txt
python -m playwright install chromium
python -m pytest -q tests/e2e
```

The regular CI suite uses a fake detector, so passing it verifies API behaviour and serialization rather than real-model accuracy. A separate opt-in real-weight smoke test is documented in [the web guide](web/README.md).

## Repository layout

```text
floorplan-digitizer/
├── planline/                     # Local API, constraints, OCR and dataset curation utilities
├── web/                          # Active browser UI and usage guide
├── schemas/                      # Versioned detection-review JSON schema
├── tests/                        # API, constraints, OCR, dataset and browser tests
├── docs/
│   ├── ARCHITECTURE.md            # Current architecture and roadmap summary
│   ├── PLANLINE_ARCHITECTURE.md   # Detailed design/research notes and backlog
│   └── archive/                   # Earlier sample UI prototype for reference
├── .github/workflows/             # Planline test workflow
├── main.py                        # Separate legacy CLI pipeline
└── requirements*.txt              # App, development and optional OCR dependencies
```

## Development principles

- Keep source drawings local by default and document the upload/temporary-file lifecycle honestly.
- Treat detections and OCR strings as candidates until reviewed.
- Keep printed OCR, handwritten OCR and geometric evidence distinguishable.
- Do not use general text OCR unless it adds measurable value to dimension reading.
- Never invent missing measurements or silently force geometry to close.
- Keep the legacy CLI pipeline, current detection/review app and future reconstruction engine clearly separated.

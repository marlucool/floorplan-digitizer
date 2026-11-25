# Planline — Scanned Floor Plan Digitisation

Planline is a local-first project for turning scanned or hand-drawn 2D floor plans into **editable, dimensionally constrained CAD geometry**.

The important problem is not tracing pixels. Survey drawings can be skewed, faded, low-resolution, or drawn approximately rather than to scale. Planline is being developed to read written dimensions, relate them to the correct parts of the drawing, detect contradictions, and keep uncertain results in a human review workflow.

> **Current status: detection and review prototype.** The browser app and local FastAPI API are working. The app can preview raster/PDF input, run the bundled YOLO detector, display candidate regions and bounded dimension crops, export a versioned review JSON file, and validate a manually entered dimension chain. OCR is not yet part of the browser workflow; an optional standalone PaddleOCR runner can recognise saved crops. Automatic dimension-to-wall association, metric reconstruction, and verified DXF export are not implemented.

![Example survey drawing](docs/rysunek.png)

## What works today

| Area | Current capability |
| --- | --- |
| Web app | Browser UI served by the local FastAPI application |
| Input | PNG, JPG, WEBP, TIFF and PDF uploads up to 25 MB |
| PDF handling | First page rasterisation; multi-page selection is not implemented |
| Detection | Bundled YOLO model proposes wall, dimension_line and dimension_value regions |
| Review | Detection overlays, zoom, confidence-threshold control, class filtering, selected-box highlighting and dimension-region crops |
| Manual transcription | Reviewer-entered text can be linked to detection IDs and marked as printed, handwritten or unclear |
| Review export | Versioned planline-detection-review/v1 JSON export with source dimensions, bounding boxes, detector scores and limitations |
| Dimension chain | Separate API endpoint checks explicitly supplied values, verification flags, units and tolerance using decimal arithmetic |
| Optional OCR | Standalone PaddleOCR recognition runner for saved dimension crops; raw results remain unverified |
| OCR evaluation | Tool to compare predictions against manually verified transcriptions using exact-match rate, prediction coverage and character error rate |
| Crop dataset curation | Export verified full-string crops or import manual crops; validate manifests and create source/writer-safe splits |

### Start collecting handwritten dimension samples

The repository now includes a local dataset curation tool. It does not train a model yet; it turns your reviewed crops into a traceable OCR dataset so we can benchmark recognisers and decide what to fine-tune.

For new drawings, crop the **whole dimension string** as one image (for example, “4,200 mm”), not individual digits. Transcribe exactly what is visible, preserve decimals and units, and only mark a label verified after checking it against the drawing. Keep crops from one plan under the same source ID. Use the same pseudonymous writer ID for samples written by the same person.

The dataset is local and excluded from Git. Detailed commands and the CSV format are in [the crop-data guide](web/README.md#handwritten-dimension-crop-dataset).

A detector score is **not** OCR confidence or a probability that a measurement is correct. A bounding box is a candidate region, not a wall centreline or a measurement. Pixel distances are not millimetres.

## Run Planline locally

Use Python 3.11 or newer. Run these commands from the repository root:

```bash
python -m pip install -r requirements-web.txt
python -m uvicorn planline.api:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000.

The API binds to loopback by default. Do not expose the development server directly to the public internet. If remote access is ever required, put an authenticated, encrypted access layer in front of it and configure the deployment deliberately.

See [the web guide](web/README.md) for the current workflow, API routes, upload lifecycle, optional OCR runner, benchmark evaluation and development checks.

### Upload and privacy boundary

Planline does not intentionally save uploaded drawings as project files. However, FastAPI/Starlette parse multipart uploads using spooled temporary files; larger uploads may roll over to temporary disk storage before the endpoint reads and closes them. The 25 MB application check occurs after multipart parsing, so it is not a pre-parser disk-spooling limit. Browser caches, server logs, reverse-proxy buffering and temporary directories also matter. The current API should therefore **not** be described as guaranteeing memory-only handling. Review the detailed precautions in [the web guide](web/README.md) before processing sensitive drawings.

## What is not implemented yet

- OCR integrated into the browser analysis workflow.
- Automatic association between a recognised number, its dimension line and the measured wall/span.
- Reliable unit interpretation or scale calibration from written dimensions.
- Automatic dimension-chain solving across a floor plan.
- Editable wall/opening reconstruction with topology and geometry validation.
- DXF/SVG export generated from verified uploaded-plan geometry.

The manual dimension-chain endpoint checks arithmetic only. It does not read values, infer missing dimensions, convert units, associate dimensions with walls, or enable CAD export. The optional PaddleOCR tool produces raw candidate text for evaluation; its output is not automatically accepted.

## Where the project is heading

The target is a reviewable 2D digitisation pipeline:

1. **Prepare the source.** Preserve the original scan, identify page bounds and orientation, inspect resolution, deskew and normalise contrast, and rasterise PDF pages.
2. **Detect drawing features.** Locate walls, openings, dimension strings/lines and relevant annotation regions. Use overlapping high-resolution tiles when small handwriting is lost at full-page scale.
3. **Read dimension numerals.** Prioritise printed and handwritten numbers before broad English OCR. Keep the source crop, raw candidates, model provenance, confidence and alternatives.
4. **Associate readings with geometry.** Determine which dimension line and wall span each number describes. Do not silently choose a nearby wall when more than one association is plausible.
5. **Solve dimensional constraints.** Compare segment chains with overall dimensions, identify missing values and contradictions, and keep under-constrained geometry unresolved. For non-scale drawings, written dimensions are the metric authority; pixel proportions are evidence about shape and adjacency only.
6. **Reconstruct editable 2D geometry.** Build walls and openings from verified constraints, validate connectivity and topology, and expose unresolved gaps or conflicts for manual correction.
7. **Gate CAD export.** Generate DXF/SVG only from verified geometry, with explicit units and layers. A drawing that merely looks plausible is not ready for export.

The OCR direction is deliberately numeric-first. General English room-label and note recognition is not an initial dependency unless evaluation shows it materially improves the dimension workflow. The optional PaddleOCR recogniser is a baseline to measure, not a claim that OCR is solved.

The first dataset-capture and validation utilities are now implemented. Full model training and a browser-integrated OCR stage remain future work. Evaluation must be split by original drawing and writer, not by individual crops. Measure exact full-dimension accuracy, prediction coverage, dimension association, chain consistency, topology/export correctness and human correction time.

The existing RTX 2080 Ti (11 GB VRAM) is the initial local development target. Compact models, tiled inference, conservative batch sizes and staged processing are preferred over a large end-to-end model. Model selection should follow representative-plan evaluation.

**Scope:** 2D floor-plan digitisation and CAD output. 3D building reconstruction is not a current goal.

## Existing command-line experiment

The repository retains an earlier Python pipeline separate from the Planline web app:

- main.py — fixed-input detection, handwritten-digit OCR and DXF pipeline
- train_yolo.py and trainer.py — detector and digit-model training scripts
- detection.py, ocr.py, model.py, dxf_export.py — legacy pipeline modules
- yolo_floorplan.pt and digit_ocr_resnet18.pth — tracked experimental weights

That pipeline can produce a DXF from its test input, but its heuristic dimension matching and geometry are not validated for arbitrary scanned or non-scale plans. It is not called by the web API and should be treated as a research baseline, not the production reconstruction engine.

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

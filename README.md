# Planline — Scanned Floor Plans to Editable 2D CAD

Planline is a local-first project exploring how to turn scanned or hand-drawn 2D floor plans into **editable, dimensionally constrained CAD geometry**.

The target is not a simple image-to-vector trace. Real survey plans can be skewed, faded, scanned at unknown scale, or drawn approximately rather than perfectly to scale. Planline is intended to read the written dimensions, relate them to the drawing, detect contradictions, and keep uncertain results in a human review queue.

> **Current status: early prototype.** The web workspace and local file API are in place. Uploaded files can be previewed and stored locally, and the API can run basic source preflight. The OCR, feature-detection, dimension-association and reconstruction adapters are not connected yet. The only currently exportable DXF in the web UI is illustrative sample geometry.

## What works today

| Area | Current capability |
| --- | --- |
| Web workspace | Three-step local UI: add drawing, review dimensions, preview/export |
| Source preview | PNG, JPG, WEBP and browser-supported TIFF previews; PDF files can be selected and stored, but PDF pages are not rendered in the current UI |
| Local API | Stores uploads and project metadata under `runtime/projects/` on this computer |
| Source preflight | SHA-256 file fingerprint, available image dimensions and basic quality findings |
| Review workflow | Editable sample dimensions, verification controls and a live example dimension-chain check |
| DXF | Download of the illustrative sample plan only; it is not generated from an uploaded drawing |

The sample readings and confidence percentages are demonstration data. They are not model predictions. When an uploaded drawing is selected, the sample review rows and sample export are disabled so they cannot be mistaken for results from that drawing.

## Run the web app

Run these commands from the repository root. The web app uses the smaller backend requirements file; installing the root `requirements.txt` also installs the heavier experimental ML stack.

```bash
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install and start the local service:

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Uploaded source files and project metadata are written to `runtime/projects/` on the same machine. That directory is ignored by Git. The service does not send files to a remote OCR provider.

For frontend-only exploration, open `web/index.html` directly. Direct-file mode supports the sample interaction and browser preview, but it cannot store server-side projects or run API preflight.

See [backend/README.md](backend/README.md) for API routes and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the system design and development phases.

## Where the project is heading

The intended workflow is:

1. **Import and prepare the scan.** Preserve the source, identify page bounds and orientation, inspect resolution, deskew and normalise contrast, and rasterise PDF pages before recognition.
2. **Find drawing features and dimension regions.** Detect walls, openings, dimension strings/lines and relevant symbols. Use high-resolution crops or tiles where small handwritten dimensions would otherwise be lost.
3. **Read dimension numerals.** Prioritise printed and handwritten numbers rather than running broad English OCR over every room label and note. Keep candidate readings, source crops, confidence and model provenance.
4. **Resolve dimensions as constraints.** Associate each number with the correct wall or dimension segment. Compare chained dimensions with overall dimensions, identify missing values and surface contradictions. Written dimensions should govern non-scale sketches; image pixels must not be mistaken for millimetres.
5. **Reconstruct editable 2D geometry.** Build walls and openings from verified constraints, check connectivity and topology, and show unresolved gaps or conflicts for correction.
6. **Export only verified geometry.** Produce DXF/SVG from the reviewed vector model, with units and layers preserved. A plausible-looking drawing is not enough if its dimensions or topology are unsupported.

A separate training/evaluation workspace is planned for dataset manifests, annotation QA, model comparison and regression testing. It should use plans that are licensed or explicitly permitted, keep train/validation/test splits separate by source drawing, and measure exact dimension accuracy, association accuracy, chain consistency, geometry correctness and time spent correcting results.

The local development target is the existing RTX 2080 Ti (11 GB VRAM), so compact models, tiled inference, conservative batches and staged processing are preferred over a large end-to-end model. Model choice will follow evaluation on representative plans, not assumptions based on benchmark scores alone.

**Scope:** 2D floor-plan digitisation and CAD output. 3D building reconstruction is not a current goal.

## Existing experimental pipeline

The repository also contains an earlier command-line experiment:

- `main.py` — fixed-input detection, digit OCR and DXF pipeline
- `train_yolo.py` / `trainer.py` — detector and digit-recognition training scripts
- `detection.py`, `ocr.py`, `model.py`, `dxf_export.py` — supporting modules
- `yolo_floorplan.pt` and `digit_ocr_resnet18.pth` — committed experimental model weights

This older pipeline uses YOLO for three object classes and a custom ResNet18 for handwritten digits. It is **not integrated into the Planline web API**, does not implement the planned review/constraint workflow, and should not be treated as validated for arbitrary plans. Its output is a research baseline to test and improve, not the promised end state of the application.

To run that separate experiment, install the root ML dependencies and use the repository's fixed `test.jpg` input:

```bash
python -m pip install -r requirements.txt
python main.py
```

## Repository layout

```text
floorplan-digitizer/
├── web/                         # Planline browser interface
├── backend/                     # Local FastAPI service and source preflight
│   └── pipeline/
├── docs/
│   ├── ARCHITECTURE.md           # System design, data contract and roadmap
│   ├── input.jpg                 # Legacy pipeline example input
│   ├── output.png                # Legacy pipeline example output
│   └── rysunek.png               # Project reference drawing
├── main.py                       # Separate experimental CLI pipeline
├── detection.py                  # Legacy detection post-processing
├── ocr.py / model.py              # Legacy digit OCR
├── dxf_export.py                 # Legacy DXF construction
├── train_yolo.py / trainer.py     # Legacy training scripts
└── requirements.txt              # Dependencies for the legacy ML pipeline
```

## Development principles

- Keep the workflow local-first and preserve the original scan.
- Treat every detected dimension as a candidate until checked.
- Keep printed OCR, handwritten OCR and geometric evidence distinguishable.
- Do not use general text OCR unless it adds measurable value to the dimension-reading task.
- Never invent missing dimensions or silently force geometry to close.
- Keep the sample UI, the old experimental pipeline and the future production analyser clearly separated.

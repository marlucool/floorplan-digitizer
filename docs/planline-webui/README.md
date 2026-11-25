# Planline — 2D Floor Plan Digitiser

A local-first workspace for reviewing scanned 2D floor plans. It includes a local API for files and project state; OCR, model training and geometry reconstruction are not included yet.

Read [ARCHITECTURE.md](ARCHITECTURE.md) for the local-first OCR, training, uncertainty review, constraint and 2D reconstruction plan. It separates implemented components from planned model work.

## Run it

For the full local workflow, run the backend and open `http://127.0.0.1:8000`:

```powershell
python -m uvicorn backend.app:app --reload
```

Opening `index.html` directly still provides the sample workflow and in-browser preview, but cannot save uploaded projects.

## Working in the prototype

- **Three-step workflow:** use **Add drawing**, **Review dimensions**, and **Preview & export** as separate, uncluttered screens. The final screen unlocks only when the sample chain matches and all sample dimensions have been confirmed.
- **Sample project:** edit the illustrative dimension values, mark readings reviewed, compare their sum with the overall dimension, and export an illustrative DXF in millimetres.
- **Import drawing:** choose or drop a PNG, JPG, WEBP, TIFF, or PDF up to 50 MB. Image preview depends on browser support; PDF pages are not rendered here. TIFF preview support varies by browser.
- **Uploaded drawing:** the selected file is previewed locally. Sample measurements become read-only, sample DXF export is disabled, and the UI labels the measurements as illustrative placeholders. Reset returns to the sample project.
- **Local handling:** when run through the backend, the chosen file and project record are stored only in `runtime/projects/` on this computer. Opening the HTML file directly keeps the file only in the browser session.

## What is implemented

- Responsive workspace with source preview and an illustrative 2D plan.
- Local file selection, drag and drop, image preview where supported, and PDF selection state.
- Editable sample dimensions, verification toggles, review progress, and a live dimension-chain check.
- Sample DXF download, explicitly limited to the illustrative geometry.
- Accessible labels and keyboard focus indicators for interactive controls.
- A local FastAPI service for projects, source files, analysis status, corrections, and guarded DXF export. See [backend/README.md](backend/README.md).

## What is not implemented

- No OCR or handwriting recognition runs. Confidence values are examples, not model scores.
- No wall, opening, or dimension detection runs on uploaded drawings.
- No geometry is reconstructed from an upload. The sample plan remains separate from the uploaded image.
- No claim of 95%+ recognition accuracy is made or measured by this prototype.
- No backend, project persistence, or DXF export from uploaded drawings is included.

## Intended next stage

Connect this interface to a local Python service for scan preparation, printed and handwritten dimension detection, OCR, dimension-chain consistency checks, uncertainty review, geometric constraints, and verified 2D export. Uncertain readings should remain visibly unresolved until a person confirms them. The API routes sketched in the original prototype README were proposals only; no API implementation is included.

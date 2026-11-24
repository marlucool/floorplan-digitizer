# Planline web interface

The browser UI and local FastAPI service are one application. Start the server from the repository root; do not open the HTML file directly.

## Start locally

```bash
python -m pip install -r requirements-web.txt
python -m uvicorn planline.api:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. The default bind address is loopback-only. To make the service reachable from another device, change the bind address deliberately and put an authenticated, encrypted access layer in front of it; do not expose the development server directly to the public internet.

## Current workflow

1. Select a PNG, JPG, WEBP, TIFF or PDF file (maximum 25 MB).
2. The browser uploads the source to `POST /api/analyze`.
3. The API decodes the image or rasterises page one of a PDF in memory, then runs the repository's `yolo_floorplan.pt` detector.
4. The API returns source pixel dimensions, class counts, candidate bounding boxes, detector scores and a reduced preview.
5. The UI draws the returned boxes over the preview. Use the class filter to narrow the list, select a detection row to highlight its box, and hide/show the overlay.

The application does not intentionally save an uploaded drawing as a project file. However, FastAPI/Starlette receive multipart uploads using a spooled temporary file: smaller uploads may remain in memory, while larger uploads can roll over to temporary disk storage before this endpoint reads them. The endpoint then reads the file into memory for decoding and closes the upload. Therefore, this is **not a guarantee of memory-only handling**. Review the operating-system temporary directory, container storage, reverse-proxy buffering, server logs and browser caches before processing sensitive drawings. The 25 MB application check is performed after multipart parsing, so it is not a pre-parser disk-spooling limit.

## API

- `GET /api/health` — lightweight service/model readiness status; does not load the detector.
- `POST /api/analyze` — candidate-region detection for one uploaded file.
- `GET /docs` — interactive FastAPI/OpenAPI documentation.
- `GET /architecture` — the project architecture, research findings and implementation roadmap.

## What is and is not implemented

| Capability | Status |
|---|---|
| Image import and preview | Implemented |
| First-page PDF rasterisation | Implemented; multi-page selection is not |
| YOLO candidate detection | Implemented when the tracked weights are present |
| Detection list, class filter, box selection | Implemented in the UI |
| OCR of printed/handwritten dimensions | Not implemented in this web workflow |
| Dimension-to-wall association | Not implemented |
| Dimension-chain constraint solving | Not implemented |
| Scale calibration from written dimensions | Not implemented |
| Measured 2D reconstruction | Not implemented |
| Verified DXF export | Not implemented; intentionally unavailable |

A detection score is the model's confidence for a class prediction. It is not OCR confidence, a calibrated probability of correctness, or evidence that a dimension value has been read. A bounding box is not a wall centreline or architectural measurement. Do not derive millimetres from pixel proportions.

## Known limitations and risks

- The bundled detector was trained on a small set of simplified drawings. Old scans, faded marks, skew, annotations and different drafting conventions may produce false positives and missed detections.
- PDF support analyses only page one. Password-protected PDFs are rejected.
- The model is lazy-loaded on the first analysis request; the health endpoint only checks whether the weight file exists.
- Browser overlay alignment is based on the reduced preview and source-image coordinate dimensions. It is a visual review aid, not an annotation-authoring or measurement surface.
- The current detector endpoint is synchronous. Large or concurrent jobs may need a background-job design and explicit resource limits before multi-user deployment.

## Development checks

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=. python -m pytest -q
node --check web/app.js
```

The automated tests use a fake detector. Passing them verifies API behaviour and serialization, not the accuracy of the real model. A separate smoke test with the actual weights and representative scans is still required.

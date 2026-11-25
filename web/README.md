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
5. The UI draws the returned boxes over the preview. Use the zoom controls to inspect small annotations, Fit to return to the fitted view, the detector-threshold slider to trade off candidate recall against false positives, the class filter to narrow the list, and a detection row to highlight its box. The overlay can be hidden or shown independently of the detection list. After analysis, `Export JSON` downloads a versioned candidate-review file with source pixel dimensions, bounding boxes and detector scores; it does not include the uploaded image or claim to contain measurements. The collapsed manual dimension-chain checker lets a reviewer enter segment and overall values and verify their arithmetic; it is not OCR and does not associate values with detected walls.

The application does not intentionally save an uploaded drawing as a project file. However, FastAPI/Starlette receive multipart uploads using a spooled temporary file: smaller uploads may remain in memory, while larger uploads can roll over to temporary disk storage before this endpoint reads them. The endpoint then reads the file into memory for decoding and closes the upload. For raster images, Pillow checks the header dimensions against the pixel limit before OpenCV allocates the decoded raster; the limit is checked again after decode. PDF page dimensions are checked before rasterisation. Therefore, this is **not a guarantee of memory-only handling**. Review the operating-system temporary directory, container storage, reverse-proxy buffering, server logs and browser caches before processing sensitive drawings. The 25 MB application check is performed after multipart parsing, so it is not a pre-parser disk-spooling limit.

## API

- `GET /api/health` — lightweight service/model readiness status; does not load the detector.
- `POST /api/analyze` — candidate-region detection for one uploaded file. Optional multipart field `confidence_threshold` defaults to `0.25` and must be in `(0, 1]`; the UI exposes a narrower `0.05–0.80` range.
- `POST /api/validate-dimension-chain` — arithmetic check for explicitly supplied dimension values and verification flags. This does not run OCR or associate dimensions with walls.
- `GET /docs` — interactive FastAPI/OpenAPI documentation.
- `GET /architecture` — the project architecture, research findings and implementation roadmap.


### Candidate review JSON

The **Export JSON** button is enabled after an analysis result is returned. It downloads a `planline-detection-review/v1` document containing:

- Original source filename and source pixel dimensions.
- Detector name, confidence threshold and pixel-coordinate convention.
- Per-class counts and candidate IDs, classes, confidence scores, bounding boxes and centres.
- Explicit limitations stating that OCR, dimension association, scale calibration and measured DXF generation have not occurred.

The export intentionally excludes the uploaded image and crop pixels. It includes user-entered dimension-text transcriptions with source detection IDs, a printed/handwritten/unclear style label and verification flags, but not manual dimension-chain entries. It is a review/interchange artifact, not a CAD file or verified measurement record. The version 1 contract is defined in [the JSON Schema](../schemas/planline-detection-review-v1.schema.json).

### Manual dimension-chain validation

The API accepts already-read values so the manual review panel can check a dimension chain without guessing. Example request:

```json
{
  "segment_values": ["3000", "4500", "2500"],
  "segment_verified": [true, true, true],
  "overall_value": "10000",
  "overall_verified": true,
  "unit": "mm",
  "tolerance": "0"
}
```

The response status is one of:

- `matches` — every value is verified and the sum matches within the explicit tolerance;
- `mismatch` — every value is verified, but the sum differs beyond tolerance;
- `needs_review` — values are present, but one or more are not verified;
- `unresolved` — a segment or overall value is missing.

Values use decimal arithmetic. The endpoint does not parse OCR text, convert units, infer missing values, associate dimensions with geometry, or enable DXF export. The caller must supply one consistent unit for the entire chain; the API does not verify that the drawing actually uses that unit. The dimension-value crop panel is for manual transcription only; entries are user-entered text and are not OCR output. Crops are taken from the original raster with padding and bounded to a maximum 384-pixel edge; at most 30 candidates receive crops per analysis. Crop pixels are not embedded in the review JSON export.

## What is and is not implemented

| Capability | Status |
|---|---|
| Image import and preview | Implemented |
| First-page PDF rasterisation | Implemented; multi-page selection is not |
| YOLO candidate detection | Implemented when the tracked weights are present |
| Detection list, class filter, box selection | Implemented in the UI |
| Manual transcription of dimension-value crops | Implemented; user-entered text only, not OCR |
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


## Real-weight smoke test (opt-in)

The regular CI suite uses a fake detector so it stays lightweight and deterministic. To verify that the actual `yolo_floorplan.pt` loads and runs inference on a representative scan, install the web dependencies and run the opt-in integration test.

PowerShell:

```powershell
python -m pip install -r requirements-web.txt
$env:PLANLINE_RUN_MODEL_SMOKE = "1"
$env:PLANLINE_SMOKE_IMAGE = "C:\path\to\representative-scan.png"
python -m pytest -m integration tests/test_real_model_smoke.py -q
```

Bash:

```bash
python -m pip install -r requirements-web.txt
PLANLINE_RUN_MODEL_SMOKE=1 PLANLINE_SMOKE_IMAGE=/path/to/representative-scan.png \
  python -m pytest -m integration tests/test_real_model_smoke.py -q
```

Set `PLANLINE_SMOKE_DEVICE=cpu` to force CPU inference, or use the Ultralytics device value appropriate to the local installation. The test checks model loading, class names, output shape and finite in-bounds boxes. It does **not** measure detection accuracy or validate OCR, dimensions, scale or geometry. Use a representative scan that you are permitted to test.

## OCR benchmark evaluation

The manual transcription export can serve as ground truth for comparing OCR engines. The evaluator does not run OCR; it compares a predictions JSON file against **verified** entries in a Planline review export and reports exact-string rate, prediction coverage and character error rate (CER), overall and by printed/handwritten/unclear style.

Prediction file format:

```json
{
  "engine": "PaddleOCR",
  "model": "PP-OCRv5_server_rec",
  "predictions": [
    {
      "detection_id": "det-001",
      "text": "4200",
      "confidence": 0.91
    }
  ]
}
```

Run:

```bash
python -m planline.ocr_eval \\
  --review planline-review.json \\
  --predictions paddleocr-predictions.json \\
  --output ocr-metrics.json
```

Only manually verified, non-empty reference strings are scored. Missing predictions count as empty strings. Only leading/trailing whitespace is trimmed; punctuation, decimal separators and units are compared exactly. Keep the review export and predictions file together so each result can be traced to its source detection.

## Development checks

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=. python -m pytest -q tests/test_*.py
node --check web/app.js
```

Optional browser smoke test (requires a local Chromium installation):

```bash
python -m pip install -r requirements-e2e.txt
python -m playwright install chromium
python -m pytest -q tests/e2e
```

The browser test exercises local image preview, zoom controls and the manual dimension-chain checker with API responses stubbed. It does not validate YOLO accuracy or OCR.

The automated tests use a fake detector. Passing them verifies API behaviour and serialization, not the accuracy of the real model. A separate smoke test with the actual weights and representative scans is still required.


Detector confidence is a model filtering threshold, not a calibrated probability of correctness or measurement confidence.

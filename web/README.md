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
3. The API decodes the image or rasterises the explicitly selected PDF page in memory, then runs the repository's `yolo_floorplan.pt` detector.
4. The API returns source pixel dimensions, class counts, candidate bounding boxes, detector scores and a reduced preview.
5. The UI draws the returned boxes over the preview. Use zoom, Fit, the detector threshold, class filter and detection list to inspect candidates. The review toolbar supports search and sorting. When the local PaddleOCR inference runtime is available, the Drawing workspace automatically sends the detected dimension crops (up to 30 per analysis) to the recogniser. OCR text is inserted into each dimension row and interpreted using the conservative unit parser; it remains an unverified draft. The geometric association stage ranks dimension-value boxes against dimension-line boxes and wall spans, then preselects its global best wall-gap match where one exists. Check the crop, text, line and wall pair, then explicitly confirm both the transcription and association. A confirmed linear dimension/span pair can derive a candidate pixel-to-mm scale directly from the span's pixel length. No match or scale is silently verified. The manual dimension-chain checker remains a separate arithmetic tool; it does not infer which drawing geometry a chain describes.

The application does not intentionally save an uploaded drawing as a project file. However, FastAPI/Starlette receive multipart uploads using a spooled temporary file: smaller uploads may remain in memory, while larger uploads can roll over to temporary disk storage before this endpoint reads them. The endpoint then reads the file into memory for decoding and closes the upload. For raster images, Pillow checks the header dimensions against the pixel limit before OpenCV allocates the decoded raster; the limit is checked again after decode. PDF page dimensions are checked before rasterisation. Therefore, this is **not a guarantee of memory-only handling**. Review the operating-system temporary directory, container storage, reverse-proxy buffering, server logs and browser caches before processing sensitive drawings. The 25 MB application check is performed after multipart parsing, so it is not a pre-parser disk-spooling limit.

## Desktop OCR Studio

The installed Windows app opens OCR Studio in its native desktop window. Normal users should use the single interactive Planline-Setup.exe installer linked from the root README; the source-launch commands below are for contributors only.

### Launch from a source checkout (development only)

Browser mode:

~~~bash
python -m pip install -r requirements-web.txt
python -m uvicorn planline.api:app --host 127.0.0.1 --port 8000
~~~

Then open http://127.0.0.1:8000/ocr.

Native desktop mode:

~~~powershell
py -3 -m pip install -r requirements-desktop.txt
.\run_planline_desktop.bat
~~~

On macOS/Linux, install requirements-desktop.txt and run sh run_planline_desktop.sh. The desktop launcher selects a free loopback port, starts the same FastAPI app and opens a native WebView window. Keep the service loopback-only; it has no user authentication and must not be exposed directly to a LAN or the public internet.

### Crop and label workflow

1. Create or select a local dataset.
2. Add one scan or multiple crops from the same source drawing.
3. Drag around one complete dimension string, keeping punctuation and units inside the selection.
4. Enter the exact text as written, choose printed/handwritten/unclear/unknown, and confirm the transcription against the source before saving.
5. Reuse the same source ID for all crops from the same drawing. Use a stable pseudonymous writer ID for one handwriting author when evaluating generalisation across writers.
6. Review, correct or delete saved labels in the sample library. Any label/group change invalidates the previous split plan.

Only the selected crop is sent to the local API. The full input scan stays in the browser. The Drawing workspace can also send an individual dimension crop directly into a selected OCR dataset after its transcription is manually verified. Saved crop images and manifests are written below datasets/ocr/ for source/development runs. Installed Windows builds use %LOCALAPPDATA%/Planline/ocr, outside the application folder. The OCR Studio endpoint accepts raster images only; add PDF pages through the drawing workflow or rasterise the desired page locally before adding it as an image. Do not commit personal property information or complete source plans into the repository.

### Training and evaluation

The Windows installer provisions the compatible PaddlePaddle and PaddleOCR inference runtime in Planline's private Python environment. OCR Studio can prepare the pinned PaddleOCR source checkout and matching PP-OCRv5 pretrained checkpoint on demand for fine-tuning; those larger training assets are not bundled with the installer. The mobile recogniser is the initial low-memory option; the server model has higher memory requirements.

Build drawing-safe splits before training. Samples sharing a source drawing or writer ID are kept in one connected group so crops from one drawing/author cannot leak across train, validation and test. Fine-tuning receives train and validation data only; the held-out test split is excluded from optimisation. Benchmark runs generate predictions and calculate exact full-string match, prediction coverage and character error rate on the held-out test group.

A small number of crops validates the workflow, not model quality. No claim of useful recognition accuracy is made until representative, independent drawings have been labelled and the model has been evaluated on a sufficiently varied held-out set. OCR Studio manages training data and models; the Drawing workspace performs geometric candidate association and can derive a candidate scale from a confirmed dimension/span pair. Neither workspace automatically reconstructs measured CAD geometry.

## Manual geometry export

The Drawing workspace can export user-authored wall segments and closed room outlines as SVG or DXF. DXF is a 2D AutoCAD R2000-compatible ASCII file with separate `WALLS` and `ROOMS` layers. When a manual two-point scale or a scale derived from a confirmed dimension/span association is present, coordinates are converted to millimetres and `$INSUNITS` is set accordingly; without calibration, the DXF is unitless and retains source-pixel distances. Image Y coordinates are flipped into CAD Cartesian coordinates. Only manual geometry is exported: detector boxes, OCR suggestions and calculated dimension candidates are never promoted to walls or rooms. This export is not a dimension-constrained or verified CAD reconstruction.

## API

- `GET /api/health` — lightweight service/model readiness status; does not load the detector.
- `POST /api/analyze` — candidate-region detection for one uploaded file. Optional multipart field `confidence_threshold` defaults to `0.25` and must be in `(0, 1]`; the UI exposes a narrower `0.05–0.80` range.
- `POST /api/ocr/recognize-review` — recognition-only OCR for dimension crops from a review export; the Drawing UI calls it automatically when the local OCR runtime is ready.
- `POST /api/interpret-dimension` — conservative parsing of explicitly written metric/imperial dimension strings.
- `POST /api/validate-dimension-chain` — arithmetic check for explicitly supplied dimension values and verification flags. This remains separate from geometric association.
- `GET /docs` — interactive FastAPI/OpenAPI documentation.
- `GET /architecture` — renders the maintained architecture, implementation status, research findings and roadmap as a themed HTML page.


### Candidate review JSON

The **Export JSON** button is enabled after an analysis result is returned. It downloads a `planline-detection-review/v1` document containing:

- Original source filename and source pixel dimensions.
- Detector name, confidence threshold and pixel-coordinate convention.
- Per-class counts and candidate IDs, classes, confidence scores, bounding boxes and centres.
- Explicit limitations that distinguish OCR suggestions, candidate associations, confirmed review state, candidate scale and the absence of measured DXF reconstruction.

The export intentionally excludes the uploaded image and crop pixels. It includes OCR drafts and/or corrected dimension text, parser results, source detection IDs, writing-style and verification flags, association candidates and reviewer selections, calibration provenance and limitations. It is a review/interchange artifact, not a CAD file or verified reconstruction. The version 1 contract is defined in [the JSON Schema](../schemas/planline-detection-review-v1.schema.json).

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

Values use decimal arithmetic. The endpoint does not parse OCR text, convert units, infer missing values, associate dimensions with geometry, or enable DXF export. The caller must supply one consistent unit for the entire chain; the API does not verify that the drawing actually uses that unit. The dimension-value crop panel receives OCR draft text when the local recogniser is available; reviewers can correct it manually. Parsed values and OCR output remain unverified until checked. Crops are taken from the original raster with padding and bounded to a maximum 384-pixel edge; at most 30 candidates receive crops per analysis. Crop pixels are not embedded in the review JSON export.

## What is and is not implemented

| Capability | Status |
|---|---|
| Image import and preview | Implemented |
| Multi-page PDF rasterisation | Implemented; select a page before analysis; password-protected PDFs are rejected |
| YOLO candidate detection | Implemented when the tracked weights are present |
| Detection list, class filter, box selection | Implemented in the UI |
| Dimension OCR in drawing review | Automatically runs on detected dimension crops when local PaddleOCR is available; OCR drafts are interpreted but never verified automatically |
| OCR Studio crop annotation and verified label library | Implemented at /ocr; only selected raster crops are uploaded |
| Source/writer-grouped splits and OCR dataset audit | Implemented; held-out test set remains separate |
| PP-OCRv5 fine-tuning and benchmark orchestration | Implemented; requires local PaddlePaddle/PaddleOCR dependencies and checkpoint |
| Automatic OCR of all drawing text across the entire sheet | Not implemented; OCR runs on YOLO dimension-value crops only, up to 30 per analysis |
| Dimension-value → dimension-line → wall-span association | Geometric candidates ranked and global best match preselected; axis-aligned box heuristic, reviewer confirmation required |
| Dimension-chain constraint solving | Not implemented |
| Scale from a written dimension | Candidate scale derived from a verified text and reviewer-confirmed wall-span association; multi-dimension reconciliation is not implemented |
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

## Optional PaddleOCR recognition runner

An optional offline runner applies PaddleOCR's recognition-only module to the dimension crops already identified by YOLO. The default is `PP-OCRv5_mobile_rec`, matching the mobile fine-tuning configuration in OCR Studio; use `--model PP-OCRv5_server_rec` to compare the server variant.

1. Install a compatible PaddlePaddle CPU or GPU package using the [official installation guide](https://www.paddleocr.ai/latest/en/version3.x/installation.html).
2. Install the optional OCR package:

```bash
python -m pip install -r requirements-ocr-paddle.txt
```

3. Run recognition against the exact same raster image used to create the review export:

```bash
python -m planline.ocr_paddle \\
  --review planline-review.json \\
  --image original-scan.png \\
  --output paddleocr-predictions.json
```

Use `--device gpu:0` only when a compatible PaddlePaddle GPU build is installed; the default is CPU. The first run may download model weights. This runner currently accepts raster images, not PDFs. It checks the source pixel dimensions against the review export and uses its saved crop bounds. It emits raw, unverified text and confidence only; it does not correct values, parse units or infer geometry.

The default Planline install does not include PaddleOCR or PaddlePaddle. The optional runner is tested with a fake recognizer in CI; actual PaddlePaddle installation and inference remain environment-specific.

To run the same recogniser against your curated local crop dataset (after creating and validating its split file):

~~~bash
python -m planline.ocr_paddle \
  --dataset datasets/handwriting \
  --output handwriting-predictions.json
~~~

Dataset predictions are keyed by crop_id. By default this recognises the whole dataset; use `--split test` to run only inference on the held-out test group, or `--split validation` for a diagnostic subset. This runner does not train the model.

## OCR benchmark evaluation

The manual transcription export or curated crop dataset can serve as ground truth for comparing OCR engines. The evaluator does not run OCR; it compares a predictions JSON file against **verified** labels and reports exact-string rate, prediction coverage and character error rate (CER), overall and by printed/handwritten/unclear style.

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

For a curated local crop dataset, score the held-out test split (the default) by crop_id. The dataset split is grouped by source drawing and writer, so related scans or handwriting stay together:

~~~bash
python -m planline.ocr_eval \
  --dataset datasets/handwriting \
  --predictions handwriting-predictions.json \
  --output handwriting-metrics.json
~~~

Use --split validation or --split train only for diagnostics. Use --split all only for a non-held-out summary, not as your final benchmark.

## Handwritten-dimension crop dataset

Your own manually cropped dimension images can be used directly. Planline can also extract verified crops from its review export.

### Option A — export crops reviewed in Planline

1. Analyse the source drawing in the web app.
2. In the dimension-candidate review, enter the complete text exactly as written, choose **Handwritten**, and tick **I checked this transcription** only after confirming it against the original.
3. Export the review JSON. Keep the exact raster image used for analysis; the JSON contains crop coordinates and labels, not image pixels.
4. From the repository root, run:

~~~bash
python -m planline.dataset export-review \
  --review planline-review.json \
  --image original-scan.png \
  --output-dir datasets/handwriting \
  --writer-id writer-01
~~~

The source ID defaults to the SHA-256 of the raster file. Pass --source-id with a stable drawing ID when multiple files or scans represent the same source plan. The command only exports non-empty, manually verified labels matching the selected style (handwritten by default). It uses the original source pixels and the saved crop bounds. For a PDF, supply a raster image of the same page that the detector analysed.

### Option B — import crops you made yourself

Create a CSV next to your crop images with these columns:

~~~csv
image,text,source_id,writer_id,text_style,verified
crops/plan-a-001.png,"4,200 mm",plan-a,writer-01,handwritten,true
crops/plan-a-002.png,2750,plan-a,writer-01,handwritten,true
crops/plan-b-001.png,3.65m,plan-b,writer-02,handwritten,true
crops/plan-c-001.png,1800,plan-c,writer-03,handwritten,true
~~~

- image is a path relative to the CSV file (or an absolute path).
- text is the exact visible string; preserve decimal marks and units rather than normalising them.
- source_id must be the same for every crop from the same drawing.
- writer_id is optional but should be a stable pseudonymous ID when known. Do not use a person's real name. Samples with the same writer_id are kept in the same split, even across different drawings. If every crop is from one writer, keeping that writer_id will intentionally make one group and prevent an independent split. You can omit writer_id to measure generalisation to unseen drawings by that same writer, but that will not test generalisation to new handwriting styles.
- text_style is handwritten, printed, unclear or unknown. The default import selects handwritten rows.
- verified must be true only after the label has been checked against the source.

Import, validate and split:

~~~bash
python -m planline.dataset import-csv --annotations crops.csv --output-dir datasets/handwriting
python -m planline.dataset validate --dataset datasets/handwriting
python -m planline.dataset split --dataset datasets/handwriting --seed 42
~~~

The dataset contains images/, manifest.jsonl and splits.json. Splits target 80/10/10, but actual proportions depend on how many independent source/writer groups you have. At least three independent groups are required. Crops connected by either source_id or writer_id are kept together to prevent near-duplicate drawing or handwriting leakage. Adding samples invalidates the old split file; regenerate it after curation. Use --force only when you deliberately want to replace an existing split plan.

### Run and benchmark OCR on the crop dataset

Once the dataset is curated, you can run the optional PaddleOCR recogniser across its crops:

~~~bash
python -m planline.ocr_paddle \
  --dataset datasets/handwriting \
  --output handwriting-predictions.json
~~~

The runner checks the dataset manifest and crop checksums before inference. It emits raw, unverified predictions keyed by crop_id. It does not train the recogniser or alter your labels. The evaluation command above uses the held-out test split by default.

### Cropping guidance

Use a tight crop around the **complete handwritten dimension**, with enough margin to retain punctuation, decimal points, unit marks and any distinguishing strokes. Do not split a multi-digit number into separate digit images. Avoid manually sharpening, thresholding, resizing or cleaning the crop before import; keep the original pixels so preprocessing can be evaluated consistently. If a value is ambiguous, leave it unverified and out of the training/evaluation set until it is resolved.

Only use drawings you own or have permission to use. The dataset tool stores crops and labels locally; the repository ignores the datasets/ directory. It does not upload drawings, train a model, or claim that the resulting dataset is representative by itself. Keep a range of plans, writers, scan qualities and dimension styles before drawing conclusions.

## Development checks

```bash
python -m pip install -r requirements-dev.txt
PYTHONPATH=. python -m pytest -q tests/test_*.py
python -m planline.dataset --help
node --check web/app.js
```

Optional browser smoke test (requires a local Chromium installation):

```bash
python -m pip install -r requirements-e2e.txt
python -m playwright install chromium
python -m pytest -q tests/e2e
```

The browser test exercises automatic OCR draft insertion and parsing, candidate association preselection, manual confirmation, scale derivation, project save/restore and geometry tools with API responses stubbed. It does not validate real YOLO or PaddleOCR accuracy.

The automated tests use a fake detector. Passing them verifies API behaviour and serialization, not the accuracy of the real model. A separate smoke test with the actual weights and representative scans is still required.


Detector confidence is a model filtering threshold, not a calibrated probability of correctness or measurement confidence.

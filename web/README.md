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
5. The UI draws the returned boxes over the preview. Use the zoom controls to inspect small annotations, Fit to return to the fitted view, the detector-threshold slider to trade off candidate recall against false positives, the class filter to narrow the list, and a detection row to highlight its box. The overlay can be hidden or shown independently of the detection list. The review toolbar also supports text search by candidate ID/class and sorting by detector score or region area. The workspace has section navigation, a persistent light/dark theme preference, and keyboard shortcuts (`Ctrl/Cmd+O` to choose a drawing, `Ctrl/Cmd+Enter` to analyse, and `Esc` to clear the current drawing). After analysis, `Export JSON` downloads a versioned candidate-review file with source pixel dimensions, bounding boxes and detector scores; it does not include the uploaded image or claim to contain measurements. The collapsed manual dimension-chain checker lets a reviewer enter segment and overall values and verify their arithmetic; it is not OCR and does not associate values with detected walls.

The application does not intentionally save an uploaded drawing as a project file. However, FastAPI/Starlette receive multipart uploads using a spooled temporary file: smaller uploads may remain in memory, while larger uploads can roll over to temporary disk storage before this endpoint reads them. The endpoint then reads the file into memory for decoding and closes the upload. For raster images, Pillow checks the header dimensions against the pixel limit before OpenCV allocates the decoded raster; the limit is checked again after decode. PDF page dimensions are checked before rasterisation. Therefore, this is **not a guarantee of memory-only handling**. Review the operating-system temporary directory, container storage, reverse-proxy buffering, server logs and browser caches before processing sensitive drawings. The 25 MB application check is performed after multipart parsing, so it is not a pre-parser disk-spooling limit.

## Desktop OCR Studio

Open /ocr in the local app. It is a separate workspace within the same FastAPI application, not a disconnected demo.

### Launch

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

Only the selected crop is sent to the local API. The full input scan stays in the browser. Saved crop images and manifests are written below datasets/ocr/, which is ignored by Git. The OCR Studio endpoint accepts raster images only; add PDF pages through the drawing workflow or rasterise the desired page locally before adding it as an image. Do not commit personal property information or complete source plans into the repository.

### Training and evaluation

Install a PaddlePaddle build compatible with the local Python/CUDA environment, then install requirements-ocr-paddle.txt into the same environment used to launch Planline. Fine-tuning additionally needs a local PaddleOCR source checkout and a matching PP-OCRv5 .pdparams checkpoint. The mobile recogniser and a conservative batch size are the initial low-VRAM option; the server model has a higher memory requirement.

Build drawing-safe splits before training. Samples sharing a source drawing or writer ID are kept in one connected group so crops from one drawing/author cannot leak across train, validation and test. Fine-tuning receives train and validation data only; the held-out test split is excluded from optimisation. Benchmark runs generate predictions and calculate exact full-string match, prediction coverage and character error rate on the held-out test group.

A small number of crops validates the workflow, not model quality. No claim of useful recognition accuracy is made until representative, independent drawings have been labelled and the model has been evaluated on a sufficiently varied held-out set. All OCR predictions remain candidates; this workbench does not associate a dimension with a wall, calibrate scale or generate measured CAD geometry.

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
| Manual transcription of dimension-value crops in drawing review | Implemented; user-entered text only, not OCR |
| OCR Studio crop annotation and verified label library | Implemented at /ocr; only selected raster crops are uploaded |
| Source/writer-grouped splits and OCR dataset audit | Implemented; held-out test set remains separate |
| PP-OCRv5 fine-tuning and benchmark orchestration | Implemented; requires local PaddlePaddle/PaddleOCR dependencies and checkpoint |
| Automatic OCR of all drawing detections in the main drawing workflow | Not implemented; OCR Studio currently captures human-selected crops |
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

## Optional PaddleOCR recognition runner

An optional offline runner applies PaddleOCR's recognition-only module to the dimension crops already identified by YOLO. The default is `en_PP-OCRv5_mobile_rec` (compact English recognizer); use `--model PP-OCRv5_server_rec` to compare the multilingual server recognizer.

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

Dataset predictions are keyed by crop_id. This recognises the whole dataset; it does not train the model.

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

The browser test exercises local image preview, zoom controls and the manual dimension-chain checker with API responses stubbed. It does not validate YOLO accuracy or OCR.

The automated tests use a fake detector. Passing them verifies API behaviour and serialization, not the accuracy of the real model. A separate smoke test with the actual weights and representative scans is still required.


Detector confidence is a model filtering threshold, not a calibrated probability of correctness or measurement confidence.

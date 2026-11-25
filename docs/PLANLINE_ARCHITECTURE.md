# Planline architecture and implementation roadmap

## Product boundary

Planline is a **2D scanned-drawing digitisation** project. The target output is editable 2D vector/CAD geometry (DXF), not a 3D model. A scanned drawing may be skewed, faded, low resolution, or not drawn to scale. Consequently, pixel geometry is evidence about shape and adjacency, not authoritative real-world measurement.

The central rule is:

> A written dimension, once correctly read and associated with the correct measured span, is the authority for metric geometry. Pixel proportions must not silently replace missing or ambiguous dimensions.

A dimension that is unreadable, unassociated, contradictory, or insufficient to constrain geometry must remain unresolved and be presented for review.

## Current application state

The current web integration is intentionally a detection-and-review slice:

- FastAPI serves the browser UI and exposes `/api/health` and `/api/analyze`.
- PNG/JPG/WEBP/TIFF and PDF uploads are accepted within the configured limits.
- Multi-page PDFs support explicit 1-based page selection in the drawing workspace; each selected page is rasterised independently and source page identity is preserved in the review result.
- The existing YOLO weights detect candidate `wall`, `dimension_line`, and `dimension_value` regions.
- The UI displays the preview, candidate boxes, class counts, detector scores, a configurable confidence threshold, brightness/contrast preparation, filtering, selected-box highlighting, zoom/fit controls and a scrollable zoomed view.
- A candidate-review JSON export preserves source pixel dimensions, detector metadata, bounding boxes, scores, optional user-entered dimension-text transcriptions, and optional user-supplied two-point scale calibration under a versioned schema; it excludes source/crop pixels and is not a measurement record.
- The dimension-value crop panel returns bounded crops from the original raster for manual transcription. User-entered text, a printed/handwritten/unclear style label and verification flags are included in the review JSON; this does not run OCR or associate text with geometry.
- The application does not automatically persist source drawings or upload them to a server. Users can explicitly save a portable `.planline` project containing the embedded source file, analysis payload and manual review state; the file remains under the user’s control. No measured DXF is emitted.
- Raster image dimensions are preflighted from the image header before OpenCV decodes the full image; the pixel limit is enforced again after decode. PDF page dimensions are checked before rasterisation.
- A manual two-point scale calibration is available after analysis. It records the source-image pixel coordinates, known distance, unit, pixels-per-millimetre factor and source page in the review JSON. It is a user-supplied reference only; it does not verify the reference dimension, correct scan distortion, associate dimensions with walls or create measured geometry.
- A manual `/api/validate-dimension-chain` endpoint checks explicitly supplied values with decimal arithmetic and verification flags. It does not perform OCR, unit conversion, geometry association or DXF export.
- The UI can export candidate detections as a versioned JSON review artifact containing source pixel dimensions, model metadata and detector boxes. It excludes the source image and does not represent verified measurements.

### Portable project files

The Drawing workspace supports explicit save/open of versioned `.planline` JSON project files. A project embeds the original source file (up to the existing 25 MB source limit), current analysis payload, manual dimension transcriptions, association selections, scale calibration, user-drawn wall segments and manual room polygons. Saving is user-initiated; there is no background project upload or server-side project storage. Project import validates the format version and source byte count before replacing the current workspace. Keep project files in a trusted local location because they contain the source drawing.

### Manual room boundaries and area

A reviewer can create a room polygon by clicking at least three corners and explicitly finishing the outline. Self-crossing outlines are rejected. Area is calculated from the polygon using the shoelace formula. Without calibration, only square pixels are reported; with calibration, the app displays a derived square-metre value that is explicitly tied to the user-supplied, unverified two-point reference. Room polygons are user-authored and are not inferred from detector boxes or automatically closed.

### Manual wall geometry

The Drawing workspace includes a user-driven wall-segment layer. The reviewer selects Draw wall and clicks a start and end point in source-image coordinates. Segments can be selected, have either endpoint dragged to correct the line, deleted, undone or cleared, and exported as SVG. Selected wall lengths are shown in pixels or derived metres when a user-supplied scale is available. These lines are explicitly user-created; detector boxes are never promoted to walls automatically. SVG physical sizing uses the user-supplied scale reference when present and records that it is not verified geometry. This is not DXF export or automatic topology reconstruction.

### Manual wall geometry

The Drawing workspace includes a user-driven wall-segment layer. The reviewer selects Draw wall and clicks a start and end point in source-image coordinates. Segments can be selected, deleted, undone or cleared, and exported as SVG. These lines are explicitly user-created; detector boxes are never promoted to walls automatically. SVG physical sizing uses the user-supplied scale reference when present and records that it is not verified geometry. This is not DXF export or automatic topology reconstruction.

### Image intensity preparation

The Drawing workspace exposes bounded brightness (-100 to +100) and contrast (0.5× to 2×) adjustments before detection and crop generation. This is a linear intensity transform only: image dimensions and pixel coordinates are unchanged, so existing source-coordinate annotations and two-point calibration remain aligned. The original uploaded file is embedded unchanged in a saved project. These controls do not deskew, dewarp or crop a drawing.

### Manual scale calibration

The Drawing workspace allows a reviewer to click two source-image points and enter their known separation in mm, cm, m, inches or feet. The preview click coordinates are mapped back to the original raster coordinate system before computing pixels per millimetre. Calibration is scoped to the currently analysed source page and is included in the exported review JSON. It is never inferred from OCR or detector boxes. The result is explicitly labelled as a user-supplied reference and must not be treated as validation of any wall, dimension or reconstructed geometry. A single global factor also cannot correct perspective or local scan distortion.

### Detection resolution risk

The current API sends the complete source image to YOLO with `imgsz=640` and exposes a configurable confidence threshold (default `0.25`). On a large scanned sheet, small dimension text and thin annotation features can be reduced to only a few pixels before detection. The bounded 1600-pixel browser preview does not change the inference input; it is only for display.

The 2026 *Buildings* study uses density-adaptive overlapping crops because a single fixed resize can lose small targets in large drawings. Its reported crop sizes and performance are specific to its own dataset and model and must not be copied as Planline defaults without testing.

Planned approach:

- Benchmark full-frame inference against overlapping tile inference on the same held-out source drawings.
- Preserve each crop's offset and map every detection back to original source-image coordinates.
- Merge overlapping detections with class-aware NMS, and measure duplicate and missed detections at tile boundaries.
- Compare several crop sizes and overlap ratios, including crowded dimension bands and sparse plan regions.
- Keep the original full-resolution scan as the source of truth; never use the resized preview as the measurement coordinate system.

Do not enable tiled inference by assumption alone: the current detector was trained on a small simplified-plan dataset, and higher-resolution crops cannot compensate for a domain mismatch.

The API tests use a fake detector. They do not establish the real model's accuracy or prove that it works on representative scans. An opt-in real-weight smoke test is now available in `tests/test_real_model_smoke.py`; running it with the actual weights and representative old scans remains outstanding.

A Playwright browser smoke test covers image preview, zoom, zoomed overlay alignment, candidate JSON export/schema validation, manual dimension-chain entry and a narrow mobile viewport. Manual visual inspection and PDF-preview verification remain outstanding.

## Recommended processing architecture

Keep the stages modular and preserve their intermediate records. Do not combine OCR, association, scale recovery and geometry generation into one opaque function.

### 1. Ingest and preserve source coordinates

- Decode the original scan and retain its native width, height, orientation and page identity.
- For PDFs, make page selection explicit before multi-page support is considered complete.
- Apply geometric deskew/dewarp as a reversible transform; retain the transform so detected coordinates can be mapped back to the original source.
- Generate separate preprocessing views for line geometry and text recognition. A single aggressive thresholding pass can destroy either thin strokes or small characters.
- Keep the original source as the immutable review background.

### 2. Detect drawing primitives

The existing detector's three classes are a useful bootstrap, but are not enough to reconstruct a plan reliably. A later annotation schema should distinguish at least:

- wall strokes/regions and wall junctions;
- door/window openings where supported by the dataset;
- dimension lines, extension/witness lines and terminators (arrowheads or ticks);
- dimension text regions;
- general notes and room labels, so they can be excluded from dimension OCR.

Detection outputs should be represented in source-image coordinates and include model/version provenance. Detector confidence must not be presented as OCR confidence or as a calibrated probability.

### 3. Read complete dimension strings

Dimension OCR is not digit classification alone. It must preserve full strings and syntax, including decimal separators, units, prefixes/suffixes, tolerances, and common drafting marks. The system should store:

- raw OCR text;
- normalized candidate value and unit, if parsing is unambiguous;
- text bounding polygon/box and orientation;
- recognizer identity/version;
- confidence and per-character alternatives where available;
- review status and any human correction.

Printed and handwritten text should be evaluated separately before deciding whether they need separate recognition models. Rotate vertical text using the associated dimension-line orientation, not a blind global rotation guess.

### 4. Associate text with dimension graphics

Treat association as its own inference stage. Candidate evidence includes:

- proximity and orientation between text and dimension line;
- alignment with the dimension-line axis;
- extension-line endpoints and terminators;
- grouping of parallel/collinear dimension segments;
- neighbouring dimension strings and chain structure.

Do not attach a number to the nearest wall by distance alone. Store candidate associations and scores, and allow a reviewer to correct them. A text region may be a room label or note rather than a measurement.

### 5. Solve metric geometry as a constraint problem

Build a graph of geometric entities and constraints. Each verified dimension constrains a span between identified endpoints or references. Use multiple independent dimensions to detect contradictions and estimate only genuinely shared calibration parameters.

Important safeguards:

- Never invent a missing dimension from pixel ratios.
- Do not force dimensions onto a preferred module (for example, rounding to 50 mm) without explicit evidence and user approval.
- Do not average contradictory dimensions into a plausible-looking value.
- Track under-constrained, over-constrained and inconsistent systems separately.
- Preserve uncertainty and provenance through every derived coordinate.
- If a drawing has local distortion or multiple scales, do not assume one global pixel-to-unit factor.

A global scale estimate may be useful as a diagnostic when several trusted dimension spans agree. It must not override explicit written dimensions or conceal local scan distortion.

### 6. Reconstruct editable 2D topology

Only after the source strokes and dimension constraints have been reviewed should the system regularise geometry. Recover connected wall segments, junctions, openings and closed boundaries while preserving a link back to source pixels and detection records. Geometric cleanup must not invent a closing wall merely to make a polygon valid.

### 7. Gate DXF export

DXF export should be a separate, explicit operation that requires a validated project state. A future export should include clear layers (for example walls, openings, dimensions, annotations and review markers), units, and metadata/provenance where possible. Unresolved or contradictory dimensions should block a **measured** export, or be clearly marked as unmeasured if the user explicitly requests a non-metric tracing.

## Research findings that influence the design

### Floor-plan text extraction

Schönfelder et al., *Deep learning-based text detection and recognition on architectural floor plans*, Automation in Construction 157 (2024), article 105156, DOI: 10.1016/j.autcon.2023.105156.

The work highlights that floor-plan text is small, spatially scattered, may be rotated or occluded, and differs from ordinary document text. It evaluates both text-region detection and recognition and describes a synthetic-data generation approach. This supports keeping text localisation and OCR as distinct stages and evaluating complete strings rather than only isolated digits.

Reference: https://doi.org/10.1016/j.autcon.2023.105156

### Dimension-set recognition

Dori and Velkovitch, *Segmentation and Recognition of Dimensioning Text from Engineering Drawings*, Computer Vision and Image Understanding 69(2), 1998, pp. 196–201, DOI: 10.1006/cviu.1997.0585.

This work explicitly separates text/graphics separation, text-string extraction, association of text with graphics, recognition, and verification. It also uses drawing context and measured graphical evidence to verify OCR. This is a strong reason not to treat OCR output as a final measurement by itself.

Reference: https://doi.org/10.1006/cviu.1997.0585

### Scanned drawing vectorisation and reconstruction

A 2026 paper in *Buildings*, “A Hybrid Deep Learning and Rule-Based Method for Architectural Drawing Vectorization and CAD Reconstruction,” describes a pipeline combining dimension detection, text recognition, scale recovery, topology reconstruction and CAD regularisation. Its discussion of aged paper, uneven illumination, creases and skew is directly relevant to archival scans.

Reference: https://www.mdpi.com/2075-5309/16/5/1043

The paper's use of modular regularisation is not adopted as an automatic Planline rule: a drawing-specific module or grid assumption could incorrectly alter a real measurement. Any such prior must be optional, visible and independently validated.
The paper reports 89.3% accuracy for dimension-text recognition on a 150-sample test set. This is useful evidence that a tailored pipeline is feasible, but it is not a guarantee for Planline's scans, handwriting, or drafting conventions. Its reported detector mAP and its OCR accuracy measure different stages and must not be conflated. The paper also applies a 50 mm modular regularisation step; Planline will not silently snap dimensions to a module because a drawing may use different conventions or contain non-modular values.

### Dimension-aware text-to-geometry matching

Liang, Fukuda and Yabuki, *Automated dimension-aware BIM reconstruction from annotated floorplans through optimization-based text–geometry matching*, Automation in Construction 191 (2026), article 107204, DOI: 10.1016/j.autcon.2026.107204.

This 2026 work is especially relevant to Planline's core problem: it treats OCR-derived dimensions as **localized metric constraints** and explicitly links them to candidate geometric entities through an optimization-based matching stage. It argues that image-level metrics (IoU, mAP, F1) alone do not establish engineering-level correctness; component dimensions, placement and relationships need their own evaluation. It also discusses oblique/non-Manhattan geometry rather than assuming every plan is an orthogonal grid.

The paper's matching stage uses spatial position, orientation, perpendicular offset, projected position, line relationships, expected length and annotation-band context to score candidate text/segment pairs. It then uses joint decoding with a duplicate-use penalty so one OCR string is not casually assigned to several unrelated segments. The authors also explicitly report that ambiguous OCR or weak geometric compatibility can still lead to rejection, fallback to a global estimate, or a plausible but incorrect match.

Design implications:

- Store OCR observations and geometric candidates independently before attempting association.
- Represent a dimension as a constraint attached to a candidate span/entity, not as a free-floating number or a global scale label.
- Use direction, alignment, offset, endpoint/extension-line evidence, projected position and chain context to rank candidate associations; nearest-neighbour distance alone is inadequate.
- Prevent duplicate use of one OCR observation across unrelated spans, while allowing an explicit reviewer override.
- Keep multiple candidate text-to-geometry matches when evidence is ambiguous; require review instead of silently selecting the nearest wall.
- Do **not** copy the paper's global-scale fallback as a silent recovery path. If a written dimension cannot be associated confidently, preserve it as unresolved. A scale estimate may be shown separately as a diagnostic only.
- Evaluate final geometry using dimension residuals, endpoint/placement error and topology/relationship correctness, not only detector accuracy.
- Keep metric dimensions local. A drawing-wide scale may be a diagnostic, but must not override a verified written dimension or hide local distortion.

Reference: https://doi.org/10.1016/j.autcon.2026.107204 (open-access author manuscript: https://research.chalmers.se/publication/554882/file/554882_Fulltext.pdf)

### 2024 floor-plan OCR benchmark

Schönfelder et al. (2024) compare text-region detection and OCR approaches on architectural floor plans, including printed and handwritten challenges. Their paper notes that text is spatially scattered, small, rotated and sometimes occluded, and that generic OCR performance remains a limitation for this domain. The paper provides annotated floor-plan text data and a synthetic text-generation approach.

Planline should therefore benchmark candidate recognizers on **complete dimension strings**, not only isolated digits. Test sets must include rotation, low resolution, faded scans, line/text overlap, handwritten values, decimal separators and units. A high detector score cannot compensate for an OCR transcription error.

Reference: https://doi.org/10.1016/j.autcon.2023.105156

### Audit of the repository's existing digit OCR

The legacy main.py pipeline is not ready to be called from the web API as-is:

- It executes image loading, model loading, inference, file writes and DXF generation at module import time. Importing it from FastAPI would trigger the entire legacy workflow.
- Its ResNet18 classifier has ten outputs (0–9), so it is a **digit classifier**, not a full-string OCR recognizer.
- It thresholds the red channel at a fixed value and assumes the dimension marks are red. That is not a safe assumption for arbitrary archival scans or black/blue annotations.
- It concatenates predicted digits into an integer. Decimal marks, commas, units, prefixes, suffixes and tolerances are not represented.
- Low-confidence digits are printed as warnings, but their predicted classes are still appended to the final number. The pipeline therefore does not enforce an uncertainty gate.
- The original segmentation code and preprocessing have not been validated against representative old scans in the Planline web workflow.
- The legacy trainer randomly splits cropped samples from the same small source collection into train and test subsets. This does not provide a writer- or drawing-independent test set, so reported validation accuracy may overstate generalisation to a different scan, handwriting style or drafting convention.
- The legacy dataset creator previously failed to append a final digit segment when a row ended while the segment was still open, omitting samples at the right edge of a row. This was fixed in the current branch and is covered by regression tests. Unreadable source sheets are also skipped cleanly.

The existing model can be retained as an **experimental candidate recognizer** for the narrow drawing style it was trained on, but it must not become the authoritative dimension parser. Before integration, extract pure functions into an import-safe module, return per-character alternatives and confidence, preserve raw crops and preprocessing provenance, and require human confirmation of the complete string. Do not feed its output directly into geometry or DXF export.

### OCR engine selection: practical direction

PaddleOCR is a reasonable local baseline to evaluate because it provides text detection and sequence recognition components and is used in recent architectural-drawing research. It is not a guaranteed solution: floor-plan text detection, vertical orientation, small text and overlap with dimension graphics remain domain-specific failure modes. A second baseline should be evaluated against the same held-out scans rather than selecting an engine from generic document benchmarks.

Reference implementation: https://github.com/PaddlePaddle/PaddleOCR


### OCR baseline comparison (research update: 2026-11-25)

The manual crop/transcription panel now provides a source of verified text labels. Use those labels to benchmark recognizers before selecting or integrating an OCR dependency.

| Candidate | Relevant capability | Limitation for Planline | Decision |
|---|---|---|---|
| PaddleOCR PP-OCRv5 | Full text detection + recognition; documentation explicitly includes complex English handwriting and vertical text. The published internal recognition table reports a 0.5806 score for handwritten English versus 0.8679 for printed English. | Those are vendor-reported internal-set results, not floor-plan results. The handwriting score is not high enough to trust dimensions without review. | **First baseline to benchmark**, using original-resolution crops and human verification. |
| TrOCR base handwritten | MIT-licensed recognizer fine-tuned on IAM handwriting; intended for single text-line images. | Recognition only, not text detection; IAM handwriting is not architectural dimension notation. | **Second baseline** for crops already isolated by the detector. |
| EasyOCR | Convenient local text detection + recognition pipeline. | Its current project README lists handwritten-text support under “What's coming next”. | Do not select as the handwriting baseline. |
| Surya | Document OCR/layout system with handwritten-document examples. | The code is Apache 2.0, but model weights use a modified AI Pubs Open Rail-M license with restrictions; the current inference path also adds deployment complexity. | Do not make it a core dependency without a separate license/deployment review. |

References:
- [PaddleOCR Text Recognition module](https://www.paddleocr.ai/v3.3.1/en/version3.x/module_usage/text_recognition.html) — documented `TextRecognition` API, model names, input arrays and output `rec_text`/`rec_score` fields.
- [PaddleOCR PP-OCRv5 documentation](https://www.paddleocr.ai/v3.3.0/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html) — pipeline-level handwriting evaluation.
- [PaddleOCR repository](https://github.com/PaddlePaddle/PaddleOCR) — Apache 2.0 project license.
- [Microsoft TrOCR base-handwritten model card](https://huggingface.co/microsoft/trocr-base-handwritten) — MIT license, IAM fine-tuning and single-line OCR use.
- [EasyOCR README](https://github.com/JaidedAI/EasyOCR) — handwriting support remains listed as upcoming.
- [Surya README](https://github.com/datalab-to/surya) — separate code and model-weight licensing.

The optional `planline.ocr_paddle` runner applies PaddleOCR's recognition-only `TextRecognition` module to the saved `crop_bbox` regions. YOLO remains the region detector; PaddleOCR does not redetect the floor plan.

Recommended evaluation order:
1. Export manually verified dimension crops and use them as a small held-out benchmark. Keep printed and handwritten samples separate.
2. Run `en_PP-OCRv5_mobile_rec` on the crop images first, then compare `PP-OCRv5_server_rec`; preserve raw output, confidence and engine/model version.
3. Run TrOCR on the same handwritten line crops as a recognition-only comparison.
4. Report exact-string accuracy, character error rate, decimal/separator errors, unit errors and the proportion of crops requiring human correction. Include faint, skewed, rotated and overlapping examples.
5. Keep all machine results **unverified**. Only a human-confirmed complete string may enter the dimension-chain workflow.
6. Use `python -m planline.ocr_eval` to compare an engine's predictions against verified review exports. It reports exact-string rate and character error rate overall and by text style; it has no OCR-engine dependency.

Do not add either OCR package to the default install yet. The next step is a reproducible benchmark against representative scans, not another training run or an assumption that generic handwriting scores transfer to architectural dimensions.

### Floor-plan parsing challenges

The open-access paper *Automatic structural scene digitalization* (2017) describes common issues in raster floor-plan parsing: dimension leaders being confused with walls, backgrounds containing grids/patterns, variable text fonts and orientations, text touching graphics, and vectorisation failures at junctions.

Reference: https://pmc.ncbi.nlm.nih.gov/articles/PMC5693441/

### Upload handling and privacy boundary

FastAPI documents `UploadFile` as a spooled file: data can remain in memory up to a threshold and roll over to disk-backed temporary storage for larger multipart parts. Starlette also documents that uploaded files are spooled to temporary storage. Planline's 25 MB endpoint check happens after multipart parsing, so it bounds the application read/decode step but does not prevent the parser from receiving and temporarily spooling an oversized upload first. The API now checks the parsed `UploadFile.size` before copying it into the application byte buffer, then closes it. This is not equivalent to a strict pre-parser request-body limit.

References:
- FastAPI, [Request Files](https://fastapi.tiangolo.com/tutorial/request-files/) — describes the spooled upload implementation and disk rollover.
- Starlette, [Requests](https://www.starlette.dev/requests/) — documents multipart file spooling and parser limits.

For sensitive drawings, configure and monitor the server/container temporary directory, apply a request-body limit at the reverse proxy or ASGI boundary, and review logs and browser caching. Do not describe the current implementation as memory-only.

## Dataset strategy — research first, no training yet

Do not start another training run until the annotation schema, rights, evaluation split and target failure modes are agreed. The new planline.dataset CLI now provides the first curation step: it exports verified full-string crops from review JSON or imports manually cropped images using a CSV manifest, then validates checksums and builds source/writer-safe splits. It prepares data only; it does not train a recogniser.

A useful development dataset should contain both:

1. **Rights-cleared real scans** for realism and external validity. Record provenance, permission, allowed use, drawing identity, writer identity where relevant, and whether redistribution is allowed.
2. **Owned synthetic drawings** for exact ground truth and controlled coverage. Generate geometry and annotations parametrically, then render varied drafting styles and scan degradations.

Synthetic examples should vary line weights, text size, fonts, handwritten styles (only from appropriately licensed sources), rotation, skew, blur, faded ink, background stains, compression, occlusion, dimension placement, units and dimension-chain layouts. Keep the underlying vector geometry and all annotation associations as exact machine-readable ground truth.

Split training/validation/test by original drawing and writer, not by cropped digit or text patch. Otherwise nearly identical samples from one source can leak across splits and inflate evaluation.

## Suggested acceptance tests before model training

1. **Ingest:** correct dimensions/orientation for raster images; clear PDF page handling; reject malformed and oversized inputs.
2. **Detection:** per-class precision/recall on held-out drawings, with results stratified by scan quality and drafting style.
3. **OCR:** exact full-string accuracy, character error rate, unit/decimal parsing accuracy, and confidence calibration; report handwritten and printed subsets separately.
4. **Association:** correct text-to-dimension-line and dimension-line-to-span matching; measure both top-1 accuracy and reviewer correction rate.
5. **Constraints:** recover known dimensions from synthetic plans; detect inconsistent and under-constrained cases; never substitute pixel ratios for missing written values.
6. **Geometry:** endpoint/junction error, topology/connectivity accuracy, and dimension residuals in physical units.
7. **DXF:** open the exported file in at least one independent CAD reader and verify units, layers, coordinates and entity counts.
8. **Human review:** every uncertain or conflicting item must be visible, editable and traceable to its source region.

## Immediate engineering backlog

- [x] Connect the browser UI to the existing detector API.
- [x] Add candidate region review, class filtering and selected-box highlighting.
- [x] Add a user-adjustable detector confidence threshold; detector scores remain uncalibrated and are not measurement confidence.
- [x] Document API setup and the current capability boundary.
- [ ] Run a real-weight smoke test with `yolo_floorplan.pt` and representative old scans.
- [ ] Compare full-frame YOLO inference with overlapping multi-scale tiles on held-out scans before changing the default detector path.
- [ ] Audit the legacy digit classifier on held-out scans; do not integrate its current integer output as dimension OCR.
- [x] Fix and test end-of-row digit segmentation in `dataset_creator.py` before generating any replacement dataset.
- [x] Add a local OCR crop dataset curator/importer with verified labels, checksum validation and source/writer-grouped splits.
- [ ] Replace random crop-level validation with drawing-/writer-grouped held-out evaluation before trusting OCR accuracy.
- [ ] Benchmark at least two OCR baselines on complete dimension strings, including rotated, faded and handwritten samples.
- [ ] Add text-to-dimension-line and dimension-line-to-span association records with multiple candidates and human review.
- [ ] Evaluate metric correctness (dimension residuals and placement/topology errors), not only detection mAP or OCR character accuracy.
- [x] Add a Playwright browser smoke test for zoomed overlay alignment and a 390-pixel mobile viewport.
- [ ] Manually inspect the interface at desktop/mobile sizes and verify PDF preview behaviour.
- [ ] Add persistent project state only after defining privacy, retention and recovery requirements.
- [ ] Introduce a typed intermediate representation for detections, OCR observations, dimension associations and constraints.
- [ ] Add OCR as a reviewable stage; do not wire it directly to geometry generation.
- [x] Add a standalone manual dimension-chain arithmetic validator with explicit verification and tolerance states.
- [x] Add versioned candidate-review JSON export and a JSON Schema contract.
- [ ] Add dimension-to-line and line-to-span association; the current validator does not perform either task.
- [ ] Add manual geometry correction and measured DXF export only after validation gates exist.
- [ ] Revisit training only after rights-cleared data, annotation guidelines and a grouped evaluation split are ready.

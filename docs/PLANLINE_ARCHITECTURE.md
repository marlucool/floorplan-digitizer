# Planline architecture and implementation roadmap

## Product boundary

Planline is a **2D scanned-drawing digitisation** project. The target output is editable 2D vector/CAD geometry (DXF), not a 3D model. A scanned drawing may be skewed, faded, low resolution, or not drawn to scale. Consequently, pixel geometry is evidence about shape and adjacency, not authoritative real-world measurement.

The central rule is:

> A written dimension, once correctly read and associated with the correct measured span, is the authority for metric geometry. Pixel proportions must not silently replace missing or ambiguous dimensions.

A dimension that is unreadable, unassociated, contradictory, or insufficient to constrain geometry must remain unresolved and be presented for review.

## Implemented application state (reviewed 2026-11-28)

Planline is no longer just a detector preview. The current application is a **local-first drawing review and OCR workbench**, with manual geometry authoring and conservative dimension-analysis tools. The implemented features below are distinct from the future goal of automatic, measured CAD reconstruction.

### Drawing ingestion and detection

- The FastAPI application serves the dashboard, Drawing workspace, OCR Studio, Settings and the architecture reader. The main API includes health and drawing-analysis endpoints.
- Raster inputs include PNG, JPG/JPEG, WEBP and TIFF. PDF workflows support explicit 1-based page selection and rasterise the selected page independently while preserving page identity.
- The current YOLO detector proposes three classes: `wall`, `dimension_line` and `dimension_value`. These are candidate regions, not verified semantic geometry.
- The Drawing workspace shows the source preview, detector boxes, class counts, detector scores, confidence-threshold filtering, class filtering, selected-box highlighting, zoom/fit controls and a scrollable zoomed view.
- Brightness and contrast preparation is bounded and non-geometric. It preserves source dimensions and coordinates; it does not deskew, dewarp, crop or correct local scan distortion.
- Full-frame inference currently uses `imgsz=640`. Overlapping high-resolution tiling is still a benchmark item, not an enabled feature. Small text and thin strokes can be lost when large sheets are resized.

### Dimension review, OCR and association

- Reviewers can inspect bounded crops from detected dimension-value regions, enter the complete visible text, classify it as printed/handwritten/unclear and mark it verified. Candidate-review JSON exports preserve the source dimensions, model metadata, bounding boxes, scores, text transcriptions, verification state and optional user-supplied scale reference. The export is not a verified measurement record and excludes source/crop pixels.
- The Drawing workspace automatically runs the local PaddleOCR recogniser on detected dimension crops (up to the current 30-crop limit) when the inference runtime is available. Base or locally fine-tuned recognition models can be selected. OCR output is inserted as an interpreted draft with recogniser confidence; it is never verified automatically.
- A separate conservative dimension-text parser recognises supported explicit units and formats (including metric and common imperial forms). A bare number without a unit is not assumed to be millimetres, and ambiguous separators remain unresolved. Parsing is not proof that the OCR reading is correct.
- The dimension-association module ranks candidate relationships from dimension-value regions to dimension-line regions and wall gaps using orientation, alignment, projected position and nearby wall-box geometry. A dimension line may be shared by multiple labels in a chained dimension; the same candidate wall gap is not assigned to competing labels. Scores are relative rankings, not probabilities. Every proposed relationship requires reviewer confirmation.
- The dimension-chain checker uses decimal arithmetic to compare explicitly entered segment values with an overall value and a stated tolerance. It reports missing, unverified and conflicting values. It can propose the remainder for exactly one missing segment only when all known segments and the overall value are verified; that proposal still requires confirmation.
- A separate wall-dimension comparison checks the active pixel scale against an explicitly supplied dimension and reports its provenance (confirmed dimension/span association or manual two-point reference). It reports the difference and tolerance status, but does not rescale, move or validate the wall geometry.

### OCR Studio and datasets

- OCR Studio includes a crop editor, verified-label library, bulk import from verified Drawing reviews, bounded CSV-plus-images ZIP import, verified dataset ZIP export, manifest and checksum validation, source/writer-grouped split creation, dataset-quality reporting and training-job monitoring.
- Training and benchmark job snapshots and recent logs are persisted beside their run outputs. A browser reload reconnects to active jobs; an application restart marks unfinished jobs as interrupted rather than pretending that their subprocesses resumed.
- Local PaddleOCR PP-OCRv5 fine-tuning jobs can be configured from a matching pretrained checkpoint and PaddleOCR source checkout. Benchmark tooling evaluates a recogniser against a held-out test split and reports exact-string accuracy and character error rate.
- These features provide a reproducible training/evaluation workflow; they do **not** prove that a recogniser is accurate on real architectural drawings. Training still requires compatible local PaddlePaddle/PaddleOCR assets, representative rights-cleared crops and a genuinely independent held-out set. Do not describe a model as validated merely because a training job completes.
- The Windows installer provisions PaddlePaddle and the pinned PaddleOCR recognition runtime in Planline's private Python environment. OCR Studio downloads the pinned PaddleOCR source checkout and matching pretrained training checkpoint on demand when training assets are prepared or a training job is started; these larger assets are not bundled in the installer. The core web requirements keep the heavyweight training stack separate.

### User-authored geometry, projects and exports

- Reviewers can draw, select, move either endpoint of, delete, undo and clear manual wall segments. Room polygons can be created and edited; self-crossing or degenerate outlines are rejected. Optional snapping applies only to user-created endpoints and vertices.
- Wall lengths and room areas are reported in source pixels unless a user supplies a two-point scale reference. Calibrated metres or square metres are derived from that reference; they are not independently verified dimensions and a single global scale cannot correct perspective or local distortion.
- **Dimension-driven wall-edge draft (first-stage reconstruction):** after the reviewer verifies explicit linear dimension text and confirms the matching dimension line and two bounding wall detections, the API recomputes the candidate association and uses the agreed pixel span as a measurement. At least one horizontal and one vertical measurement are required; the median per-axis scale is used and inconsistent same-axis measurements block generation. Each clearly axis-aligned wall bounding box becomes two editable parallel face lines with source detection ID and confidence. Ambiguous/diagonal boxes are skipped. Near-coincident endpoints are emitted with explicit segment/endpoint references; the reviewer can join one pair at a time or undo it. Shared endpoints are not reused by multiple joins, and no automatic network repair, openings, rooms or scan perspective/skew correction is inferred.
- Portable, versioned `.planline` projects support explicit local save/open of the source file, analysis, review state, manual transcriptions, association selections, scale calibration, manual wall segments, the dimension-driven draft and its X/Y scale provenance, and room polygons. Project saving is user-initiated; there is no background project upload or server-side project store.
- SVG and DXF export support manual linework and the explicitly generated wall-edge draft. Draft edges are exported on a separate `DETECTED_WALL_DRAFT` DXF layer, with metric coordinates using confirmed X/Y scales; manually drawn segments remain on `WALLS` and room polygons on `ROOMS`. Detector boxes, OCR text or unconfirmed associations are never promoted to CAD entities.
- Raster dimensions are preflighted before full OpenCV decode and checked again after decode. PDF page dimensions are checked before rasterisation. The multipart request parser may spool uploads to temporary storage before the endpoint-level size check; the application must not be described as memory-only.

### Explicitly not implemented

The following remain future engineering work: reliable real-scan detector performance; tiled inference; reversible deskew/dewarp; automatic full-sheet OCR; automatic acceptance of text-to-line or line-to-span associations; a global metric constraint solver; joining wall faces into consistent junctions; room, door and window reconstruction; diagonal/non-orthogonal wall handling; and validated, verified measured CAD export. The current wall-edge draft is an intermediate, reviewable output, not an end-to-end automatic CAD pipeline.

A real-weight detector smoke test on representative older scans is still outstanding. API tests use a fake detector and therefore do not establish model accuracy. Browser automation covers key drawing, overlay, export and narrow-viewport behaviour; manual visual inspection across real scans and PDF cases remains outstanding.

## Recommended processing architecture

Keep the stages modular and preserve their intermediate records. Do not combine OCR, association, scale recovery and geometry generation into one opaque function.

### 1. Ingest and preserve source coordinates — implemented baseline

- Decode the original scan and retain its native width, height, orientation and page identity.
- PDF page selection is implemented: the user chooses a 1-based page, and source page identity is retained. Keep this selection explicit when extending PDF workflows.
- Apply geometric deskew/dewarp as a reversible transform; retain the transform so detected coordinates can be mapped back to the original source.
- Generate separate preprocessing views for line geometry and text recognition. A single aggressive thresholding pass can destroy either thin strokes or small characters.
- Keep the original source as the immutable review background.

### 2. Detect drawing primitives — implemented baseline, limited classes

The current detector proposes wall, dimension-line and dimension-value boxes. That is a useful bootstrap, but the detector and current annotation schema are not enough to reconstruct a plan reliably. Future detector coverage should distinguish at least:

- wall strokes/regions and wall junctions;
- door/window openings where supported by the dataset;
- dimension lines, extension/witness lines and terminators (arrowheads or ticks);
- dimension text regions;
- general notes and room labels, so they can be excluded from dimension OCR.

Detection outputs should be represented in source-image coordinates and include model/version provenance. Detector confidence must not be presented as OCR confidence or as a calibrated probability.

### 3. Read complete dimension strings — reviewable OCR implemented

Dimension OCR is not digit classification alone. Planline can run local PaddleOCR on selected dimension crops and stores reviewer-controlled transcription/verification state. A separate parser handles supported explicit dimension formats; ambiguous or unitless readings remain unresolved. Further OCR work must preserve full strings and syntax, including decimal separators, units, prefixes/suffixes, tolerances, and common drafting marks. The system should retain:

- raw OCR text;
- normalized candidate value and unit, if parsing is unambiguous;
- text bounding polygon/box and orientation;
- recognizer identity/version;
- confidence and per-character alternatives where available;
- review status and any human correction.

Printed and handwritten text should be evaluated separately before deciding whether they need separate recognition models. Rotate vertical text using the associated dimension-line orientation, not a blind global rotation guess.

### 4. Associate text with dimension graphics — candidate ranking implemented

Association is a separate, reviewable inference stage. Planline currently ranks text-to-dimension-line and dimension-line-to-wall-gap candidates from box geometry. Candidate evidence includes:

- proximity and orientation between text and dimension line;
- alignment with the dimension-line axis;
- extension-line endpoints and terminators;
- grouping of parallel/collinear dimension segments;
- neighbouring dimension strings and chain structure.

Do not attach a number to the nearest wall by distance alone. Store candidate associations and scores, and allow a reviewer to correct them. A text region may be a room label or note rather than a measurement.

### 5. Solve metric geometry as a constraint problem — partial validators implemented

The current application ranks dimension-value → dimension-line → wall-span candidates, preselects the global best match, and derives a candidate scale from a manually confirmed text/association pair. It also retains a manual dimension-chain arithmetic checker and a review-only comparison between a user-supplied scale and an explicitly supplied wall dimension. A global graph solver that propagates verified dimensions through identified geometric entities is not implemented. The future solver should treat each verified dimension as a constraint on a span between identified endpoints or references, use independent dimensions to detect contradictions, and estimate only genuinely shared calibration parameters.

Important safeguards:

- Never invent a missing dimension from pixel ratios.
- Do not force dimensions onto a preferred module (for example, rounding to 50 mm) without explicit evidence and user approval.
- Do not average contradictory dimensions into a plausible-looking value.
- Track under-constrained, over-constrained and inconsistent systems separately.
- Preserve uncertainty and provenance through every derived coordinate.
- If a drawing has local distortion or multiple scales, do not assume one global pixel-to-unit factor.

A global scale estimate may be useful as a diagnostic when several trusted dimension spans agree. It must not override explicit written dimensions or conceal local scan distortion.

### 6. Reconstruct editable 2D topology — manual geometry implemented, automatic reconstruction planned

Planline supports manual wall/room drawing and a first automatic wall-edge draft. The draft stage turns each clearly axis-aligned detected wall region into two parallel edge lines only after at least one horizontal and one vertical dimension have been explicitly transcribed, verified and associated with the correct wall pair. It retains source detection IDs and per-axis scale provenance. It does not infer connected topology, wall junctions, openings or closed room boundaries. Future reconstruction must preserve links back to source pixels and detection records. Geometric cleanup must not invent a closing wall merely to make a polygon valid.

### 7. Gate DXF export — draft wall-edge export implemented, verified measured export planned

The DXF exporter accepts manual wall segments, room polygons and the explicit dimension-driven wall-face draft. Draft wall faces are emitted on `DETECTED_WALL_DRAFT`, manual walls on `WALLS`, and rooms on `ROOMS`. The draft uses separate X/Y scales from confirmed dimensions and is labelled as draft geometry; it is not a certified measured drawing. The generation endpoint blocks missing axes, unsupported/ambiguous dimension text, associations that no longer match the source candidate geometry, and conflicting same-axis measurements. Full measured export still needs a topology/constraint solver, wall junction and opening reconstruction, scan-distortion handling, and an independent validation gate.

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

The legacy main.py pipeline is not ready to be called from the web API as-is. It remains in Git for research, but its retired scripts and digit-only checkpoint are excluded from the Windows installer source archive:

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

OCR Studio now provides verified full-string crop labels, and the Drawing workspace can run a local PaddleOCR recogniser on selected dimension crops. Use source-/writer-separated held-out labels to compare recognisers; a completed training run is not evidence of accuracy on real floor plans.

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

Keep heavyweight OCR/training dependencies isolated from the core application environment. The Windows installer provisions the optional local OCR runtime separately. Continue with reproducible benchmarks on representative, held-out architectural scans; do not assume generic handwriting scores transfer to dimension notation.

### Floor-plan parsing challenges

The open-access paper *Automatic structural scene digitalization* (2017) describes common issues in raster floor-plan parsing: dimension leaders being confused with walls, backgrounds containing grids/patterns, variable text fonts and orientations, text touching graphics, and vectorisation failures at junctions.

Reference: https://pmc.ncbi.nlm.nih.gov/articles/PMC5693441/

### Upload handling and privacy boundary

FastAPI documents `UploadFile` as a spooled file: data can remain in memory up to a threshold and roll over to disk-backed temporary storage for larger multipart parts. Starlette also documents that uploaded files are spooled to temporary storage. Planline's 25 MB endpoint check happens after multipart parsing, so it bounds the application read/decode step but does not prevent the parser from receiving and temporarily spooling an oversized upload first. The API now checks the parsed `UploadFile.size` before copying it into the application byte buffer, then closes it. This is not equivalent to a strict pre-parser request-body limit.

References:
- FastAPI, [Request Files](https://fastapi.tiangolo.com/tutorial/request-files/) — describes the spooled upload implementation and disk rollover.
- Starlette, [Requests](https://www.starlette.dev/requests/) — documents multipart file spooling and parser limits.

For sensitive drawings, configure and monitor the server/container temporary directory, apply a request-body limit at the reverse proxy or ASGI boundary, and review logs and browser caching. Do not describe the current implementation as memory-only.

## OCR dataset, training and evaluation status

Planline now has a local OCR data workflow; this section replaces the earlier “research first, no training yet” description. The current tools prepare, curate, split, train and evaluate recognition datasets, but dataset tooling is not a substitute for a representative benchmark.

Implemented capabilities:

1. **Verified capture:** Drawing review can save an individually verified full-string dimension crop to a selected local dataset. OCR Studio also supports manual crop creation and exact transcription.
2. **Dataset curation:** `planline.dataset` exports verified crops from review JSON or imports manually cropped images through a CSV manifest. It records source and optional writer grouping, checks image limits and checksums, and creates grouped train/validation/test splits.
3. **Quality audit:** `planline.ocr_quality` reports duplicate images, conflicting labels, suspicious transcription formats, character coverage, source/writer representation and split leakage.
4. **Fine-tuning workflow:** OCR Studio can prepare data and monitor local PaddleOCR PP-OCRv5 mobile/server recognition training jobs using matching pretrained checkpoints and a local PaddleOCR source checkout.
5. **Held-out evaluation:** The benchmark tooling compares raw recogniser predictions with verified labels and reports exact-string accuracy and character error rate, with breakdowns by text style where available.

Important limits:

- Training requires a compatible local PaddlePaddle environment, the matching PaddleOCR source/configuration and a compatible pretrained checkpoint. The installer provisions these assets in its private environment; the runtime remains separate from the core API dependencies.
- Training success does not demonstrate engineering accuracy. A useful test set must contain independent real scans and represent printed/handwritten, rotated, faded, skewed, compressed and overlapping dimension strings.
- Split by original drawing and writer, not by individual crop, so near-duplicate handwriting and drawing styles cannot leak between train, validation and test.
- Record dataset provenance, consent/rights, allowed use and redistribution status. Keep customer or otherwise sensitive scans out of public training data unless the rights and privacy basis are explicit.
- Keep machine-generated text unverified. Only a human-confirmed complete string may be used as a trusted input to downstream dimension checks.

A clean dataset-quality report is only a data-hygiene check. It does not prove that the data is large, balanced or representative enough to train a reliable recogniser.

## Acceptance criteria before relying on reconstructed geometry

1. **Ingest:** correct dimensions/orientation for raster images; clear PDF page handling; reject malformed and oversized inputs.
2. **Detection:** per-class precision/recall on held-out drawings, with results stratified by scan quality and drafting style.
3. **OCR:** exact full-string accuracy, character error rate, unit/decimal parsing accuracy, and confidence calibration; report handwritten and printed subsets separately.
4. **Association:** correct text-to-dimension-line and dimension-line-to-span matching; measure both top-1 accuracy and reviewer correction rate.
5. **Constraints:** recover known dimensions from synthetic plans; detect inconsistent and under-constrained cases; never substitute pixel ratios for missing written values.
6. **Geometry:** endpoint/junction error, topology/connectivity accuracy, and dimension residuals in physical units.
7. **DXF:** open the exported file in at least one independent CAD reader and verify units, layers, coordinates and entity counts.
8. **Human review:** every uncertain or conflicting item must be visible, editable and traceable to its source region.

## Immediate engineering backlog

### Completed foundations

- [x] Connect the browser Drawing workspace to the detector API.
- [x] Add candidate-region review, class filtering, selection, zoom and confidence-threshold control.
- [x] Add versioned candidate-review JSON export and a schema contract.
- [x] Add manual dimension transcription with style and verification metadata.
- [x] Automatically run local PaddleOCR on detected dimension crops when the inference runtime is available; retain manual verification.
- [x] Add explicit-unit dimension parsing that keeps missing-unit and ambiguous values unresolved.
- [x] Add reviewable text-to-dimension-line and dimension-line-to-wall-gap candidate association.
- [x] Add a manual decimal dimension-chain checker with explicit verification and tolerance states.
- [x] Add a review-only wall-dimension comparison; it never changes geometry.
- [x] Add explicit multi-page PDF page selection and source-page provenance.
- [x] Add portable `.planline` save/open with local user-controlled storage.
- [x] Add editable manual wall segments, room polygons, endpoint/corner editing and optional snapping.
- [x] Add SVG and DXF export for manual geometry, plus a separate DXF layer for dimension-constrained wall-face drafts using confirmed X/Y scales.
- [x] Add an OCR crop curator, manifest validation, source/writer-grouped splits and a dataset-quality audit.
- [x] Add local PaddleOCR fine-tuning job orchestration and held-out recogniser benchmarking.
- [x] Add browser smoke coverage for zoomed overlay alignment and a narrow mobile viewport.

### Next engineering priorities

- [ ] Run the real detector weights against representative older scans and record per-class precision/recall.
- [ ] Compare full-frame YOLO inference with overlapping multi-scale tiles on a held-out scan set before changing defaults.
- [ ] Audit the legacy digit classifier on held-out scans; do not integrate integer-only output as dimension OCR.
- [ ] Improve OCR evaluation coverage for faint, rotated, handwritten and overlapping complete dimension strings.
- [ ] Validate source-/writer-group separation across all OCR import and training paths; keep the test split untouched during model selection.
- [ ] Evaluate association top-1 accuracy, ambiguity rejection and reviewer correction rate on annotated real plans.
- [ ] Introduce a typed intermediate representation for detections, OCR observations, associations, constraints and provenance.
- [ ] Implement a global constraint solver that can identify under-constrained, over-constrained and inconsistent dimension systems without inventing measurements.
- [ ] Benchmark reversible deskew/dewarp and map transformed detections back to original source coordinates.
- [ ] Reconstruct wall/opening topology from reviewed source evidence and verified constraints; do not infer closure solely to make polygons valid.
- [ ] Extend the wall-face draft into connected wall topology with validated junctions, rooms and openings; retain unit/layer/provenance validation before any certified measured export.
- [ ] Manually inspect drawing, OCR and architecture pages at desktop/mobile sizes and verify PDF preview behaviour on representative files.
- [ ] Keep OCR training datasets rights-cleared, source-/writer-separated and outside the application repository by default.


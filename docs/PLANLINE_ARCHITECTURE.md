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
- PDF handling rasterises page one only.
- The existing YOLO weights detect candidate `wall`, `dimension_line`, and `dimension_value` regions.
- The UI displays the preview, candidate boxes, class counts, detector scores, filtering, and selected-box highlighting.
- The application does not intentionally save source drawings as project files; multipart parsing may spool larger uploads to temporary storage. No measured DXF is emitted.
- OCR, dimension association, calibration, topology reconstruction and measured DXF export are not part of this web workflow.

### Detection resolution risk

The current API sends the complete source image to YOLO with `imgsz=640`. On a large scanned sheet, small dimension text and thin annotation features can be reduced to only a few pixels before detection. The bounded 1600-pixel browser preview does not change the inference input; it is only for display.

The 2026 *Buildings* study uses density-adaptive overlapping crops because a single fixed resize can lose small targets in large drawings. Its reported crop sizes and performance are specific to its own dataset and model and must not be copied as Planline defaults without testing.

Planned approach:

- Benchmark full-frame inference against overlapping tile inference on the same held-out source drawings.
- Preserve each crop's offset and map every detection back to original source-image coordinates.
- Merge overlapping detections with class-aware NMS, and measure duplicate and missed detections at tile boundaries.
- Compare several crop sizes and overlap ratios, including crowded dimension bands and sparse plan regions.
- Keep the original full-resolution scan as the source of truth; never use the resized preview as the measurement coordinate system.

Do not enable tiled inference by assumption alone: the current detector was trained on a small simplified-plan dataset, and higher-resolution crops cannot compensate for a domain mismatch.

The API tests use a fake detector. They do not establish the real model's accuracy or prove that it works on representative scans. The real-weight smoke test and browser visual test remain separate acceptance tasks.

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
- The legacy dataset creator does not append a final digit segment when a row ends while the segment is still open; samples at the right edge of a row can therefore be omitted. This should be fixed and covered by tests before regenerating training data.

The existing model can be retained as an **experimental candidate recognizer** for the narrow drawing style it was trained on, but it must not become the authoritative dimension parser. Before integration, extract pure functions into an import-safe module, return per-character alternatives and confidence, preserve raw crops and preprocessing provenance, and require human confirmation of the complete string. Do not feed its output directly into geometry or DXF export.

### OCR engine selection: practical direction

PaddleOCR is a reasonable local baseline to evaluate because it provides text detection and sequence recognition components and is used in recent architectural-drawing research. It is not a guaranteed solution: floor-plan text detection, vertical orientation, small text and overlap with dimension graphics remain domain-specific failure modes. A second baseline should be evaluated against the same held-out scans rather than selecting an engine from generic document benchmarks.

Reference implementation: https://github.com/PaddlePaddle/PaddleOCR


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

Do not start another training run until the annotation schema, rights, evaluation split and target failure modes are agreed.

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
- [x] Document API setup and the current capability boundary.
- [ ] Run a real-weight smoke test with `yolo_floorplan.pt` and representative old scans.
- [ ] Compare full-frame YOLO inference with overlapping multi-scale tiles on held-out scans before changing the default detector path.
- [ ] Audit the legacy digit classifier on held-out scans; do not integrate its current integer output as dimension OCR.
- [x] Fix and test end-of-row digit segmentation in `dataset_creator.py` before generating any replacement dataset.
- [ ] Replace random crop-level validation with drawing-/writer-grouped held-out evaluation before trusting OCR accuracy.
- [ ] Benchmark at least two OCR baselines on complete dimension strings, including rotated, faded and handwritten samples.
- [ ] Add text-to-dimension-line and dimension-line-to-span association records with multiple candidates and human review.
- [ ] Evaluate metric correctness (dimension residuals and placement/topology errors), not only detection mAP or OCR character accuracy.
- [ ] Visually verify overlay alignment at desktop and mobile sizes, including resize and PDF preview.
- [ ] Add persistent project state only after defining privacy, retention and recovery requirements.
- [ ] Introduce a typed intermediate representation for detections, OCR observations, dimension associations and constraints.
- [ ] Add OCR as a reviewable stage; do not wire it directly to geometry generation.
- [ ] Add dimension association and constraint validation.
- [ ] Add manual geometry correction and measured DXF export only after validation gates exist.
- [ ] Revisit training only after rights-cleared data, annotation guidelines and a grouped evaluation split are ready.

const $ = (selector) => document.querySelector(selector);
const state = { file: null, objectUrl: null, result: null, previewUrl: null, detections: [], selectedId: null, activeFilter: "all", searchQuery: "", sortMode: "original", overlayVisible: true, resizeObserver: null, resizeHandler: null, controller: null, zoom: 1, calibration: { points: [], picking: false, applied: null } };

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function resetWorkspace() {
  if (state.controller) { state.controller.abort(); state.controller = null; }
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  if (state.resizeObserver) state.resizeObserver.disconnect();
  if (state.resizeHandler) window.removeEventListener("resize", state.resizeHandler);
  state.file = null; state.objectUrl = null; state.result = null; state.previewUrl = null;
  state.detections = []; state.selectedId = null; state.activeFilter = "all";
  state.overlayVisible = true; state.resizeObserver = null; state.resizeHandler = null; state.zoom = 1;
  state.searchQuery = ""; state.sortMode = "original";
  clearCalibration();
  if ($("#detectionSearch")) $("#detectionSearch").value = "";
  if ($("#detectionSort")) $("#detectionSort").value = "original";
  $("#fileInput").value = "";
  $("#fileCard").classList.add("hidden");
  $("#pdfPageControl").classList.add("hidden");
  $("#pdfPageNumber").value = "1";
  $("#pdfPageNumber").removeAttribute("max");
  $("#pdfPageCount").textContent = "Page count will be confirmed after analysis.";
  $("#dropzone").classList.remove("hidden");
  $("#analyzeButton").disabled = true;
  $("#exportReview").disabled = true;
  $("#analyzeButton").innerHTML = 'Analyse drawing <span>→</span>';
  $("#detectStep").classList.remove("complete");
  $("#sourceState").textContent = "Waiting";
  $("#drawingTitle").textContent = "No drawing loaded";
  $("#viewTag").textContent = "EMPTY CANVAS";
  $("#previewImage").onload = null;
  $("#previewImage").onerror = null;
  $("#previewImage").classList.add("hidden");
  $("#previewImage").removeAttribute("src");
  $("#loader").classList.add("hidden");
  $("#overlay").classList.add("hidden");
  $("#overlayToggle").textContent = "Hide boxes";
  $("#zoomLevel").textContent = "100%";
  $("#canvasWrap").classList.remove("zoomed");
  $("#previewImage").style.width = "";
  $("#previewImage").style.height = "";
  $("#previewImage").style.maxWidth = "";
  $("#previewImage").style.maxHeight = "";
  $("#classFilter").value = "all";
  $("#emptyState").classList.remove("hidden");
  $("#emptyState").querySelector("strong").textContent = "Your drawing will appear here";
  $("#emptyState").querySelector("p").textContent = "Upload a scan or PDF to begin detection.";
  $("#imageDimensions").textContent = "No source dimensions";
  $("#detectionCount").textContent = "0 detected regions";
  $("#summary").classList.add("hidden");
  $("#detectionList").innerHTML = "";
  $("#selectedDetection").classList.add("hidden");
  $("#noDetectionMatches").classList.add("hidden");
  clearDimensionTextReview();
  $("#resultStatus").textContent = "NOT ANALYSED";
}

function setFile(file) {
  if (!file) return;
  const allowed = /\.(png|jpe?g|webp|tiff?)$/i.test(file.name) || /\.pdf$/i.test(file.name);
  if (!allowed) {
    resetWorkspace();
    return showNotice("Unsupported file type", "Choose a PNG, JPG, WEBP, TIFF or PDF drawing.");
  }
  if (file.size > 25 * 1024 * 1024) {
    resetWorkspace();
    return showNotice("File is too large", "The maximum upload size is 25 MB.");
  }
  if (state.controller) { state.controller.abort(); state.controller = null; }
  $("#loader").classList.add("hidden");
  $("#analyzeButton").innerHTML = 'Analyse drawing <span>→</span>';
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  if (state.resizeObserver) state.resizeObserver.disconnect();
  if (state.resizeHandler) window.removeEventListener("resize", state.resizeHandler);
  state.resizeObserver = null; state.resizeHandler = null;
  $("#previewImage").onload = null;
  $("#previewImage").onerror = null;
  state.file = file;
  state.objectUrl = URL.createObjectURL(file);
  state.result = null;
  state.previewUrl = null;
  clearCalibration();
  state.selectedId = null;
  state.detections = [];
  state.overlayVisible = true;
  state.zoom = 1;
  $("#exportReview").disabled = true;
  $("#overlayToggle").textContent = "Hide boxes";
  $("#zoomLevel").textContent = "100%";
  $("#canvasWrap").classList.remove("zoomed");
  $("#previewImage").style.width = "";
  $("#previewImage").style.height = "";
  $("#fileName").textContent = file.name;
  $("#fileMeta").textContent = formatBytes(file.size) + " · selected locally";
  const isPdf = /\.pdf$/i.test(file.name);
  $("#pdfPageControl").classList.toggle("hidden", !isPdf);
  $("#pdfPageNumber").value = "1";
  $("#pdfPageCount").textContent = "Page count will be confirmed after analysis.";
  $("#fileCard").classList.remove("hidden");
  $("#dropzone").classList.add("hidden");
  $("#analyzeButton").disabled = false;
  $("#sourceState").textContent = "Selected";
  $("#drawingTitle").textContent = file.name;
  $("#viewTag").textContent = "READY TO ANALYSE";
  $("#emptyState").classList.add("hidden");
  $("#previewImage").classList.add("hidden");
  $("#previewImage").removeAttribute("src");
  $("#overlay").classList.add("hidden");
  $("#classFilter").value = "all"; state.activeFilter = "all";
  state.searchQuery = ""; state.sortMode = "original";
  $("#detectionSearch").value = ""; $("#detectionSort").value = "original";
  $("#imageDimensions").textContent = "Waiting for analysis";
  $("#detectionCount").textContent = "0 detected regions";
  $("#resultStatus").textContent = "NOT ANALYSED";
  $("#summary").classList.add("hidden");
  $("#detectionList").innerHTML = "";
  $("#selectedDetection").classList.add("hidden");
  $("#noDetectionMatches").classList.add("hidden");
  clearDimensionTextReview();
  showNotice("Drawing ready", "Run local detection to locate candidate walls and dimension annotations. No measurements will be inferred.");
  if (file.type.startsWith("image/")) {
    const img = $("#previewImage");
    img.onload = applyImageScale;
    img.src = state.objectUrl;
    img.classList.remove("hidden");
    img.onerror = () => {
      img.classList.add("hidden");
      $("#emptyState").classList.remove("hidden");
      $("#emptyState").querySelector("strong").textContent = "Preview unavailable";
      $("#emptyState").querySelector("p").textContent = "The local API can still analyse this image format.";
    };
  }
}

function showNotice(title, message) {
  $("#notice").innerHTML = "";
  const strong = document.createElement("b");
  strong.textContent = title;
  const span = document.createElement("span");
  span.textContent = message;
  $("#notice").append(strong, span);
  $("#notice").classList.remove("hidden");
}

function applyImageScale() {
  const img = $("#previewImage");
  const wrap = $("#canvasWrap");
  $("#zoomLevel").textContent = Math.round(state.zoom * 100) + "%";
  if (!img.naturalWidth || !img.naturalHeight) return;
  const availableWidth = Math.max(120, wrap.clientWidth - 48);
  const fitScale = Math.min(1, availableWidth / img.naturalWidth, 590 / img.naturalHeight);
  const scale = fitScale * state.zoom;
  img.style.width = Math.max(1, Math.round(img.naturalWidth * scale)) + "px";
  img.style.height = Math.max(1, Math.round(img.naturalHeight * scale)) + "px";
  img.style.maxWidth = "none";
  img.style.maxHeight = "none";
  img.style.margin = state.zoom > 1 ? "0" : "0 auto";
  wrap.classList.toggle("zoomed", state.zoom > 1);
}

function drawDetections(previewUrl, detections, imageSize) {
  const img = $("#previewImage");
  const canvas = $("#overlay");
  const wrap = $("#canvasWrap");
  state.previewUrl = previewUrl;
  state.detections = detections;
  state.imageSize = imageSize;
  const paint = () => {
    if (!img.complete || !img.naturalWidth || img.classList.contains("hidden")) return;
    applyImageScale();
    const imageRect = img.getBoundingClientRect();
    const wrapRect = wrap.getBoundingClientRect();
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    canvas.style.width = imageRect.width + "px";
    canvas.style.height = imageRect.height + "px";
    canvas.style.maxWidth = "none";
    canvas.style.maxHeight = "none";
    canvas.style.left = (imageRect.left - wrapRect.left + wrap.scrollLeft) + "px";
    canvas.style.top = (imageRect.top - wrapRect.top + wrap.scrollTop) + "px";
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const sx = img.naturalWidth / imageSize.width;
    const sy = img.naturalHeight / imageSize.height;
    detections.forEach((d) => {
      if (state.activeFilter !== "all" && d.class_name !== state.activeFilter) return;
      const box = d.bbox;
      const selected = state.selectedId === d.id;
      ctx.strokeStyle = selected ? "#d34e3e" : d.class_name === "wall" ? "#287c56" : d.class_name === "dimension_value" ? "#c47734" : "#4778a8";
      ctx.lineWidth = selected ? Math.max(4, canvas.width / 450) : Math.max(2, canvas.width / 700);
      ctx.strokeRect(box.x1 * sx, box.y1 * sy, box.width * sx, box.height * sy);
    });
    if (state.calibration.points.length) {
      const points = state.calibration.points.map((point) => ({ x: point.x * sx, y: point.y * sy }));
      if (points.length === 2) {
        ctx.strokeStyle = "#0b8f67";
        ctx.lineWidth = Math.max(3, canvas.width / 500);
        ctx.setLineDash([10, 6]);
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        ctx.lineTo(points[1].x, points[1].y);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      points.forEach((point, index) => {
        ctx.beginPath();
        ctx.fillStyle = "#0b8f67";
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = Math.max(2, canvas.width / 700);
        ctx.arc(point.x, point.y, Math.max(7, canvas.width / 250), 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold " + Math.max(12, canvas.width / 90) + "px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(index + 1), point.x, point.y);
      });
    }
    canvas.classList.toggle("hidden", !state.overlayVisible);
  };
  img.onload = paint;
  if (img.src !== previewUrl) img.src = previewUrl;
  img.classList.remove("hidden");
  $("#emptyState").classList.add("hidden");
  if (img.complete) paint();
  if (state.resizeObserver) state.resizeObserver.disconnect();
  state.resizeObserver = new ResizeObserver(paint);
  state.resizeObserver.observe(img);
  if (state.resizeHandler) window.removeEventListener("resize", state.resizeHandler);
  state.resizeHandler = paint;
  window.addEventListener("resize", state.resizeHandler, { passive: true });
}
const CALIBRATION_UNIT_TO_MM = { mm: 1, cm: 10, m: 1000, in: 25.4, ft: 304.8 };

function clearCalibration() {
  state.calibration = { points: [], picking: false, applied: null };
  const status = $("#calibrationState");
  if (!status) return;
  status.textContent = "Not set";
  $("#calibrationPoints").textContent = "Point 1: not set · Point 2: not set";
  $("#calibrationResult").textContent = "No scale applied.";
  $("#startCalibration").disabled = !state.result;
  $("#startCalibration").textContent = "Pick two points";
  $("#applyCalibration").disabled = true;
  $("#clearCalibration").disabled = true;
  $("#previewImage").classList.remove("calibration-picking");
  if (state.result && state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function renderCalibrationStatus() {
  const points = state.calibration.points;
  $("#calibrationPoints").textContent = "Point 1: " +
    (points[0] ? Math.round(points[0].x) + ", " + Math.round(points[0].y) + " px" : "not set") +
    " · Point 2: " +
    (points[1] ? Math.round(points[1].x) + ", " + Math.round(points[1].y) + " px" : "not set");
  $("#startCalibration").disabled = !state.result;
  $("#startCalibration").textContent = state.calibration.picking ? "Click the drawing…" : "Pick two points";
  $("#applyCalibration").disabled = points.length !== 2;
  $("#clearCalibration").disabled = points.length === 0 && !state.calibration.applied;
  $("#calibrationState").textContent = state.calibration.applied ? "Applied" :
    state.calibration.picking ? "Picking points" : points.length ? "2 points ready" : "Not set";
  $("#previewImage").classList.toggle("calibration-picking", state.calibration.picking);
}

function startCalibration() {
  if (!state.result) return;
  state.calibration = { points: [], picking: true, applied: null };
  $("#calibrationResult").textContent = "Click the first point, then the second point on the drawing.";
  renderCalibrationStatus();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function addCalibrationPoint(event) {
  if (!state.calibration.picking || !state.result) return;
  const image = $("#previewImage");
  const rect = image.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const x = Math.max(0, Math.min(state.result.image.width,
    ((event.clientX - rect.left) / rect.width) * state.result.image.width));
  const y = Math.max(0, Math.min(state.result.image.height,
    ((event.clientY - rect.top) / rect.height) * state.result.image.height));
  state.calibration.points.push({ x, y });
  if (state.calibration.points.length >= 2) state.calibration.picking = false;
  renderCalibrationStatus();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
  if (state.calibration.points.length === 2) $("#calibrationResult").textContent =
    "Two points selected. Enter their known distance and apply the scale.";
}

function applyCalibration() {
  const points = state.calibration.points;
  const distance = Number($("#calibrationDistance").value);
  const unit = $("#calibrationUnit").value;
  if (points.length !== 2) return;
  if (!Number.isFinite(distance) || distance <= 0 || !CALIBRATION_UNIT_TO_MM[unit]) {
    $("#calibrationResult").textContent = "Enter a positive distance and choose a supported unit.";
    $("#calibrationDistance").focus();
    return;
  }
  const dx = points[1].x - points[0].x;
  const dy = points[1].y - points[0].y;
  const pixelDistance = Math.hypot(dx, dy);
  if (!Number.isFinite(pixelDistance) || pixelDistance < 1) {
    $("#calibrationResult").textContent = "The selected points are too close together. Pick two distinct points.";
    return;
  }
  const distanceMm = distance * CALIBRATION_UNIT_TO_MM[unit];
  if (!Number.isFinite(distanceMm) || distanceMm <= 0) {
    $("#calibrationResult").textContent = "That distance is outside the supported numeric range.";
    return;
  }
  state.calibration.applied = {
    method: "user_two_point_reference",
    points_px: points.map((point) => ({ x: Number(point.x.toFixed(2)), y: Number(point.y.toFixed(2)) })),
    pixel_distance: Number(pixelDistance.toFixed(3)),
    known_distance: distance,
    input_unit: unit,
    known_distance_mm: Number(distanceMm.toFixed(6)),
    pixels_per_mm: Number((pixelDistance / distanceMm).toFixed(9)),
    source_filename: state.file?.name || null,
    source_page_index: state.result?.source?.page_index ?? 0,
    status: "user_supplied_reference_not_geometry_validation"
  };
  $("#calibrationResult").textContent = pixelDistance.toFixed(1) + " px / " +
    distanceMm.toLocaleString(undefined, { maximumFractionDigits: 3 }) +
    " mm = " + state.calibration.applied.pixels_per_mm.toFixed(6) +
    " px/mm. User-supplied reference only.";
  renderCalibrationStatus();
}

$("#startCalibration").addEventListener("click", startCalibration);
$("#applyCalibration").addEventListener("click", applyCalibration);
$("#clearCalibration").addEventListener("click", clearCalibration);
$("#previewImage").addEventListener("click", addCalibrationPoint);

function renderResults(payload) {
  const detections = payload.detections || [];
  if (payload.source?.source_type === "pdf") {
    const pageNumber = Number(payload.source.page_index || 0) + 1;
    const pageCount = Number(payload.source.page_count || 1);
    $("#pdfPageControl").classList.remove("hidden");
    $("#pdfPageNumber").value = String(pageNumber);
    $("#pdfPageNumber").max = String(pageCount);
    $("#pdfPageCount").textContent = `Page ${pageNumber} of ${pageCount}`;
  } else {
    $("#pdfPageControl").classList.add("hidden");
  }
  $("#exportReview").disabled = false;
  $("#startCalibration").disabled = false;
  renderCalibrationStatus();
  $("#sourceState").textContent = "Analysed";
  $("#viewTag").textContent = "DETECTION OVERLAY";
  $("#imageDimensions").textContent = payload.image.width + " × " + payload.image.height + " px";
  $("#detectionCount").textContent = detections.length + " detected regions";
  $("#resultStatus").textContent = "DETECTION COMPLETE";
  $("#notice").classList.add("hidden");
  $("#summary").innerHTML = "";
  const counts = payload.counts || {};
  const classes = ["wall", "dimension_line", "dimension_value"];
  classes.forEach((name) => {
    const card = document.createElement("div");
    card.className = "summary-card";
    const value = document.createElement("strong");
    value.textContent = counts[name] || 0;
    const label = document.createElement("span");
    label.textContent = name.replaceAll("_", " ");
    card.append(value, label);
    $("#summary").append(card);
  });
  $("#summary").classList.remove("hidden");
  $("#detectionList").innerHTML = "";
  $("#selectedDetection").classList.add("hidden");
  $("#noDetectionMatches").classList.add("hidden");
  state.selectedId = null;
  detections.forEach((d) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "detection-row";
    row.setAttribute("aria-pressed", "false");
    row.addEventListener("click", () => { state.selectedId = d.id; renderDetectionRows(detections); drawDetections(state.previewUrl, detections, payload.image); });
    const id = document.createElement("span");
    id.className = "det-id";
    id.textContent = d.id;
    const name = document.createElement("span");
    name.className = "det-name";
    name.textContent = d.class_name.replaceAll("_", " ");
    const box = document.createElement("span");
    box.className = "det-box";
    box.textContent = Math.round(d.bbox.width) + " × " + Math.round(d.bbox.height) + " px";
    const confidence = document.createElement("span");
    confidence.className = "confidence";
    confidence.textContent = Math.round(d.confidence * 100) + "% score";
    row.append(id, name, box, confidence);
    row.dataset.className = d.class_name;
    row.dataset.detectionId = d.id;
    $("#detectionList").append(row);
  });
  renderDetectionRows(detections);
  renderDimensionTextReview(payload.dimension_regions || []);
  const notes = (payload.notes || []).join(" ");
  showNotice(detections.length ? "Detection finished — OCR has not run" : "No candidate regions detected", detections.length ? notes : "The model returned no boxes at its current confidence threshold. This does not prove that the drawing contains no walls or dimensions. " + notes);
  if (payload.source?.source_type === "pdf") {
    const pageNumber = Number(payload.source.page_index || 0) + 1;
    const pageCount = Number(payload.source.page_count || 1);
    showNotice(`PDF page ${pageNumber} of ${pageCount} analysed`, notes + " Select another page above and analyse it without uploading the PDF again.");
  }
  if (payload.preview_data_url) drawDetections(payload.preview_data_url, detections, payload.image);
}

function clearDimensionTextReview() {
  const panel = $("#dimensionTextReview");
  panel.classList.add("hidden");
  panel.open = false;
  $("#dimensionTextItems").replaceChildren();
}

function renderDimensionTextReview(regions) {
  const panel = $("#dimensionTextReview");
  const container = $("#dimensionTextItems");
  container.replaceChildren();
  if (!regions.length) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  panel.open = true;
  regions.forEach((region, index) => {
    const row = document.createElement("article");
    row.className = "dimension-text-item";
    row.dataset.detectionId = region.id;

    if (region.crop_data_url) {
      const crop = document.createElement("img");
      crop.className = "dimension-text-crop";
      crop.src = region.crop_data_url;
      crop.alt = "Original-resolution crop for dimension candidate " + (index + 1);
      row.append(crop);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "dimension-text-crop-placeholder";
      placeholder.textContent = "Crop unavailable for this candidate";
      row.append(placeholder);
    }

    const fields = document.createElement("div");
    fields.className = "dimension-text-fields";
    const meta = document.createElement("span");
    meta.className = "dimension-text-meta";
    meta.textContent = "Candidate " + (index + 1) + " · " +
      Math.round(region.confidence * 100) + "% detector score · " + region.id;

    const textLabel = document.createElement("label");
    textLabel.textContent = "Transcribe exactly as written";
    const textInput = document.createElement("input");
    textInput.className = "dimension-text-value";
    textInput.type = "text";
    textInput.autocomplete = "off";
    textInput.spellcheck = false;
    textInput.placeholder = "Enter the visible text";
    textLabel.append(textInput);

    const styleLabel = document.createElement("label");
    styleLabel.textContent = "Writing style";
    const styleSelect = document.createElement("select");
    styleSelect.className = "dimension-text-style";
    [
      ["unknown", "Not classified"],
      ["printed", "Printed"],
      ["handwritten", "Handwritten"],
      ["unclear", "Unclear / mixed"]
    ].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      styleSelect.append(option);
    });
    styleLabel.append(styleSelect);

    const verifiedLabel = document.createElement("label");
    verifiedLabel.className = "dimension-text-verified";
    const verifiedInput = document.createElement("input");
    verifiedInput.className = "dimension-text-verified-input";
    verifiedInput.type = "checkbox";
    verifiedLabel.append(verifiedInput, document.createTextNode(" I checked this transcription"));

    const association = region.association || { status: "unmatched", candidate_lines: [] };
    const associationPanel = document.createElement("section");
    associationPanel.className = "dimension-association";
    const associationHeading = document.createElement("strong");
    associationHeading.textContent = "Geometric association · review required";
    const associationHelp = document.createElement("p");
    associationHelp.className = "association-help";
    associationHelp.textContent = association.status === "unmatched"
      ? "No compatible dimension-line candidate was found. Do not guess a connection."
      : "Choose the dimension line and the two bounding walls that this value describes. Scores rank box geometry; they are not probabilities.";
    const lineLabel = document.createElement("label");
    lineLabel.textContent = "Dimension line candidate";
    const lineSelect = document.createElement("select");
    lineSelect.className = "dimension-line-select";
    const linePlaceholder = document.createElement("option");
    linePlaceholder.value = "";
    linePlaceholder.textContent = "Choose a dimension line…";
    lineSelect.append(linePlaceholder);
    (association.candidate_lines || []).forEach((candidate) => {
      const option = document.createElement("option");
      option.value = candidate.dimension_line_id;
      option.textContent = candidate.dimension_line_id + " · " + candidate.orientation +
        " · rank " + Math.round((candidate.assignment_score ?? candidate.score) * 100);
      lineSelect.append(option);
    });
    lineLabel.append(lineSelect);

    const spanLabel = document.createElement("label");
    spanLabel.textContent = "Measured wall span candidate";
    const spanSelect = document.createElement("select");
    spanSelect.className = "dimension-wall-span-select";
    spanSelect.disabled = true;
    const spanPlaceholder = document.createElement("option");
    spanPlaceholder.value = "";
    spanPlaceholder.textContent = "Choose a wall pair…";
    spanSelect.append(spanPlaceholder);
    spanLabel.append(spanSelect);

    const associationVerifiedLabel = document.createElement("label");
    associationVerifiedLabel.className = "dimension-association-verified";
    const associationVerified = document.createElement("input");
    associationVerified.className = "dimension-association-verified-input";
    associationVerified.type = "checkbox";
    associationVerified.disabled = true;
    associationVerifiedLabel.append(
      associationVerified,
      document.createTextNode(" I checked this line and wall pair against the drawing")
    );

    function updateWallSpanOptions() {
      spanSelect.replaceChildren();
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Choose a wall pair…";
      spanSelect.append(placeholder);
      const selectedLine = (association.candidate_lines || []).find(
        (candidate) => candidate.dimension_line_id === lineSelect.value
      );
      (selectedLine?.wall_spans || []).forEach((span, spanIndex) => {
        const option = document.createElement("option");
        option.value = String(spanIndex);
        const globalHint = span.globally_assigned
          ? " · global gap suggestion"
          : span.globally_assigned_to
            ? " · gap suggested for " + span.globally_assigned_to
            : "";
        option.textContent = span.wall_ids.join(" ↔ ") + " · " +
          Math.round(span.span_px) + " px · rank " +
          Math.round((span.assignment_score ?? span.score) * 100) + globalHint;
        spanSelect.append(option);
      });
      spanSelect.disabled = !selectedLine || !(selectedLine.wall_spans || []).length;
      associationVerified.checked = false;
      associationVerified.disabled = true;
      associationHelp.textContent = !selectedLine
        ? "Choose a dimension-line candidate. One detected line may serve multiple labels in a chained dimension."
        : !(selectedLine.wall_spans || []).length
          ? "This line has no viable wall-gap candidate. Leave the association unresolved."
          : "Choose the wall gap that this dimension measures. The global recommendation is advisory and does not select anything automatically.";
    }
    lineSelect.addEventListener("change", updateWallSpanOptions);
    spanSelect.addEventListener("change", () => {
      associationVerified.checked = false;
      associationVerified.disabled = !lineSelect.value || !spanSelect.value;
      const selectedLine = (association.candidate_lines || []).find(
        (candidate) => candidate.dimension_line_id === lineSelect.value
      );
      const selectedSpan = selectedLine?.wall_spans?.[Number(spanSelect.value)];
      associationHelp.textContent = !selectedSpan
        ? "Choose a wall gap. A dimension-line detection may be shared by several labels in a chain."
        : selectedSpan.globally_assigned
          ? "This is the globally preferred one-to-one wall-gap match. Check the drawing and explicitly confirm."
          : selectedSpan.globally_assigned_to
            ? "This wall gap is globally preferred for another dimension label. Selecting it here is an override; verify carefully."
            : "Check that this wall pair describes the written dimension, then explicitly confirm.";
    });

    associationPanel.append(associationHeading, associationHelp, lineLabel, spanLabel, associationVerifiedLabel);
    fields.append(meta, textLabel, styleLabel, verifiedLabel, associationPanel);
    row.append(fields);
    container.append(row);
  });
}

function renderDetectionRows(detections) {
  const container = $("#detectionList");
  const rows = [...container.querySelectorAll(".detection-row")];
  const byId = new Map((detections || []).map((item) => [item.id, item]));
  const query = state.searchQuery.trim().toLowerCase();
  rows.forEach((row) => {
    const item = byId.get(row.dataset.detectionId);
    const matchesClass = state.activeFilter === "all" || row.dataset.className === state.activeFilter;
    const searchable = [row.dataset.detectionId, row.dataset.className].join(" ").toLowerCase();
    const matchesQuery = !query || searchable.includes(query);
    row.classList.toggle("hidden", !(matchesClass && matchesQuery));
    const selected = row.dataset.detectionId === state.selectedId;
    row.classList.toggle("selected", selected);
    row.setAttribute("aria-pressed", selected ? "true" : "false");
    if (item) row.dataset.confidence = String(item.confidence || 0);
  });
  const sorted = [...rows].sort((a, b) => {
    if (state.sortMode === "confidence") return Number(b.dataset.confidence) - Number(a.dataset.confidence);
    if (state.sortMode === "size") {
      const aa = byId.get(a.dataset.detectionId)?.bbox || {};
      const bb = byId.get(b.dataset.detectionId)?.bbox || {};
      return (Number(bb.width) * Number(bb.height)) - (Number(aa.width) * Number(aa.height));
    }
    return (detections || []).findIndex((item) => item.id === a.dataset.detectionId) -
      (detections || []).findIndex((item) => item.id === b.dataset.detectionId);
  });
  sorted.forEach((row) => container.append(row));
  const visible = rows.filter((row) => !row.classList.contains("hidden")).length;
  if (state.result) $("#detectionCount").textContent = visible + " of " + rows.length + " regions shown";
  const selected = byId.get(state.selectedId);
  const inspector = $("#selectedDetection");
  if (selected) {
    $("#selectedDetectionName").textContent = selected.class_name.replaceAll("_", " ") + " · " + selected.id;
    $("#selectedDetectionScore").textContent = Math.round(selected.confidence * 100) + "%";
    $("#selectedDetectionPosition").textContent = Math.round(selected.bbox.x1) + ", " + Math.round(selected.bbox.y1) + " px";
    $("#selectedDetectionSize").textContent = Math.round(selected.bbox.width) + " × " + Math.round(selected.bbox.height) + " px";
    inspector.classList.remove("hidden");
  } else {
    inspector.classList.add("hidden");
  }
  $("#noDetectionMatches").classList.toggle("hidden", visible !== 0 || rows.length === 0);
}

$("#classFilter").addEventListener("change", (event) => {
  state.activeFilter = event.target.value;
  renderDetectionRows(state.detections || []);
  if (state.result) drawDetections(state.previewUrl, state.detections, state.result.image);
});
$("#detectionSearch").addEventListener("input", (event) => {
  state.searchQuery = event.target.value;
  renderDetectionRows(state.detections || []);
});
$("#detectionSort").addEventListener("change", (event) => {
  state.sortMode = event.target.value;
  renderDetectionRows(state.detections || []);
});
function setZoom(value) {
  state.zoom = Math.max(0.5, Math.min(3, value));
  applyImageScale();
  if (state.result && state.previewUrl) {
    drawDetections(state.previewUrl, state.detections, state.result.image);
  }
}
$("#zoomIn").addEventListener("click", () => setZoom(state.zoom + 0.25));
$("#zoomOut").addEventListener("click", () => setZoom(state.zoom - 0.25));
$("#fitView").addEventListener("click", () => setZoom(1));

$("#overlayToggle").addEventListener("click", () => {
  state.overlayVisible = !state.overlayVisible;
  $("#overlayToggle").textContent = state.overlayVisible ? "Hide boxes" : "Show boxes";
  $("#overlay").classList.toggle("hidden", !state.overlayVisible);
});

async function analyse() {
  if (!state.file) return;
  const file = state.file;
  const isPdf = /\.pdf$/i.test(file.name);
  const pageNumber = Number($("#pdfPageNumber").value);
  if (isPdf && (!Number.isInteger(pageNumber) || pageNumber < 1)) {
    showNotice("Choose a valid PDF page", "Enter a whole page number starting at 1.");
    $("#pdfPageNumber").focus();
    return;
  }
  const knownPageCount = Number($("#pdfPageNumber").max || 0);
  if (isPdf && knownPageCount && pageNumber > knownPageCount) {
    showNotice("Page is outside this PDF", `This PDF has ${knownPageCount} pages. Choose a page from 1 to ${knownPageCount}.`);
    $("#pdfPageNumber").focus();
    return;
  }
  const controller = new AbortController();
  state.controller = controller;
  const button = $("#analyzeButton");
  button.disabled = true;
  button.textContent = "Analysing…";
  // Do not leave results from an earlier run visible if this run fails.
  state.result = null; state.previewUrl = null; state.detections = []; state.selectedId = null;
  $("#exportReview").disabled = true;
  $("#overlay").classList.add("hidden");
  $("#summary").classList.add("hidden");
  $("#detectionList").innerHTML = "";
  $("#selectedDetection").classList.add("hidden");
  $("#noDetectionMatches").classList.add("hidden");
  clearDimensionTextReview();
  $("#resultStatus").textContent = "ANALYSING";
  $("#detectionCount").textContent = "Analysis in progress";
  showNotice("Analysis in progress", "The previous result has been cleared. Candidate detections will appear when this run finishes.");
  $("#loader").classList.remove("hidden");
  $("#detectStep").classList.remove("complete");
  try {
    const form = new FormData();
    form.append("file", file);
    form.append("confidence_threshold", $("#confidenceThreshold").value);
    form.append("page_index", String(isPdf ? pageNumber - 1 : 0));
    const response = await fetch("/api/analyze", { method: "POST", body: form, signal: controller.signal });
    const payload = await response.json().catch(() => ({}));
    if (state.controller !== controller) return;
    if (!response.ok) throw new Error(payload.detail || "Analysis failed (HTTP " + response.status + ").");
    state.result = payload;
    $("#detectStep").classList.add("complete");
    renderResults(payload);
  } catch (error) {
    if (error.name !== "AbortError" && state.controller === controller) {
      $("#detectStep").classList.remove("complete");
      showNotice("Analysis could not be completed", error.message || "Check that the local API is running.");
      $("#resultStatus").textContent = "ANALYSIS FAILED";
    }
  } finally {
    if (state.controller === controller) {
      state.controller = null;
      $("#loader").classList.add("hidden");
      button.disabled = false;
      button.innerHTML = 'Analyse again <span>→</span>';
    }
  }
}

function exportReviewJson() {
  if (!state.result) return;
  const safeStem = (state.file?.name || "drawing")
    .replace(/\.[^.]+$/, "")
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .slice(0, 60) || "drawing";
  const result = state.result;
  const review = {
    schema_version: "planline-detection-review/v1",
    generated_at: new Date().toISOString(),
    source: {
      filename: state.file?.name || null,
      image_width_px: result.image.width,
      image_height_px: result.image.height
    },
    calibration: state.calibration.applied ? { ...state.calibration.applied } : null,
    analysis: {
      model: "yolo_floorplan.pt",
      confidence_threshold: result.confidence_threshold ?? 0.25,
      status: "candidate_detection_only",
      coordinate_system: "pixel coordinates; origin at top-left; x increases right; y increases down"
    },
    counts: {
      wall: result.counts?.wall || 0,
      dimension_line: result.counts?.dimension_line || 0,
      dimension_value: result.counts?.dimension_value || 0
    },
    detections: (result.detections || []).map((detection) => ({
      id: detection.id,
      class_name: detection.class_name,
      confidence: detection.confidence,
      bbox: detection.bbox,
      centre: detection.centre
    })),
    manual_dimension_text_review: (result.dimension_regions || []).map((region, index) => {
      const textInputs = document.querySelectorAll(".dimension-text-value");
      const verifiedInputs = document.querySelectorAll(".dimension-text-verified-input");
      const association = region.association || { status: "unmatched", candidate_lines: [] };
      const lineSelect = document.querySelectorAll(".dimension-line-select")[index];
      const spanSelect = document.querySelectorAll(".dimension-wall-span-select")[index];
      const associationVerified = document.querySelectorAll(".dimension-association-verified-input")[index];
      const selectedLine = (association.candidate_lines || []).find(
        (candidate) => candidate.dimension_line_id === lineSelect?.value
      );
      const selectedSpan = spanSelect?.value !== ""
        ? selectedLine?.wall_spans?.[Number(spanSelect.value)]
        : null;
      return {
        detection_id: region.id,
        raw_text: textInputs[index]?.value || "",
        text_style: document.querySelectorAll(".dimension-text-style")[index]?.value || "unknown",
        verified: verifiedInputs[index]?.checked || false,
        detector_confidence: region.confidence,
        bbox: region.bbox,
        crop_bbox: region.crop_bbox || null,
        association: {
          status: association.status || "unmatched",
          dimension_line_id: selectedLine?.dimension_line_id || null,
          wall_ids: selectedSpan?.wall_ids || [],
          wall_span_px: selectedSpan?.span_px ?? null,
          confirmed: associationVerified?.checked || false,
          candidate_lines: (association.candidate_lines || []).map((candidate) => ({
            dimension_line_id: candidate.dimension_line_id,
            orientation: candidate.orientation,
            score: candidate.score,
            assignment_score: candidate.assignment_score,
            wall_span_status: candidate.wall_span_status,
            wall_spans: (candidate.wall_spans || []).map((span) => ({
              wall_ids: span.wall_ids,
              orientation: span.orientation,
              method: span.method,
              span_px: span.span_px,
              score: span.score,
              assignment_score: span.assignment_score,
              globally_assigned: span.globally_assigned,
              globally_assigned_to: span.globally_assigned_to,
              gap_center_px: span.gap_center_px,
              text_center_offset_px: span.text_center_offset_px,
              line_center_offset_px: span.line_center_offset_px,
              endpoint_residual_px: span.endpoint_residual_px,
              perpendicular_offset_px: span.perpendicular_offset_px,
              intervening_wall_count: span.intervening_wall_count
            }))
          }))
        }
      };
    }),
    limitations: [
      "No OCR has been performed; manual transcription entries are user-entered and not machine-verified.",
      "Geometric association suggestions are axis-aligned box hypotheses; only explicitly confirmed line and wall-pair selections are marked as reviewed.",
      state.calibration.applied
        ? "A two-point scale was supplied by the user and recorded as pixels per millimetre; it is not an independently verified measurement or validated geometry."
        : "No pixel-to-unit scale or measured geometry has been inferred.",
      "Bounding boxes are detector candidates, not measured wall geometry.",
      "No measured DXF geometry is included."
    ]
  };
  const blob = new Blob([JSON.stringify(review, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = safeStem + "-planline-review.json";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("#exportReview").addEventListener("click", exportReviewJson);
$("#confidenceThreshold").addEventListener("input", () => {
  $("#confidenceValue").textContent = Number($("#confidenceThreshold").value).toFixed(2);
});

function renumberChainRows() {
  const rows = [...$("#chainSegments").querySelectorAll(".chain-segment-row")];
  rows.forEach((row, index) => {
    const label = row.querySelector(".chain-value-label");
    label.childNodes[0].textContent = "Segment " + (index + 1) + " ";
    const remove = row.querySelector(".remove-segment");
    remove.disabled = rows.length === 1;
    remove.setAttribute("aria-label", "Remove segment " + (index + 1));
  });
}

function addChainSegment() {
  const row = document.createElement("div");
  row.className = "chain-segment-row";
  const valueLabel = document.createElement("label");
  valueLabel.className = "chain-value-label";
  valueLabel.append(document.createTextNode("Segment "));
  const value = document.createElement("input");
  value.className = "segment-value";
  value.type = "number";
  value.min = "0";
  value.step = "any";
  value.inputMode = "decimal";
  value.placeholder = "Enter value";
  valueLabel.append(value);

  const verifyLabel = document.createElement("label");
  verifyLabel.className = "chain-verify-label";
  const verified = document.createElement("input");
  verified.className = "segment-verified";
  verified.type = "checkbox";
  verifyLabel.append(verified, document.createTextNode(" Verified"));

  const remove = document.createElement("button");
  remove.className = "remove-segment toolbar-button";
  remove.type = "button";
  remove.textContent = "×";
  row.append(valueLabel, verifyLabel, remove);
  $("#chainSegments").append(row);
  renumberChainRows();
  value.focus();
}

function renderChainResult(result) {
  const box = $("#chainResult");
  box.replaceChildren();
  box.dataset.status = result.status;
  box.classList.remove("hidden");
  const titles = {
    matches: "Chain matches within the specified tolerance",
    mismatch: "Verified dimensions do not add up",
    needs_review: "Review is still required",
    unresolved: "The chain is incomplete"
  };
  const heading = document.createElement("strong");
  heading.textContent = titles[result.status] || "Dimension-chain result";
  box.append(heading);

  [
    ["Segment total", result.segment_total],
    ["Overall value", result.overall_value],
    ["Difference", result.difference],
    ["Tolerance", result.tolerance]
  ].forEach(([label, value]) => {
    const line = document.createElement("p");
    line.textContent = label + ": " + (value === null ? "—" : value) + " " + result.unit;
    box.append(line);
  });

  if (result.unresolved_indices.length) {
    const line = document.createElement("p");
    line.textContent = "Missing segments: " + result.unresolved_indices.map((index) => index + 1).join(", ");
    box.append(line);
  }
  if (result.overall_unresolved) {
    const line = document.createElement("p");
    line.textContent = "Overall dimension is missing.";
    box.append(line);
  }
  if (result.unverified_indices.length || !result.overall_verified) {
    const line = document.createElement("p");
    const segments = result.unverified_indices.map((index) => index + 1);
    line.textContent = "Unverified: " + (segments.length ? "segments " + segments.join(", ") : "") +
      (!result.overall_verified ? (segments.length ? "; " : "") + "overall dimension" : "");
    box.append(line);
  }
}

async function checkDimensionChain() {
  const rows = [...$("#chainSegments").querySelectorAll(".chain-segment-row")];
  const payload = {
    segment_values: rows.map((row) => row.querySelector(".segment-value").value.trim() || null),
    segment_verified: rows.map((row) => row.querySelector(".segment-verified").checked),
    overall_value: $("#overallValue").value.trim() || null,
    overall_verified: $("#overallVerified").checked,
    unit: $("#chainUnit").value,
    tolerance: $("#chainTolerance").value.trim() || "0"
  };
  const box = $("#chainResult");
  box.classList.remove("hidden");
  box.removeAttribute("data-status");
  box.textContent = "Checking the supplied values…";
  try {
    const response = await fetch("/api/validate-dimension-chain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(result.detail)
        ? result.detail.map((item) => item.msg).join("; ")
        : result.detail || "The dimension chain could not be checked.";
      throw new Error(detail);
    }
    renderChainResult(result);
  } catch (error) {
    box.dataset.status = "unresolved";
    box.textContent = "Could not check the dimension chain: " + (error.message || "API unavailable");
  }
}

$("#addSegment").addEventListener("click", addChainSegment);
$("#chainSegments").addEventListener("click", (event) => {
  const button = event.target.closest(".remove-segment");
  if (!button || button.disabled) return;
  button.closest(".chain-segment-row").remove();
  renumberChainRows();
});
$("#checkChain").addEventListener("click", checkDimensionChain);
renumberChainRows();

const themeButton = $("#themeToggle");
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const dark = theme === "dark";
  themeButton.textContent = dark ? "Light mode" : "Dark mode";
  themeButton.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  try { localStorage.setItem("planline-theme", theme); } catch (_) {}
}
let savedTheme = "light";
try { savedTheme = localStorage.getItem("planline-theme") || "light"; } catch (_) {}
setTheme(savedTheme === "dark" ? "dark" : "light");
themeButton.addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));

document.addEventListener("keydown", (event) => {
  const command = event.ctrlKey || event.metaKey;
  const target = event.target;
  const typing = target && (target.matches("input, textarea, select") || target.isContentEditable);
  if (command && event.key.toLowerCase() === "o") {
    event.preventDefault();
    $("#fileInput").click();
  } else if (command && event.key === "Enter" && !$("#analyzeButton").disabled) {
    event.preventDefault();
    analyse();
  } else if (event.key === "Escape" && !typing && state.file) {
    resetWorkspace();
  }
});

$("#fileInput").addEventListener("change", (event) => setFile(event.target.files[0]));
$("#analyzeButton").addEventListener("click", analyse);
$("#removeFile").addEventListener("click", () => {
  resetWorkspace();
  showNotice("Awaiting a drawing", "Once analysed, candidate regions will be listed here. Detector confidence is not OCR confidence.");
});
const dropzone = $("#dropzone");
["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => {
  event.preventDefault(); dropzone.classList.add("dragover");
}));
["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => {
  event.preventDefault(); dropzone.classList.remove("dragover");
}));
dropzone.addEventListener("drop", (event) => setFile(event.dataTransfer.files[0]));
fetch("/api/health").then((r) => r.json()).then((health) => {
  const meta = $(".top-meta");
  if (health.status === "ok") {
    $("#apiStatus").textContent = health.detector_weights_present ? "API ready · detector weights found" : "API ready · detector missing";
    if (!health.detector_weights_present) showNotice("Detector model missing", "The UI and API are available, but yolo_floorplan.pt must be present in the repository root before analysis can run.");
  } else {
    meta.classList.add("api-error");
    $("#apiStatus").textContent = "API not ready";
  }
}).catch(() => {
  $(".top-meta").classList.add("api-error");
  $("#apiStatus").textContent = "API unavailable";
  showNotice("API unavailable", "Start the local Planline API to enable drawing analysis.");
});

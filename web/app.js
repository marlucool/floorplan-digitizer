const $ = (selector) => document.querySelector(selector);
const PREVIEW_MODE = window.PLANLINE_PREVIEW === true;
const state = { file: null, objectUrl: null, result: null, previewUrl: null, detections: [], selectedId: null, activeFilter: "all", searchQuery: "", sortMode: "original", overlayVisible: true, resizeObserver: null, resizeHandler: null, controller: null, ocrReady: false, ocrModels: [], ocrDatasets: [], ocrPredictions: {}, ocrRunning: false, ocrModelId: null, ocrDevice: null, ocrCapabilitiesLoaded: false, ocrCapabilitiesPromise: null, zoom: 1, calibration: { points: [], picking: false, applied: null }, reconstruction: null, geometry: { segments: [], rooms: [], mode: "select", pendingPoint: null, pendingRoom: [], selectedId: null, selectedRoomId: null, nextId: 1, nextRoomId: 1, drag: null, suppressNextClick: false, lastSnap: null } };

function updateWorkflow(stage) {
  const order = ["upload", "analyse", "review", "draw"];
  const activeIndex = Math.max(0, order.indexOf(stage));
  const labels = {
    upload: "Next: upload a floor-plan image or PDF.",
    analyse: "Next: analyse the drawing to find candidate walls and dimensions.",
    review: "Next: review the detected regions. Verify written dimensions before using them as a scale reference.",
    draw: "Next: trace the walls and room boundaries you need, then export your own geometry."
  };
  document.querySelectorAll(".workflow-step").forEach((step) => {
    const index = order.indexOf(step.dataset.step);
    const complete = index < activeIndex;
    const active = index === activeIndex;
    step.classList.toggle("is-complete", complete);
    step.classList.toggle("is-active", active);
    if (active) step.setAttribute("aria-current", "step");
    else step.removeAttribute("aria-current");
    const stateLabel = step.querySelector(".workflow-step-state");
    if (stateLabel) stateLabel.textContent = complete ? "Done" : active ? "Current" : "Later";
  });
  const next = $("#workflowNext");
  if (next) next.textContent = labels[stage] || labels.upload;
}

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function resetWorkspace() {
  updateWorkflow("upload");
  if (state.controller) { state.controller.abort(); state.controller = null; }
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  if (state.resizeObserver) state.resizeObserver.disconnect();
  if (state.resizeHandler) window.removeEventListener("resize", state.resizeHandler);
  state.file = null; state.objectUrl = null; state.result = null; state.previewUrl = null;
  state.detections = []; state.selectedId = null; state.activeFilter = "all";
  state.overlayVisible = true; state.resizeObserver = null; state.resizeHandler = null; state.zoom = 1;
  state.searchQuery = ""; state.sortMode = "original";
  state.geometry = { segments: [], rooms: [], mode: "select", pendingPoint: null, pendingRoom: [], selectedId: null, selectedRoomId: null, nextId: 1, nextRoomId: 1 };
  clearCalibration();
  renderGeometryControls();
  if ($("#detectionSearch")) $("#detectionSearch").value = "";
  if ($("#detectionSort")) $("#detectionSort").value = "original";
  $("#fileInput").value = "";
  $("#brightnessControl").value = "0";
  $("#contrastControl").value = "1";
  $("#brightnessValue").textContent = "0";
  $("#contrastValue").textContent = "1.00×";
  $("#fileCard").classList.add("hidden");
  $("#pdfPageControl").classList.add("hidden");
  $("#pdfPageNumber").value = "1";
  $("#pdfPageNumber").removeAttribute("max");
  $("#pdfPageCount").textContent = "Page count will be confirmed after analysis.";
  $("#dropzone").classList.remove("hidden");
  $("#analyzeButton").disabled = true;
  $("#exportReview").disabled = true;
  $("#saveProject").disabled = true;
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
  const allowed = /\.(png|jpe?g|webp|tiff?)$/i.test(file.name) || /\.pdf$/i.test(file.name) ||
    (PREVIEW_MODE && /\.svg$/i.test(file.name));
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
  state.reconstruction = null;
  $("#reconstructionStatus").textContent = "Analyse a drawing, verify horizontal and vertical dimensions, and confirm their wall pairs.";
  $("#reconstructionStatus").dataset.state = "";
  updateWorkflow("analyse");
  if ($("#drawingSourceId")) $("#drawingSourceId").value = (file.name.replace(/\\.[^.]+$/, "") || "drawing").slice(0, 128);
  updateDatasetCaptureButtons();
  $("#brightnessControl").value = "0";
  $("#contrastControl").value = "1";
  $("#brightnessValue").textContent = "0";
  $("#contrastValue").textContent = "1.00×";
  state.objectUrl = URL.createObjectURL(file);
  state.result = null;
  state.previewUrl = null;
  clearCalibration();
  state.geometry = { segments: [], rooms: [], mode: "select", pendingPoint: null, pendingRoom: [], selectedId: null, selectedRoomId: null, nextId: 1, nextRoomId: 1 };
  renderGeometryControls();
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
    (state.geometry.segments || []).forEach((segment) => {
      const selected = segment.id === state.geometry.selectedId;
      ctx.beginPath();
      ctx.strokeStyle = selected ? "#d34e3e" : "#172b4d";
      ctx.lineWidth = selected ? Math.max(6, canvas.width / 300) : Math.max(4, canvas.width / 420);
      ctx.lineCap = "round";
      ctx.moveTo(segment.start_px.x * sx, segment.start_px.y * sy);
      ctx.lineTo(segment.end_px.x * sx, segment.end_px.y * sy);
      ctx.stroke();
      [segment.start_px, segment.end_px].forEach((point) => {
        ctx.beginPath();
        ctx.fillStyle = selected ? "#d34e3e" : "#172b4d";
        ctx.arc(point.x * sx, point.y * sy, Math.max(4, canvas.width / 450), 0, Math.PI * 2);
        ctx.fill();
      });
    });
    (state.geometry.rooms || []).forEach((room) => {
      const selected = room.id === state.geometry.selectedRoomId;
      const vertices = room.vertices_px.map((point) => ({ x: point.x * sx, y: point.y * sy }));
      if (vertices.length < 3) return;
      ctx.beginPath();
      ctx.moveTo(vertices[0].x, vertices[0].y);
      vertices.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
      ctx.closePath();
      ctx.fillStyle = selected ? "rgba(211, 78, 62, 0.16)" : "rgba(36, 132, 100, 0.12)";
      ctx.strokeStyle = selected ? "#d34e3e" : "#248464";
      ctx.lineWidth = selected ? Math.max(5, canvas.width / 350) : Math.max(3, canvas.width / 500);
      ctx.fill();
      ctx.stroke();
      vertices.forEach((point) => {
        ctx.beginPath();
        ctx.fillStyle = selected ? "#d34e3e" : "#248464";
        ctx.arc(point.x, point.y, Math.max(4, canvas.width / 450), 0, Math.PI * 2);
        ctx.fill();
      });
    });
    if (state.geometry.pendingRoom?.length) {
      const vertices = state.geometry.pendingRoom.map((point) => ({ x: point.x * sx, y: point.y * sy }));
      ctx.beginPath();
      ctx.strokeStyle = "#c47734";
      ctx.lineWidth = Math.max(3, canvas.width / 500);
      ctx.setLineDash([9, 6]);
      ctx.moveTo(vertices[0].x, vertices[0].y);
      vertices.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
      ctx.stroke();
      ctx.setLineDash([]);
      vertices.forEach((point) => {
        ctx.beginPath();
        ctx.fillStyle = "#c47734";
        ctx.arc(point.x, point.y, Math.max(5, canvas.width / 350), 0, Math.PI * 2);
        ctx.fill();
      });
    }
    if (state.geometry.pendingPoint) {
      ctx.beginPath();
      ctx.fillStyle = "#c47734";
      ctx.arc(state.geometry.pendingPoint.x * sx, state.geometry.pendingPoint.y * sy, Math.max(6, canvas.width / 300), 0, Math.PI * 2);
      ctx.fill();
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
  $("#calibrationPoints").textContent = "No scale reference selected.";
  $("#calibrationResult").textContent = "No scale applied.";
  $("#startCalibration").disabled = !state.result;
  $("#startCalibration").textContent = "Pick two points";
  $("#applyCalibration").disabled = true;
  $("#clearCalibration").disabled = true;
  $("#previewImage").classList.remove("calibration-picking");
  if (state.result && state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
  if (state.geometry) renderGeometryControls();
}

function renderCalibrationStatus() {
  const points = state.calibration.points;
  if (state.reconstruction?.scale?.pixels_per_mm_x && state.reconstruction?.scale?.pixels_per_mm_y) {
    $("#calibrationPoints").textContent =
      "Confirmed dimensions · X " + state.reconstruction.scale.pixels_per_mm_x.toFixed(6) +
      " px/mm · Y " + state.reconstruction.scale.pixels_per_mm_y.toFixed(6) + " px/mm";
    $("#calibrationResult").textContent =
      "Separate horizontal and vertical scales derived from confirmed dimension-to-wall matches. Draft geometry only; inspect for scan distortion.";
  } else {
    $("#calibrationPoints").textContent = state.calibration.applied?.method === "verified_dimension_association"
      ? "Derived from a confirmed dimension-to-wall match."
      : "Point 1: " +
        (points[0] ? Math.round(points[0].x) + ", " + Math.round(points[0].y) + " px" : "not set") +
        " · Point 2: " +
        (points[1] ? Math.round(points[1].x) + ", " + Math.round(points[1].y) + " px" : "not set");
  }
  $("#startCalibration").disabled = !state.result;
  $("#startCalibration").textContent = state.calibration.picking ? "Click the drawing…" : "Pick two points";
  $("#applyCalibration").disabled = points.length !== 2;
  $("#clearCalibration").disabled = points.length === 0 && !state.calibration.applied && !state.reconstruction;
  $("#calibrationState").textContent = state.reconstruction ? "X/Y scales" : state.calibration.applied ? "Applied" :
    state.calibration.picking ? "Picking points" : points.length ? "2 points ready" : "Not set";
  $("#previewImage").classList.toggle("calibration-picking", state.calibration.picking);
}

function applyAssociatedDimensionScale(reference) {
  if (state.reconstruction && state.geometry.segments.some((segment) => segment.created_by_reconstruction)) {
    $("#calibrationResult").textContent = "Clear the generated wall draft before applying a single-dimension scale.";
    return;
  }
  const distanceMm = Number(reference?.valueMm);
  const pixelDistance = Number(reference?.spanPx);
  if (!state.result || !(distanceMm > 0) || !(pixelDistance > 0) ||
      !Number.isFinite(distanceMm) || !Number.isFinite(pixelDistance)) return;
  const pixelsPerMm = pixelDistance / distanceMm;
  if (!Number.isFinite(pixelsPerMm) || pixelsPerMm <= 0) {
    $("#calibrationResult").textContent = "The matched dimension cannot produce a valid scale.";
    return;
  }
  state.reconstruction = null;
  state.calibration = {
    points: [],
    picking: false,
    applied: {
      method: "verified_dimension_association",
      points_px: [],
      pixel_distance: Number(pixelDistance.toFixed(3)),
      known_distance: distanceMm,
      input_unit: "mm",
      known_distance_mm: Number(distanceMm.toFixed(6)),
      reference_dimension_text: reference.text || null,
      reference_dimension_id: reference.id || null,
      reference_dimension_line_id: reference.lineId || null,
      reference_wall_ids: Array.isArray(reference.wallIds) ? reference.wallIds : [],
      pixels_per_mm: Number(pixelsPerMm.toFixed(9)),
      source_filename: state.file?.name || null,
      source_page_index: state.result?.source?.page_index ?? 0,
      status: "user_verified_association_reference_not_geometry_validation"
    }
  };
  $("#calibrationResult").textContent = "Scale derived from confirmed match: " +
    reference.text + " · " + pixelDistance.toFixed(1) + " px / " +
    distanceMm.toLocaleString(undefined, { maximumFractionDigits: 3 }) +
    " mm = " + pixelsPerMm.toFixed(6) + " px/mm. Check against other dimensions.";
  renderCalibrationStatus();
  renderGeometryControls();
}

function startCalibration() {
  if (!state.result) return;
  state.geometry.mode = "select";
  state.geometry.pendingPoint = null;
  state.geometry.pendingRoom = [];
  renderGeometryControls();
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
  if (state.calibration.points.length === 2) {
    $("#calibrationResult").textContent = "Two points selected. Enter their known distance and apply the scale.";
  }
}

function applyCalibration() {
  if (state.reconstruction && state.geometry.segments.some((segment) => segment.created_by_reconstruction)) {
    $("#calibrationResult").textContent = "Clear the generated wall draft before replacing its confirmed X/Y scales with one manual scale.";
    return;
  }
  const points = state.calibration.points;
  const distance = Number($("#calibrationDistance").value);
  const unit = $("#calibrationUnit").value;
  if (points.length !== 2) return;
  if (!Number.isFinite(distance) || distance <= 0 || !CALIBRATION_UNIT_TO_MM[unit]) {
    $("#calibrationResult").textContent = "Enter a positive distance and choose a supported unit.";
    $("#calibrationDistance").focus();
    return;
  }
  const pixelDistance = Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y);
  if (!Number.isFinite(pixelDistance) || pixelDistance < 1) {
    $("#calibrationResult").textContent = "The selected points are too close together. Pick two distinct points.";
    return;
  }
  const distanceMm = distance * CALIBRATION_UNIT_TO_MM[unit];
  if (!Number.isFinite(distanceMm) || distanceMm <= 0) {
    $("#calibrationResult").textContent = "That distance is outside the supported numeric range.";
    return;
  }
  state.reconstruction = null;
  state.calibration.applied = {
    method: "user_two_point_reference",
    points_px: points.map((point) => ({ x: Number(point.x.toFixed(2)), y: Number(point.y.toFixed(2)) })),
    pixel_distance: Number(pixelDistance.toFixed(3)),
    known_distance: distance,
    input_unit: unit,
    known_distance_mm: Number(distanceMm.toFixed(6)),
    reference_dimension_text: null,
    reference_dimension_id: null,
    pixels_per_mm: Number((pixelDistance / distanceMm).toFixed(9)),
    source_filename: state.file?.name || null,
    source_page_index: state.result?.source?.page_index ?? 0,
    status: "user_supplied_reference_not_geometry_validation"
  };
  $("#calibrationResult").textContent = pixelDistance.toFixed(1) + " px / " +
    distanceMm.toLocaleString(undefined, { maximumFractionDigits: 3 }) +
    " mm = " + state.calibration.applied.pixels_per_mm.toFixed(6) +
    " px/mm. Manual reference.";
  renderCalibrationStatus();
  renderGeometryControls();
}
$("#startCalibration").addEventListener("click", startCalibration);
$("#applyCalibration").addEventListener("click", () => applyCalibration());
$("#clearCalibration").addEventListener("click", clearCalibration);
function getSourcePoint(event) {
  if (!state.result) return null;
  const rect = $("#previewImage").getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  return {
    x: Math.max(0, Math.min(state.result.image.width, ((event.clientX - rect.left) / rect.width) * state.result.image.width)),
    y: Math.max(0, Math.min(state.result.image.height, ((event.clientY - rect.top) / rect.height) * state.result.image.height))
  };
}

function pointToSegmentDistance(point, start, end) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSquared = dx * dx + dy * dy;
  if (!lengthSquared) return Math.hypot(point.x - start.x, point.y - start.y);
  const t = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared));
  return Math.hypot(point.x - (start.x + t * dx), point.y - (start.y + t * dy));
}

function refreshWallDimensionOptions() {
  const select = $("#wallDimensionSelect");
  if (!select) return;
  const previous = select.value;
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a verified dimension…";
  select.append(placeholder);
  document.querySelectorAll(".dimension-text-item").forEach((row) => {
    const verified = row.querySelector(".dimension-text-verified-input")?.checked;
    const valueMm = row.dataset.parsedValueMm;
    if (!verified || !valueMm || row.dataset.dimensionType !== "linear") return;
    const option = document.createElement("option");
    option.value = row.dataset.detectionId || "";
    option.dataset.valueMm = valueMm;
    const raw = row.querySelector(".dimension-text-value")?.value.trim() || "Dimension";
    option.textContent = raw + " → " + valueMm + " mm";
    select.append(option);
  });
  select.disabled = select.options.length <= 1;
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
  updateWallDimensionCheckControls();
}

function getPixelsPerMmForSegment(segment) {
  if (segment && state.reconstruction?.scale) {
    const dx = segment.end_px.x - segment.start_px.x;
    const dy = segment.end_px.y - segment.start_px.y;
    const value = Math.abs(dx) >= Math.abs(dy)
      ? state.reconstruction.scale.pixels_per_mm_x
      : state.reconstruction.scale.pixels_per_mm_y;
    if (Number.isFinite(value) && value > 0) return value;
  }
  const uniform = state.calibration.applied?.pixels_per_mm;
  return Number.isFinite(uniform) && uniform > 0 ? uniform : null;
}

function updateWallDimensionCheckControls() {
  const select = $("#wallDimensionSelect");
  const selectedWall = state.geometry?.segments?.find((segment) => segment.id === state.geometry.selectedId);
  const hasCalibration = Boolean(getPixelsPerMmForSegment(selectedWall));
  const hasDimension = Boolean(select?.selectedOptions?.[0]?.dataset.valueMm);
  const toleranceText = $("#wallDimensionTolerance").value.trim();
  const tolerance = Number(toleranceText);
  const validTolerance = toleranceText !== "" && Number.isFinite(tolerance) && tolerance >= 0 && tolerance <= 10;
  $("#checkWallDimension").disabled = !selectedWall || !hasDimension || !hasCalibration || !validTolerance;
  if (!hasCalibration) {
    $("#wallDimensionResult").textContent = "Apply a two-point scale reference before comparing metric dimensions.";
  } else if (!selectedWall) {
    $("#wallDimensionResult").textContent = "Select a manual wall segment on the drawing.";
  } else if (!hasDimension) {
    $("#wallDimensionResult").textContent = "Interpret a dimension with an explicit unit, verify it, then choose it above.";
  }
}

async function compareSelectedWallToDimension() {
  const selectedWall = state.geometry.segments.find((segment) => segment.id === state.geometry.selectedId);
  const option = $("#wallDimensionSelect").selectedOptions[0];
  const dimensionMm = option?.dataset.valueMm;
  const pixelsPerMm = getPixelsPerMmForSegment(selectedWall);
  const tolerance = Number($("#wallDimensionTolerance").value);
  if (!selectedWall || !dimensionMm || !(pixelsPerMm > 0)) {
    updateWallDimensionCheckControls();
    return;
  }
  const wallLengthPx = Math.hypot(
    selectedWall.end_px.x - selectedWall.start_px.x,
    selectedWall.end_px.y - selectedWall.start_px.y
  );
  const button = $("#checkWallDimension");
  button.disabled = true;
  button.textContent = "Comparing…";
  try {
    const response = await fetch("/api/validate-wall-dimension", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        wall_length_px: wallLengthPx,
        pixels_per_mm: pixelsPerMm,
        dimension_mm: dimensionMm,
        tolerance_percent: tolerance,
        calibration_method: state.reconstruction
          ? "verified_dimension_association"
          : state.calibration.applied?.method === "verified_dimension_association"
            ? "verified_dimension_association"
            : "user_two_point_reference"
      })
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "Wall comparison failed.");
    const summary = "Wall " + selectedWall.id + ": " + result.measured_length_mm +
      " mm vs " + result.dimension_value_mm + " mm. Difference " +
      result.delta_mm + " mm (" + result.difference_percent + "%). ";
    $("#wallDimensionResult").textContent = result.status === "within_tolerance"
      ? summary + "Within the selected tolerance. Confirm the association against the drawing; geometry was not changed."
      : summary + "Outside tolerance. Check the scale reference and dimension-to-wall association; geometry was not changed.";
    $("#wallDimensionResult").dataset.status = result.status;
  } catch (error) {
    $("#wallDimensionResult").textContent = "Comparison failed: " + (error.message || "Local API unavailable.");
    $("#wallDimensionResult").dataset.status = "error";
  } finally {
    button.textContent = "Compare selected wall";
    updateWallDimensionCheckControls();
  }
}

function renderGeometryControls() {
  const geometry = state.geometry;
  const wallCount = geometry?.segments?.length || 0;
  const reconstructedCount = (geometry?.segments || []).filter((segment) => segment.created_by_reconstruction).length;
  const manualCount = wallCount - reconstructedCount;
  const roomCount = geometry?.rooms?.length || 0;
  if (!$("#geometryCount")) return;
  $("#geometryCount").textContent = wallCount
    ? wallCount + " wall edges" + (reconstructedCount ? " · " + reconstructedCount + " detected draft" : "")
    : "No wall edges yet";
  $("#reconstructWalls").disabled = !state.result || PREVIEW_MODE;
  $("#roomCount").textContent = roomCount + (roomCount === 1 ? " room" : " rooms");
  $("#drawWallTool").disabled = !state.result;
  $("#selectWallTool").disabled = !state.result;
  $("#drawRoomTool").disabled = !state.result;
  $("#finishRoom").disabled = geometry.pendingRoom.length < 3;
  $("#cancelRoom").disabled = geometry.pendingRoom.length === 0;
  $("#undoWall").disabled = wallCount === 0;
  $("#deleteWall").disabled = !geometry.selectedId;
  $("#clearWalls").disabled = wallCount === 0;
  $("#deleteRoom").disabled = !geometry.selectedRoomId;
  $("#clearRooms").disabled = roomCount === 0;
  $("#exportGeometry").disabled = wallCount === 0 && roomCount === 0;
  $("#exportDxf").disabled = wallCount === 0 && roomCount === 0;
  $("#drawWallTool").classList.toggle("active-tool", geometry.mode === "draw_wall");
  $("#drawRoomTool").classList.toggle("active-tool", geometry.mode === "draw_room");
  $("#selectWallTool").classList.toggle("active-tool", geometry.mode === "select");
  $("#previewImage").classList.toggle("geometry-drawing", geometry.mode === "draw_wall" || geometry.mode === "draw_room");
  const snapNote = geometry.lastSnap ? " Snapped to " + geometry.lastSnap.id + "." : "";
  if (geometry.mode === "draw_wall") {
    $("#geometryStatus").textContent = (geometry.pendingPoint ? "Start point set. Click the end point." : "Draw mode: click a wall start, then its end.") + snapNote;
  } else if (geometry.mode === "draw_room") {
    $("#geometryStatus").textContent = geometry.pendingRoom.length
      ? geometry.pendingRoom.length + " room vertices placed. Add more points, then Finish room." + snapNote
      : "Room mode: click at least three corners, then Finish room." + snapNote;
  } else if (geometry.selectedRoomId) {
    $("#geometryStatus").textContent = "Selected " + geometry.selectedRoomId + ". Area is shown below.";
  } else if (geometry.selectedId) {
    $("#geometryStatus").textContent = "Selected " + geometry.selectedId + ". Delete it or draw another wall.";
  } else if (state.reconstruction) {
    $("#geometryStatus").textContent = "Measured wall-edge draft loaded. Inspect, delete or adjust every generated edge before using the drawing.";
  } else {
    $("#geometryStatus").textContent = "No wall geometry yet. Generate a measured draft from confirmed dimensions or draw walls manually.";
  }
  const selectedWall = geometry.segments.find((segment) => segment.id === geometry.selectedId);
  if (selectedWall) {
    const dx = selectedWall.end_px.x - selectedWall.start_px.x;
    const dy = selectedWall.end_px.y - selectedWall.start_px.y;
    const lengthPx = Math.hypot(dx, dy);
    const reconstructionScale = state.reconstruction
      ? (Math.abs(dx) >= Math.abs(dy)
        ? state.reconstruction.scale.pixels_per_mm_x
        : state.reconstruction.scale.pixels_per_mm_y)
      : null;
    const pixelsPerMm = reconstructionScale || state.calibration.applied?.pixels_per_mm;
    $("#wallLength").textContent = pixelsPerMm
      ? (lengthPx / pixelsPerMm / 1000).toFixed(3) + " m (" +
        (reconstructionScale ? "confirmed-dimension draft scale; review required" : "user-supplied scale; not verified") + ")"
      : lengthPx.toFixed(1) + " px · apply calibration for metric length";
  } else {
    $("#wallLength").textContent = "Select a wall to view its length.";
  }
  refreshWallDimensionOptions();
  const selectedRoom = geometry.rooms.find((room) => room.id === geometry.selectedRoomId);
  if (selectedRoom) {
    const areaPx = polygonAreaPx2(selectedRoom.vertices_px);
    const scaleX = state.reconstruction?.scale?.pixels_per_mm_x;
    const scaleY = state.reconstruction?.scale?.pixels_per_mm_y;
    const pixelsPerMm = state.calibration.applied?.pixels_per_mm;
    if (scaleX > 0 && scaleY > 0) {
      const areaM2 = areaPx / (scaleX * scaleY) / 1000000;
      $("#roomArea").textContent = areaM2.toFixed(3) + " m² (axis scales from confirmed dimensions; draft only)";
    } else if (pixelsPerMm) {
      const areaM2 = areaPx / (pixelsPerMm * pixelsPerMm) / 1000000;
      $("#roomArea").textContent = areaM2.toFixed(3) + " m² (using user-supplied scale; not verified)";
    } else {
      $("#roomArea").textContent = areaPx.toFixed(1) + " px² · apply scale calibration for area units";
    }
  } else {
    $("#roomArea").textContent = "Select a room to view its area.";
  }
}

function setGeometryMode(mode) {
  if (!state.result) return;
  if (state.calibration.picking) {
    state.calibration.picking = false;
    renderCalibrationStatus();
  }
  state.geometry.mode = mode;
  state.geometry.drag = null;
  state.geometry.lastSnap = null;
  if (mode !== "draw_wall") state.geometry.pendingPoint = null;
  if (mode !== "draw_room") state.geometry.pendingRoom = [];
  if (mode !== "select") { state.geometry.selectedId = null; state.geometry.selectedRoomId = null; }
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function snapPointToGeometry(point) {
  if (!point || !$("#geometrySnap").checked) {
    state.geometry.lastSnap = null;
    return point;
  }
  const candidates = [];
  state.geometry.segments.forEach((segment) => {
    candidates.push({ id: segment.id, point: segment.start_px });
    candidates.push({ id: segment.id, point: segment.end_px });
  });
  state.geometry.rooms.forEach((room) => {
    room.vertices_px.forEach((vertex) => candidates.push({ id: room.id, point: vertex }));
  });
  let nearest = null;
  let nearestDistance = 10;
  candidates.forEach((candidate) => {
    const distance = Math.hypot(point.x - candidate.point.x, point.y - candidate.point.y);
    if (distance <= nearestDistance) {
      nearest = candidate;
      nearestDistance = distance;
    }
  });
  if (!nearest) {
    state.geometry.lastSnap = null;
    return point;
  }
  state.geometry.lastSnap = { id: nearest.id, distance: nearestDistance };
  return { x: nearest.point.x, y: nearest.point.y };
}

function addManualWallPoint(point) {
  if (!point) return;
  point = snapPointToGeometry(point);
  if (!state.geometry.pendingPoint) {
    state.geometry.pendingPoint = point;
  } else {
    const start = state.geometry.pendingPoint;
    const length = Math.hypot(point.x - start.x, point.y - start.y);
    if (length < 3) {
      $("#geometryStatus").textContent = "That segment is too short. Choose a more distant end point.";
      return;
    }
    const id = "manual-wall-" + String(state.geometry.nextId++).padStart(3, "0");
    state.geometry.segments.push({
      id,
      type: "wall_segment",
      start_px: { x: Number(start.x.toFixed(2)), y: Number(start.y.toFixed(2)) },
      end_px: { x: Number(point.x.toFixed(2)), y: Number(point.y.toFixed(2)) },
      source_page_index: state.result?.source?.page_index ?? 0,
      created_by_user: true
    });
    state.geometry.pendingPoint = null;
    state.geometry.selectedId = id;
  }
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function polygonAreaPx2(vertices) {
  if (!Array.isArray(vertices) || vertices.length < 3) return 0;
  let sum = 0;
  vertices.forEach((point, index) => {
    const next = vertices[(index + 1) % vertices.length];
    sum += point.x * next.y - next.x * point.y;
  });
  return Math.abs(sum) / 2;
}

function pointInPolygon(point, vertices) {
  let inside = false;
  for (let i = 0, j = vertices.length - 1; i < vertices.length; j = i++) {
    const a = vertices[i];
    const b = vertices[j];
    const crosses = ((a.y > point.y) !== (b.y > point.y)) &&
      (point.x < ((b.x - a.x) * (point.y - a.y)) / ((b.y - a.y) || Number.EPSILON) + a.x);
    if (crosses) inside = !inside;
  }
  return inside;
}

function addManualRoomPoint(point) {
  if (!point) return;
  point = snapPointToGeometry(point);
  state.geometry.pendingRoom.push({ x: Number(point.x.toFixed(2)), y: Number(point.y.toFixed(2)) });
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function segmentsIntersect(a, b, c, d) {
  const cross = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
  const abC = cross(a, b, c);
  const abD = cross(a, b, d);
  const cdA = cross(c, d, a);
  const cdB = cross(c, d, b);
  return ((abC > 0 && abD < 0) || (abC < 0 && abD > 0)) &&
    ((cdA > 0 && cdB < 0) || (cdA < 0 && cdB > 0));
}

function isSimplePolygon(vertices) {
  if (vertices.length < 3) return false;
  for (let i = 0; i < vertices.length; i += 1) {
    const a = vertices[i];
    const b = vertices[(i + 1) % vertices.length];
    for (let j = i + 1; j < vertices.length; j += 1) {
      if (j === i || j === i + 1 || (i === 0 && j === vertices.length - 1)) continue;
      const c = vertices[j];
      const d = vertices[(j + 1) % vertices.length];
      if (segmentsIntersect(a, b, c, d)) return false;
    }
  }
  return true;
}

function finishManualRoom() {
  const vertices = state.geometry.pendingRoom;
  if (vertices.length < 3) return;
  const area = polygonAreaPx2(vertices);
  const uniqueVertices = new Set(vertices.map((point) => point.x + "," + point.y));
  if (uniqueVertices.size < 3) {
    $("#geometryStatus").textContent = "A room needs at least three distinct corners.";
    return;
  }
  if (!isSimplePolygon(vertices)) {
    $("#geometryStatus").textContent = "This outline crosses itself. Cancel it and trace the room boundary without crossing edges.";
    return;
  }
  if (!Number.isFinite(area) || area < 9) {
    $("#geometryStatus").textContent = "That room outline is too small. Add more widely spaced corners.";
    return;
  }
  const id = "manual-room-" + String(state.geometry.nextRoomId++).padStart(3, "0");
  state.geometry.rooms.push({
    id,
    type: "room_polygon",
    vertices_px: vertices.map((point) => ({ ...point })),
    source_page_index: state.result?.source?.page_index ?? 0,
    created_by_user: true
  });
  state.geometry.pendingRoom = [];
  state.geometry.selectedRoomId = id;
  state.geometry.mode = "select";
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function cancelManualRoom() {
  state.geometry.pendingRoom = [];
  state.geometry.mode = "select";
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function deleteSelectedManualRoom() {
  if (!state.geometry.selectedRoomId) return;
  state.geometry.rooms = state.geometry.rooms.filter((room) => room.id !== state.geometry.selectedRoomId);
  state.geometry.selectedRoomId = null;
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function clearManualRooms() {
  state.geometry.rooms = [];
  state.geometry.pendingRoom = [];
  state.geometry.selectedRoomId = null;
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function selectManualGeometry(point) {
  if (!point) return;
  const room = [...state.geometry.rooms].reverse().find((item) => pointInPolygon(point, item.vertices_px));
  if (room) {
    state.geometry.selectedRoomId = room.id;
    state.geometry.selectedId = null;
  } else {
    state.geometry.selectedRoomId = null;
    let closest = null;
    let closestDistance = 12;
    for (const segment of state.geometry.segments) {
      const distance = pointToSegmentDistance(point, segment.start_px, segment.end_px);
      if (distance <= closestDistance) {
        closest = segment;
        closestDistance = distance;
      }
    }
    state.geometry.selectedId = closest?.id || null;
  }
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function handleDrawingClick(event) {
  if (state.geometry.suppressNextClick) { state.geometry.suppressNextClick = false; return; }
  if (!state.result) return;
  if (state.calibration.picking) return addCalibrationPoint(event);
  const point = getSourcePoint(event);
  if (state.geometry.mode === "draw_wall") return addManualWallPoint(point);
  if (state.geometry.mode === "draw_room") return addManualRoomPoint(point);
  if (state.geometry.mode === "select") return selectManualGeometry(point);
}

function undoManualWall() {
  let lastManualIndex = -1;
  for (let index = state.geometry.segments.length - 1; index >= 0; index -= 1) {
    if (state.geometry.segments[index].created_by_user === true) {
      lastManualIndex = index;
      break;
    }
  }
  if (lastManualIndex < 0) return;
  const [removed] = state.geometry.segments.splice(lastManualIndex, 1);
  if (state.geometry.selectedId === removed.id) state.geometry.selectedId = null;
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function deleteSelectedManualWall() {
  if (!state.geometry.selectedId) return;
  state.geometry.segments = state.geometry.segments.filter((segment) => segment.id !== state.geometry.selectedId);
  if (!state.geometry.segments.some((segment) => segment.created_by_reconstruction)) {
    state.reconstruction = null;
    $("#reconstructionStatus").textContent = "No generated wall edges remain.";
    $("#reconstructionStatus").dataset.state = "";
    renderCalibrationStatus();
  }
  state.geometry.selectedId = null;
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function clearManualWalls() {
  state.geometry.segments = [];
  state.reconstruction = null;
  $("#reconstructionStatus").textContent = "Wall geometry cleared. Generate a new draft or draw manually.";
  $("#reconstructionStatus").dataset.state = "";
  state.geometry.pendingPoint = null;
  state.geometry.selectedId = null;
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

async function reconstructWallDraft() {
  if (!state.result || PREVIEW_MODE) return;
  const button = $("#reconstructWalls");
  const output = $("#reconstructionStatus");
  const originalText = button.textContent;
  const regions = state.result.dimension_regions || [];
  const rows = [...document.querySelectorAll(".dimension-text-item")];
  const dimensions = regions.map((region) => {
    const row = rows.find((item) => item.dataset.detectionId === region.id);
    const text = row?.querySelector(".dimension-text-value")?.value.trim() || "";
    const selectedLineId = row?.querySelector(".dimension-line-select")?.value || null;
    const spanSelect = row?.querySelector(".dimension-wall-span-select");
    const associationConfirmed = Boolean(row?.querySelector(".dimension-association-verified-input")?.checked);
    const association = region.association || {};
    const selectedLine = (association.candidate_lines || []).find(
      (candidate) => candidate.dimension_line_id === selectedLineId
    );
    const selectedSpan = spanSelect && spanSelect.value !== ""
      ? selectedLine?.wall_spans?.[Number(spanSelect.value)]
      : null;
    return {
      detection_id: region.id,
      raw_text: text,
      text_verified: Boolean(row?.querySelector(".dimension-text-verified-input")?.checked),
      association_confirmed: associationConfirmed,
      dimension_line_id: selectedLineId,
      wall_ids: selectedSpan?.wall_ids || []
    };
  });

  button.disabled = true;
  button.textContent = "Building wall draft…";
  output.dataset.state = "";
  output.textContent = "Checking verified dimensions and rebuilding the candidate wall edges…";
  try {
    const response = await fetch("/api/reconstruct-wall-draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_width: state.result.image.width,
        source_height: state.result.image.height,
        source_page_index: state.result.source?.page_index ?? 0,
        detections: state.result.detections || [],
        dimensions
      })
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "The measured wall draft could not be built.");

    const manualSegments = state.geometry.segments.filter((segment) => !segment.created_by_reconstruction);
    state.geometry.segments = [...manualSegments, ...(result.segments || [])];
    state.geometry.selectedId = null;
    state.reconstruction = result;
    state.calibration = { points: [], picking: false, applied: null };
    renderCalibrationStatus();
    renderGeometryControls();
    $("#geometryDetails").open = true;
    const skipped = result.skipped_walls?.length || 0;
    output.dataset.state = skipped ? "warning" : "success";
    output.textContent =
      "Created " + result.segments.length + " editable wall-face edges from " +
      result.wall_regions_used + " detected wall regions. X scale " +
      result.scale.pixels_per_mm_x.toFixed(6) + " px/mm; Y scale " +
      result.scale.pixels_per_mm_y.toFixed(6) + " px/mm. " +
      (skipped ? skipped + " ambiguous wall regions were skipped. " : "") +
      "Inspect every edge and junction before exporting.";
    if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
    showNotice("Wall draft generated", result.warnings?.join(" ") || "Review all generated wall edges against the source.");
  } catch (error) {
    output.dataset.state = "error";
    output.textContent = error.message || "The wall draft could not be generated.";
  } finally {
    button.textContent = originalText;
    button.disabled = !state.result;
  }
}

async function exportManualGeometryDxf() {
  if (!state.result || (!state.geometry.segments.length && !state.geometry.rooms.length)) return;
  const hasReconstructionScale = Boolean(state.reconstruction?.scale?.pixels_per_mm_x && state.reconstruction?.scale?.pixels_per_mm_y);
  const payload = {
    source_width: state.result.image.width,
    source_height: state.result.image.height,
    pixels_per_mm: hasReconstructionScale ? null : state.calibration.applied?.pixels_per_mm ?? null,
    pixels_per_mm_x: hasReconstructionScale ? state.reconstruction.scale.pixels_per_mm_x : null,
    pixels_per_mm_y: hasReconstructionScale ? state.reconstruction.scale.pixels_per_mm_y : null,
    segments: state.geometry.segments.map((segment) => ({
      id: segment.id,
      start_px: segment.start_px,
      end_px: segment.end_px,
      source_detection_id: segment.created_by_reconstruction ? segment.source_detection_id : null
    })),
    rooms: state.geometry.rooms.map((room) => ({
      id: room.id,
      vertices_px: room.vertices_px
    }))
  };
  const button = $("#exportDxf");
  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = "Preparing DXF…";
  try {
    const response = await fetch("/api/export-dxf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || "The DXF export could not be created.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = ((state.file?.name || "drawing").replace(/.[^.]+$/, "") || "drawing") +
      (hasReconstructionScale ? "-measured-wall-draft.dxf" : "-manual-geometry.dxf");
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    $("#geometryStatus").textContent = hasReconstructionScale
      ? "DXF exported in millimetres using confirmed X/Y dimension scales. Detected wall edges are on DETECTED_WALL_DRAFT and still require review."
      : payload.pixels_per_mm
        ? "DXF exported in millimetres using the user-supplied, unverified scale."
        : "DXF exported with unitless source-pixel coordinates. Apply scale calibration for metric units.";
  } catch (error) {
    $("#geometryStatus").textContent = "DXF export failed: " + (error.message || "API unavailable");
  } finally {
    button.textContent = originalText;
    button.disabled = state.geometry.segments.length === 0 && state.geometry.rooms.length === 0;
  }
}


function exportManualGeometrySvg() {
  if (!state.result || (!state.geometry.segments.length && !state.geometry.rooms.length)) return;
  const width = state.result.image.width;
  const height = state.result.image.height;
  const scaleX = state.reconstruction?.scale?.pixels_per_mm_x || state.calibration.applied?.pixels_per_mm;
  const scaleY = state.reconstruction?.scale?.pixels_per_mm_y || state.calibration.applied?.pixels_per_mm;
  const physicalWidth = scaleX ? (width / scaleX).toFixed(3) + "mm" : width + "px";
  const physicalHeight = scaleY ? (height / scaleY).toFixed(3) + "mm" : height + "px";
  const polygons = state.geometry.rooms.map((room) =>
    '<polygon id="' + room.id + '" points="' + room.vertices_px.map((point) => point.x + "," + point.y).join(" ") +
    '" fill="rgba(36,132,100,0.12)" stroke="#248464" stroke-width="4" />'
  );
  const lines = state.geometry.segments.map((segment) =>
    '<line id="' + segment.id + '" x1="' + segment.start_px.x + '" y1="' + segment.start_px.y +
    '" x2="' + segment.end_px.x + '" y2="' + segment.end_px.y +
    '" stroke="#172b4d" stroke-width="6" stroke-linecap="round" />'
  );
  const elements = [...polygons, ...lines].join("\n  ");
  const svg = '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<svg xmlns="http://www.w3.org/2000/svg" width="' + physicalWidth + '" height="' + physicalHeight +
    '" viewBox="0 0 ' + width + ' ' + height + '">\n' +
    '  <metadata>Planline editable linework: ' + state.geometry.segments.length + ' wall edges and ' +
    state.geometry.rooms.length + ' room polygons. Coordinates are in original source-image pixels. ' +
    (state.reconstruction ? 'Wall draft uses X/Y scales derived from confirmed dimensions and remains unverified.' :
      scaleX && scaleY ? 'Physical scale uses an explicit user reference; it is not verified geometry.' : 'No physical scale is embedded.') +
    '</metadata>\n  ' + elements + '\n</svg>';
  const blob = new Blob([svg], { type: "image/svg+xml" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = ((state.file?.name || "drawing").replace(/\.[^.]+$/, "") || "drawing") + "-manual-geometry.svg";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("#drawWallTool").addEventListener("click", () => { setGeometryMode("draw_wall"); updateWorkflow("draw"); });
$("#drawRoomTool").addEventListener("click", () => { setGeometryMode("draw_room"); updateWorkflow("draw"); });
$("#finishRoom").addEventListener("click", finishManualRoom);
$("#cancelRoom").addEventListener("click", cancelManualRoom);
$("#deleteRoom").addEventListener("click", deleteSelectedManualRoom);
$("#clearRooms").addEventListener("click", clearManualRooms);
$("#selectWallTool").addEventListener("click", () => setGeometryMode("select"));
$("#undoWall").addEventListener("click", undoManualWall);
$("#deleteWall").addEventListener("click", deleteSelectedManualWall);
$("#clearWalls").addEventListener("click", () => {
  clearManualWalls();
  $("#reconstructionStatus").textContent = "All wall edges cleared, including any generated draft.";
});
$("#exportGeometry").addEventListener("click", exportManualGeometrySvg);
$("#exportDxf").addEventListener("click", exportManualGeometryDxf);
$("#reconstructWalls").addEventListener("click", reconstructWallDraft);
$("#wallDimensionSelect").addEventListener("change", updateWallDimensionCheckControls);
$("#wallDimensionTolerance").addEventListener("input", updateWallDimensionCheckControls);
$("#checkWallDimension").addEventListener("click", compareSelectedWallToDimension);

$("#previewImage").addEventListener("click", handleDrawingClick);
function beginWallEndpointDrag(event) {
  if (event.button !== 0 || !state.result || state.geometry.mode !== "select") return;
  const point = getSourcePoint(event);
  if (!point) return;

  if (state.geometry.selectedRoomId) {
    const room = state.geometry.rooms.find((item) => item.id === state.geometry.selectedRoomId);
    if (!room) return;
    let nearestIndex = -1;
    let nearestDistance = 14;
    room.vertices_px.forEach((vertex, index) => {
      const distance = Math.hypot(point.x - vertex.x, point.y - vertex.y);
      if (distance <= nearestDistance) {
        nearestIndex = index;
        nearestDistance = distance;
      }
    });
    if (nearestIndex < 0) return;
    state.geometry.drag = {
      roomId: room.id,
      vertexIndex: nearestIndex,
      originalPoint: { ...room.vertices_px[nearestIndex] },
      pointerId: event.pointerId
    };
  } else if (state.geometry.selectedId) {
    const segment = state.geometry.segments.find((item) => item.id === state.geometry.selectedId);
    if (!segment) return;
    const endpoints = [
      { key: "start_px", point: segment.start_px },
      { key: "end_px", point: segment.end_px }
    ];
    endpoints.sort((a, b) =>
      Math.hypot(point.x - a.point.x, point.y - a.point.y) -
      Math.hypot(point.x - b.point.x, point.y - b.point.y)
    );
    const nearest = endpoints[0];
    if (Math.hypot(point.x - nearest.point.x, point.y - nearest.point.y) > 14) return;
    state.geometry.drag = {
      segmentId: segment.id,
      endpoint: nearest.key,
      originalPoint: { ...nearest.point },
      pointerId: event.pointerId
    };
  } else {
    return;
  }
  event.currentTarget.setPointerCapture(event.pointerId);
  event.preventDefault();
}

function moveWallEndpointDrag(event) {
  const drag = state.geometry.drag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  const point = getSourcePoint(event);
  if (!point) return;
  if (drag.roomId) {
    const room = state.geometry.rooms.find((item) => item.id === drag.roomId);
    if (!room) return;
    room.vertices_px[drag.vertexIndex] = { x: Number(point.x.toFixed(2)), y: Number(point.y.toFixed(2)) };
  } else {
    const segment = state.geometry.segments.find((item) => item.id === drag.segmentId);
    if (!segment) return;
    segment[drag.endpoint] = { x: Number(point.x.toFixed(2)), y: Number(point.y.toFixed(2)) };
  }
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

function endWallEndpointDrag(event) {
  const drag = state.geometry.drag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  if (drag.roomId) {
    const room = state.geometry.rooms.find((item) => item.id === drag.roomId);
    if (room && (!isSimplePolygon(room.vertices_px) || polygonAreaPx2(room.vertices_px) < 9)) {
      room.vertices_px[drag.vertexIndex] = { ...drag.originalPoint };
      showNotice("Room corner not moved", "That edit would make the room outline invalid or self-crossing.");
    }
  } else {
    const segment = state.geometry.segments.find((item) => item.id === drag.segmentId);
    if (segment && Math.hypot(segment.end_px.x - segment.start_px.x, segment.end_px.y - segment.start_px.y) < 3) {
      segment[drag.endpoint] = { ...drag.originalPoint };
      showNotice("Wall endpoint not moved", "A wall segment must remain at least three source pixels long.");
    }
  }
  state.geometry.drag = null;
  state.geometry.suppressNextClick = true;
  window.setTimeout(() => { state.geometry.suppressNextClick = false; }, 250);
  renderGeometryControls();
  if (state.previewUrl) drawDetections(state.previewUrl, state.detections, state.result.image);
}

$("#previewImage").addEventListener("pointerdown", beginWallEndpointDrag);
$("#previewImage").addEventListener("pointermove", moveWallEndpointDrag);
$("#previewImage").addEventListener("pointerup", endWallEndpointDrag);
$("#previewImage").addEventListener("pointercancel", endWallEndpointDrag);


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
  $("#saveProject").disabled = false;
  $("#brightnessControl").value = String(payload.preprocessing?.brightness ?? 0);
  $("#contrastControl").value = String(payload.preprocessing?.contrast ?? 1);
  $("#brightnessValue").textContent = String(payload.preprocessing?.brightness ?? 0);
  $("#contrastValue").textContent = Number(payload.preprocessing?.contrast ?? 1).toFixed(2) + "×";
  $("#startCalibration").disabled = false;
  renderCalibrationStatus();
  renderGeometryControls();
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
  showNotice(detections.length ? "Detection finished — preparing dimension review" : "No candidate regions detected", detections.length ? notes : "The model returned no boxes at its current confidence threshold. This does not prove that the drawing contains no walls or dimensions. " + notes);
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
  updateDatasetCaptureButtons();
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

    const interpretButton = document.createElement("button");
    interpretButton.type = "button";
    interpretButton.className = "toolbar-button interpret-dimension-button";
    interpretButton.textContent = "Interpret dimension";
    interpretButton.disabled = true;
    const interpretation = document.createElement("output");
    interpretation.className = "dimension-interpretation";
    interpretation.setAttribute("aria-live", "polite");
    textInput.addEventListener("input", () => {
      interpretButton.disabled = !textInput.value.trim();
      interpretation.textContent = "";
      delete row.dataset.parsedValueMm;
      delete row.dataset.dimensionType;
      verifiedInput.checked = false;
      refreshWallDimensionOptions();
      updateDatasetCaptureButtons();
      updateUseScaleButton();
    });
    interpretButton.addEventListener("click", () => interpretDimensionForRow(textInput, interpretation, interpretButton));

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

    const useScaleButton = document.createElement("button");
    useScaleButton.type = "button";
    useScaleButton.className = "toolbar-button use-dimension-scale";
    useScaleButton.textContent = "Use confirmed match for scale";
    useScaleButton.disabled = true;

    const association = region.association || { status: "unmatched", candidate_lines: [] };
    const associationDetails = document.createElement("details");
    associationDetails.className = "dimension-association-details";
    const associationSummary = document.createElement("summary");
    associationSummary.textContent = association.candidate_lines?.length
      ? "Review suggested line and wall match"
      : "Line and wall match unavailable";
    associationDetails.append(associationSummary);
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
      option.textContent = (candidate.orientation === "horizontal" ? "Horizontal" : "Vertical") +
        (candidate === association.candidate_lines[0] ? " · best match" : " · alternative");
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
        option.textContent = "Wall pair " + (spanIndex + 1) +
          (span.globally_assigned ? " · suggested" : globalHint ? " · alternate" : "");
        spanSelect.append(option);
      });
      spanSelect.disabled = !selectedLine || !(selectedLine.wall_spans || []).length;
      associationVerified.checked = false;
      associationVerified.disabled = true;
      associationHelp.textContent = !selectedLine
        ? "Choose a dimension-line candidate. One detected line may serve multiple labels in a chained dimension."
        : !(selectedLine.wall_spans || []).length
          ? "This line has no viable wall-gap candidate. Leave the association unresolved."
          : "Choose the wall gap that this dimension measures. The best global suggestion is preselected when available; check it against the drawing.";
    }
    lineSelect.addEventListener("change", () => {
      updateWallSpanOptions();
      updateUseScaleButton();
    });
    spanSelect.addEventListener("change", () => {
      associationVerified.checked = false;
      associationVerified.disabled = !lineSelect.value || !spanSelect.value;
      updateUseScaleButton();
      const selectedLine = (association.candidate_lines || []).find(
        (candidate) => candidate.dimension_line_id === lineSelect.value
      );
      const selectedSpan = selectedLine?.wall_spans?.[Number(spanSelect.value)];
      associationHelp.textContent = !selectedSpan
        ? "Choose a wall gap. A dimension-line detection may be shared by several labels in a chain."
        : selectedSpan.globally_assigned
          ? "This is the strongest geometric suggestion. Check the drawing, then confirm it."
          : selectedSpan.globally_assigned_to
            ? "This wall gap is suggested for another dimension label. Check carefully before overriding."
            : "Check that this wall pair describes the written dimension, then confirm.";
    });

    const recommendedMatch = (association.candidate_lines || [])
      .flatMap((candidate) => (candidate.wall_spans || []).map((span, spanIndex) => ({
        candidate, span, spanIndex
      })))
      .filter(({ span }) => span.globally_assigned && span.globally_assigned_to === region.id)
      .sort((a, b) => (b.span.assignment_score || 0) - (a.span.assignment_score || 0))[0];
    const defaultCandidate = recommendedMatch?.candidate || association.candidate_lines?.[0];
    if (defaultCandidate) {
      lineSelect.value = defaultCandidate.dimension_line_id;
      updateWallSpanOptions();
      if (recommendedMatch) {
        spanSelect.value = String(recommendedMatch.spanIndex);
        associationVerified.disabled = false;
        associationHelp.textContent = "Best global match preselected. Check the drawing, then confirm if correct.";
        associationSummary.textContent = "Suggested match preselected · review before confirming";
      }
    }
    function updateUseScaleButton() {
      const selectedLine = (association.candidate_lines || []).find(
        (candidate) => candidate.dimension_line_id === lineSelect.value
      );
      const selectedSpan = spanSelect.value !== ""
        ? selectedLine?.wall_spans?.[Number(spanSelect.value)]
        : null;
      useScaleButton.disabled = !verifiedInput.checked ||
        !associationVerified.checked ||
        row.dataset.dimensionType !== "linear" ||
        !(Number(row.dataset.parsedValueMm) > 0) ||
        !(Number(selectedSpan?.span_px) > 0);
    }
    useScaleButton.addEventListener("click", () => {
      if (useScaleButton.disabled) return;
      const selectedLine = (association.candidate_lines || []).find(
        (candidate) => candidate.dimension_line_id === lineSelect.value
      );
      const selectedSpan = selectedLine?.wall_spans?.[Number(spanSelect.value)];
      applyAssociatedDimensionScale({
        valueMm: row.dataset.parsedValueMm,
        text: textInput.value.trim(),
        id: region.id,
        lineId: selectedLine?.dimension_line_id,
        wallIds: selectedSpan?.wall_ids,
        spanPx: selectedSpan?.span_px
      });
    });
    associationVerified.addEventListener("change", updateUseScaleButton);
    updateUseScaleButton();
    associationPanel.append(associationHeading, associationHelp, lineLabel, spanLabel, associationVerifiedLabel);
    associationDetails.append(associationPanel);

    const saveCropButton = document.createElement("button");
    saveCropButton.type = "button";
    saveCropButton.className = "toolbar-button save-dimension-crop";
    saveCropButton.textContent = "Save verified crop to dataset";
    saveCropButton.disabled = !region.crop_data_url;
    saveCropButton.addEventListener("click", () => saveDimensionCropToDataset(region, row, saveCropButton));
    textInput.addEventListener("input", updateDatasetCaptureButtons);
    verifiedInput.addEventListener("change", () => {
      refreshWallDimensionOptions();
      updateDatasetCaptureButtons();
      updateUseScaleButton();
    });

    fields.append(meta, textLabel, interpretButton, interpretation, styleLabel, verifiedLabel, useScaleButton, associationDetails, saveCropButton);
    row.append(fields);
    container.append(row);
  });
  refreshWallDimensionOptions();
  updateOcrControls();
}

function showOcrSuggestion(row, prediction) {
  const fields = row.querySelector(".dimension-text-fields");
  if (!fields) return;
  fields.querySelector(".ocr-suggestion")?.remove();
  const input = row.querySelector(".dimension-text-value");
  const output = row.querySelector(".dimension-interpretation");
  const interpretButton = row.querySelector(".interpret-dimension-button");
  const verifiedInput = row.querySelector(".dimension-text-verified-input");
  const wrapper = document.createElement("div");
  wrapper.className = "ocr-suggestion";
  const text = document.createElement("span");
  const confidence = Number.isFinite(prediction.confidence)
    ? " · " + Math.round(prediction.confidence * 100) + "% recogniser score"
    : " · confidence unavailable";
  text.textContent = "OCR draft: " + (prediction.text || "(no text recognised)") + confidence + " · check against drawing";
  if (prediction.text && input && !input.value.trim()) {
    input.value = prediction.text;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    if (verifiedInput) verifiedInput.checked = false;
    if (interpretButton && output) void interpretDimensionForRow(input, output, interpretButton);
  }
  const useButton = document.createElement("button");
  useButton.type = "button";
  useButton.className = "toolbar-button";
  useButton.textContent = "Replace with OCR reading";
  useButton.hidden = !prediction.text || input?.value.trim() === prediction.text;
  useButton.addEventListener("click", () => {
    if (!input) return;
    input.value = prediction.text;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    if (verifiedInput) verifiedInput.checked = false;
    if (interpretButton && output) void interpretDimensionForRow(input, output, interpretButton);
    showNotice("OCR draft inserted", "The reading has been interpreted but remains unverified. Check it against the original drawing.");
  });
  wrapper.append(text, useButton);
  const association = fields.querySelector(".dimension-association-details");
  fields.insertBefore(wrapper, association || null);
}

async function interpretDimensionForRow(input, output, button) {
  const text = input.value.trim();
  if (!text) return;
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Interpreting…";
  output.textContent = "Checking explicit dimension syntax…";
  try {
    const response = await fetch("/api/interpret-dimension", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "Dimension interpretation failed.");
    const row = input.closest(".dimension-text-item");
    if (result.status === "parsed" && result.dimension_type === "linear" && row) {
      row.dataset.parsedValueMm = result.value_mm;
      row.dataset.dimensionType = result.dimension_type;
    } else if (row) {
      delete row.dataset.parsedValueMm;
      delete row.dataset.dimensionType;
    }
    refreshWallDimensionOptions();
    if (result.status === "parsed") {
      output.textContent = "Interpretation: " + result.value_mm + " mm (" + result.dimension_type +
        ", source unit " + result.unit + "). Check this against the original drawing; it is not verified.";
    } else if (result.status === "unit_missing") {
      output.textContent = "Number detected: " + (result.value || text) +
        ". No unit is written, so Planline has not converted it to millimetres.";
    } else if (result.status === "ambiguous") {
      output.textContent = "Ambiguous number format. Planline will not guess whether the separator is decimal or thousands.";
    } else {
      output.textContent = "No supported dimension format recognised. " + (result.reason || "Review the text manually.");
    }
    output.dataset.status = result.status;
  } catch (error) {
    output.textContent = "Could not interpret dimension: " + (error.message || "Local API unavailable.");
    output.dataset.status = "error";
  } finally {
    button.textContent = originalText;
    button.disabled = !input.value.trim();

  }
}

function renderDrawingDatasetOptions() {
  const select = $("#drawingDatasetSelect");
  if (!select) return;
  const previous = select.value;
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = state.ocrDatasets.length ? "Choose a local dataset…" : "No datasets yet — create one in OCR Studio";
  select.append(placeholder);
  state.ocrDatasets.forEach((dataset) => {
    const option = document.createElement("option");
    option.value = dataset.dataset_id;
    option.textContent = dataset.dataset_id + " · " + (dataset.summary?.samples || 0) + " crops";
    select.append(option);
  });
  if (state.ocrDatasets.some((dataset) => dataset.dataset_id === previous)) select.value = previous;
  select.disabled = state.ocrDatasets.length === 0;
  if (!state.ocrDatasets.length) {
    $("#datasetCaptureStatus").textContent = "Create an OCR dataset in OCR Studio before saving crops. Only verified crops are copied; the full drawing is not uploaded.";
  } else {
    $("#datasetCaptureStatus").textContent = "Choose a dataset, keep the source ID consistent across pages from the same drawing, and save only transcriptions you have checked.";
  }
  updateDatasetCaptureButtons();
}

function updateDatasetCaptureButtons() {
  const selectedDataset = $("#drawingDatasetSelect")?.value || "";
  const sourceId = $("#drawingSourceId")?.value.trim() || "";
  const ready = Boolean(selectedDataset && sourceId);
  document.querySelectorAll(".dimension-text-item").forEach((row) => {
    const button = row.querySelector(".save-dimension-crop");
    if (!button || row.dataset.savedCropId) return;
    const text = row.querySelector(".dimension-text-value")?.value.trim() || "";
    const verified = row.querySelector(".dimension-text-verified-input")?.checked;
    const hasCrop = Boolean(row.querySelector(".dimension-text-crop"));
    button.disabled = !ready || !text || !verified || !hasCrop;
    button.title = !selectedDataset
      ? "Choose or create an OCR dataset first."
      : !sourceId
        ? "Enter a source drawing ID so related crops stay grouped."
        : !verified
          ? "Verify the transcription against the source drawing first."
          : "";
  });
}

async function saveDimensionCropToDataset(region, row, button) {
  const datasetId = $("#drawingDatasetSelect").value;
  const text = row.querySelector(".dimension-text-value").value.trim();
  const verified = row.querySelector(".dimension-text-verified-input").checked;
  const sourceId = $("#drawingSourceId").value.trim();
  const writerId = $("#drawingWriterId").value.trim();
  if (!region.crop_data_url || !datasetId || !text || !verified || !sourceId) {
    updateDatasetCaptureButtons();
    return;
  }
  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = "Saving crop…";
  $("#datasetCaptureStatus").textContent = "Saving only this verified dimension crop to the selected local dataset…";
  try {
    const cropResponse = await fetch(region.crop_data_url);
    if (!cropResponse.ok) throw new Error("The dimension crop could not be read.");
    const cropBlob = await cropResponse.blob();
    const form = new FormData();
    form.append("file", cropBlob, "dimension-crop.png");
    form.append("text", text);
    form.append("source_id", sourceId);
    form.append("writer_id", writerId);
    form.append("text_style", row.querySelector(".dimension-text-style").value);
    form.append("verified", "true");
    const response = await fetch("/api/ocr/datasets/" + encodeURIComponent(datasetId) + "/samples", {
      method: "POST",
      body: form
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "The crop could not be saved.");
    row.dataset.savedCropId = payload.crop_id || "saved";
    button.textContent = "Saved to " + datasetId;
    button.disabled = true;
    $("#datasetCaptureStatus").textContent = "Saved one verified crop. The source drawing was not uploaded; source ID " + sourceId + " keeps related crops grouped.";
    state.ocrDatasets = state.ocrDatasets.map((dataset) => dataset.dataset_id === datasetId
      ? { ...dataset, summary: { ...dataset.summary, samples: (dataset.summary?.samples || 0) + 1 } }
      : dataset);
    renderDrawingDatasetOptions();
    $("#drawingDatasetSelect").value = datasetId;
  } catch (error) {
    button.textContent = originalText;
    $("#datasetCaptureStatus").textContent = "Could not save crop: " + (error.message || "Local OCR dataset unavailable.");
    updateDatasetCaptureButtons();
  }
}

function updateOcrControls() {
  if (!$("#runOcrButton")) return;
  const hasCandidates = Boolean(state.result?.dimension_regions?.length);
  $("#runOcrButton").disabled = !state.ocrReady || !hasCandidates || state.ocrRunning || !$("#ocrModelSelect").value;
  if (!state.ocrReady) {
    $("#ocrAssistStatus").textContent = PREVIEW_MODE
      ? "OCR is disabled in this static UI preview. No recognition or training runs here."
      : "Optional PaddleOCR runtime not detected. Manual transcription and dataset tools remain available.";
  } else if (state.ocrRunning) {
    $("#ocrAssistStatus").textContent = "Recognising dimension crops…";
  } else if (!hasCandidates) {
    $("#ocrAssistStatus").textContent = "Analyse a drawing with dimension candidates to run OCR.";
  } else {
    $("#ocrAssistStatus").textContent = "OCR runs automatically after analysis. Check each reading before verifying it.";
  }
}

async function loadOcrCapabilities() {
  if (PREVIEW_MODE) {
    state.ocrReady = false;
    state.ocrModels = [];
    state.ocrDatasets = [];
    state.ocrCapabilitiesLoaded = true;
    updateOcrControls();
    return;
  }
  try {
    const [statusResponse, modelsResponse, datasetsResponse] = await Promise.all([
      fetch("/api/ocr/status"),
      fetch("/api/ocr/models"),
      fetch("/api/ocr/datasets")
    ]);
    if (!statusResponse.ok || !modelsResponse.ok || !datasetsResponse.ok) throw new Error("OCR status endpoint unavailable.");
    const status = await statusResponse.json();
    const ocrDeviceSelect = $("#ocrDeviceSelect");
    const gpuOption = ocrDeviceSelect?.querySelector('option[value="gpu:0"]');
    if (gpuOption) gpuOption.disabled = !Boolean(status.paddle_cuda_available);
    if (ocrDeviceSelect && !status.paddle_cuda_available && ocrDeviceSelect.value === "gpu:0") {
      ocrDeviceSelect.value = "cpu";
    }
    const modelPayload = await modelsResponse.json();
    const datasetPayload = await datasetsResponse.json();
    state.ocrDatasets = Array.isArray(datasetPayload.datasets) ? datasetPayload.datasets : [];
    renderDrawingDatasetOptions();
    state.ocrReady = Boolean(status.inference_runtime_ready ?? (status.paddle_installed && status.paddleocr_installed));
    state.ocrModels = Array.isArray(modelPayload.models) ? modelPayload.models : [];
    const select = $("#ocrModelSelect");
    select.replaceChildren();
    state.ocrModels.forEach((model) => {
      const option = document.createElement("option");
      option.value = model.model_id;
      option.textContent = model.label + (model.kind === "trained" ? " · fine-tuned" : " · base");
      select.append(option);
    });
    if (state.ocrModelId && state.ocrModels.some((model) => model.model_id === state.ocrModelId)) {
      select.value = state.ocrModelId;
    }
    if (!state.ocrModels.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No recognisers available";
      select.append(option);
    }
  } catch (error) {
    state.ocrReady = false;
    $("#ocrAssistStatus").textContent = error.message || "OCR status unavailable.";
  }
  state.ocrCapabilitiesLoaded = true;
  updateOcrControls();
}

async function runOcrOnCandidates() {
  if (!state.file || !state.result || !state.ocrReady || state.ocrRunning || !$("#ocrModelSelect").value) return;
  state.ocrRunning = true;
  document.querySelectorAll(".ocr-suggestion").forEach((node) => node.remove());
  updateOcrControls();
  state.ocrModelId = $("#ocrModelSelect").value;
  state.ocrDevice = $("#ocrDeviceSelect").value;
  const form = new FormData();
  form.append("file", state.file);
  form.append("review_json", JSON.stringify(buildReviewObject()));
  form.append("model_id", state.ocrModelId);
  form.append("device", state.ocrDevice);
  try {
    const response = await fetch("/api/ocr/recognize-review", { method: "POST", body: form });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "OCR failed (HTTP " + response.status + ").");
    state.ocrPredictions = {};
    (payload.predictions || []).forEach((prediction) => {
      state.ocrPredictions[prediction.detection_id] = prediction;
      const row = [...document.querySelectorAll(".dimension-text-item")]
        .find((item) => item.dataset.detectionId === prediction.detection_id);
      if (row) showOcrSuggestion(row, prediction);
    });
    const recognised = Object.values(state.ocrPredictions).filter((item) => item.text).length;
    $("#ocrAssistStatus").textContent = recognised + " text suggestions returned. None are verified automatically.";
    showNotice("OCR suggestions ready", recognised + " candidates returned text. Check the original crops before accepting or verifying them.");
  } catch (error) {
    showNotice("OCR could not complete", error.message || "Check the optional PaddleOCR runtime.");
    $("#ocrAssistStatus").textContent = error.message || "OCR failed.";
  } finally {
    state.ocrRunning = false;
    updateOcrControls();
  }
}

$("#runOcrButton").addEventListener("click", runOcrOnCandidates);

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
  updateWorkflow("analyse");
  state.controller = controller;
  const button = $("#analyzeButton");
  button.disabled = true;
  button.textContent = "Analysing…";
  // Do not leave results from an earlier run visible if this run fails.
  state.result = null; state.previewUrl = null; state.detections = []; state.selectedId = null;
  $("#exportReview").disabled = true;
  $("#saveProject").disabled = true;
  $("#overlay").classList.add("hidden");
  $("#summary").classList.add("hidden");
  $("#detectionList").innerHTML = "";
  $("#selectedDetection").classList.add("hidden");
  $("#noDetectionMatches").classList.add("hidden");
  clearDimensionTextReview();
  state.ocrPredictions = {};
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
    form.append("brightness", $("#brightnessControl").value);
    form.append("contrast", $("#contrastControl").value);
    const response = await fetch("/api/analyze", { method: "POST", body: form, signal: controller.signal });
    const payload = await response.json().catch(() => ({}));
    if (state.controller !== controller) return;
    if (!response.ok) throw new Error(payload.detail || "Analysis failed (HTTP " + response.status + ").");
    state.result = payload;
    $("#detectStep").classList.add("complete");
    renderResults(payload);
    updateWorkflow("review");
    $("#geometryDetails").open = true;
    if (state.ocrCapabilitiesPromise) await state.ocrCapabilitiesPromise;
    if (state.result === payload && state.ocrReady && payload.dimension_regions?.length) {
      void runOcrOnCandidates();
    }
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

function buildReviewObject() {
  if (!state.result) return null;
  const result = state.result;
  const review = {
    schema_version: "planline-detection-review/v1",
    generated_at: new Date().toISOString(),
    source: {
      filename: state.file?.name || null,
      page_index: result.source?.page_index ?? 0,
      image_width_px: result.image.width,
      image_height_px: result.image.height
    },
    calibration: state.calibration.applied ? { ...state.calibration.applied } : null,
    analysis: {
      model: "yolo_floorplan.pt",
      confidence_threshold: result.confidence_threshold ?? 0.25,
      status: state.reconstruction ? "dimension_constrained_wall_edge_draft" : "candidate_detection_only",
      preprocessing: result.preprocessing || { brightness: 0, contrast: 1, method: "linear_intensity_only" },
      ocr_model_id: state.ocrModelId,
      ocr_device: state.ocrDevice,
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
    manual_geometry: state.geometry.segments.map((segment) => ({ ...segment })),
    manual_rooms: state.geometry.rooms.map((room) => ({ ...room })),
    reconstruction: state.reconstruction ? { ...state.reconstruction } : null,
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
        parsed_value_mm: textInputs[index]?.closest(".dimension-text-item")?.dataset.parsedValueMm || null,
        dimension_type: textInputs[index]?.closest(".dimension-text-item")?.dataset.dimensionType || null,
        text_style: document.querySelectorAll(".dimension-text-style")[index]?.value || "unknown",
        verified: verifiedInputs[index]?.checked || false,
        detector_confidence: region.confidence,
        bbox: region.bbox,
        crop_bbox: region.crop_bbox || null,
        ocr_suggestion: state.ocrPredictions[region.id] || null,
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
      Object.keys(state.ocrPredictions).length
        ? "OCR suggestions are machine-generated and remain unverified until a user checks the original crop."
        : "No OCR has been performed; manual transcription entries are user-entered and not machine-verified.",
      "Geometric association suggestions are axis-aligned box hypotheses; only explicitly confirmed line and wall-pair selections are marked as reviewed.",
      state.calibration.applied
        ? "A two-point scale was supplied by the user and recorded as pixels per millimetre; it is not an independently verified measurement or validated geometry."
        : "No pixel-to-unit scale or measured geometry has been inferred.",
      "Bounding boxes are detector candidates, not measured wall geometry.",
      "Manual wall segments are user-created linework and have not been independently validated or topologically connected.",
      state.reconstruction
        ? "Dimension-constrained detected wall-face edges are included as editable draft geometry. They are not topologically joined or certified, and no room, opening or diagonal-wall reconstruction is included."
        : "No dimension-constrained CAD geometry has been generated."
    ]
  };
  return review;
}

function exportReviewJson() {
  const review = buildReviewObject();
  if (!review) return;
  const safeStem = (state.file?.name || "drawing")
    .replace(/\.[^.]+$/, "")
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .slice(0, 60) || "drawing";
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

async function encodeFileBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function decodeFileBase64(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

async function saveProject() {
  if (!state.file || !state.result) return;
  const review = buildReviewObject();
  if (!review) return;
  const project = {
    format: "planline-project",
    format_version: 1,
    created_at: new Date().toISOString(),
    source: {
      filename: state.file.name,
      mime_type: state.file.type || "application/octet-stream",
      last_modified: state.file.lastModified || Date.now(),
      size_bytes: state.file.size,
      data_base64: await encodeFileBase64(state.file)
    },
    analysis_result: state.result,
    geometry: state.geometry.segments,
    reconstruction: state.reconstruction,
    geometry_next_id: state.geometry.nextId,
    rooms: state.geometry.rooms,
    room_next_id: state.geometry.nextRoomId,
    review
  };
  const safeStem = (state.file.name || "drawing")
    .replace(/\.[^.]+$/, "")
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .slice(0, 60) || "drawing";
  const blob = new Blob([JSON.stringify(project)], { type: "application/vnd.planline.project+json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = safeStem + ".planline";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1500);
  showNotice("Project saved", "The source file, analysis, manual review and scale reference were packaged into a local .planline file. Nothing was uploaded.");
}

function restoreProjectReview(review) {
  const entries = review?.manual_dimension_text_review || [];
  state.ocrModelId = review?.analysis?.ocr_model_id || null;
  state.ocrDevice = review?.analysis?.ocr_device || null;
  if (state.ocrModelId && [...$("#ocrModelSelect").options].some((option) => option.value === state.ocrModelId)) {
    $("#ocrModelSelect").value = state.ocrModelId;
  }
  if (state.ocrDevice && [...$("#ocrDeviceSelect").options].some((option) => option.value === state.ocrDevice)) {
    $("#ocrDeviceSelect").value = state.ocrDevice;
  }
  entries.forEach((entry, index) => {
    const textInput = document.querySelectorAll(".dimension-text-value")[index];
    const styleInput = document.querySelectorAll(".dimension-text-style")[index];
    const verifiedInput = document.querySelectorAll(".dimension-text-verified-input")[index];
    const lineSelect = document.querySelectorAll(".dimension-line-select")[index];
    const spanSelect = document.querySelectorAll(".dimension-wall-span-select")[index];
    const associationVerified = document.querySelectorAll(".dimension-association-verified-input")[index];
    if (textInput) textInput.value = entry.raw_text || "";
    if (styleInput) styleInput.value = entry.text_style || "unknown";
    if (verifiedInput) verifiedInput.checked = Boolean(entry.verified);
    if (textInput && entry.parsed_value_mm && entry.dimension_type === "linear") {
      const row = textInput.closest(".dimension-text-item");
      row.dataset.parsedValueMm = entry.parsed_value_mm;
      row.dataset.dimensionType = "linear";
      const scaleButton = row.querySelector(".use-dimension-scale");
      if (scaleButton) scaleButton.disabled = !verifiedInput?.checked;
    }
    if (entry.ocr_suggestion && typeof entry.ocr_suggestion === "object") {
      state.ocrPredictions[entry.detection_id] = entry.ocr_suggestion;
      const row = [...document.querySelectorAll(".dimension-text-item")]
        .find((item) => item.dataset.detectionId === entry.detection_id);
      if (row) showOcrSuggestion(row, entry.ocr_suggestion);
    }
    const association = entry.association || {};
    if (lineSelect && association.dimension_line_id) {
      lineSelect.value = association.dimension_line_id;
      lineSelect.dispatchEvent(new Event("change", { bubbles: true }));
      const candidate = (association.candidate_lines || []).find(
        (item) => item.dimension_line_id === association.dimension_line_id
      );
      const targetWallIds = JSON.stringify(association.wall_ids || []);
      const spanIndex = (candidate?.wall_spans || []).findIndex(
        (span) => JSON.stringify(span.wall_ids || []) === targetWallIds
      );
      if (spanSelect && spanIndex >= 0) {
        spanSelect.value = String(spanIndex);
        spanSelect.dispatchEvent(new Event("change", { bubbles: true }));
        if (associationVerified) {
          associationVerified.checked = Boolean(association.confirmed);
          associationVerified.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
    }
  });
  if (review?.calibration) {
    state.calibration = {
      points: (review.calibration.points_px || []).map((point) => ({ x: point.x, y: point.y })),
      picking: false,
      applied: { ...review.calibration }
    };
    $("#calibrationDistance").value = String(review.calibration.known_distance);
    $("#calibrationUnit").value = review.calibration.input_unit;
    $("#calibrationResult").textContent = review.calibration.method === "verified_dimension_association"
      ? "Restored scale from confirmed match " + (review.calibration.reference_dimension_text || review.calibration.known_distance_mm + " mm") + "."
      : review.calibration.method === "verified_dimension_two_point_reference"
        ? "Restored scale from verified dimension " + (review.calibration.reference_dimension_text || review.calibration.known_distance_mm + " mm") + "."
        : Number(review.calibration.pixel_distance).toFixed(1) + " px / " +
          Number(review.calibration.known_distance_mm).toLocaleString(undefined, { maximumFractionDigits: 3 }) +
          " mm = " + Number(review.calibration.pixels_per_mm).toFixed(6) +
          " px/mm. Restored manual reference.";
    renderCalibrationStatus();
    drawDetections(state.previewUrl, state.detections, state.result.image);
  } else {
    clearCalibration();
  }
}

function isValidProjectGeometry(project) {
  const segments = project.geometry ?? [];
  const rooms = project.rooms ?? [];
  if (!Array.isArray(segments) || !Array.isArray(rooms)) return false;
  if (project.geometry_next_id !== undefined &&
      (!Number.isInteger(project.geometry_next_id) || project.geometry_next_id < 1)) return false;
  if (project.room_next_id !== undefined &&
      (!Number.isInteger(project.room_next_id) || project.room_next_id < 1)) return false;
  const ids = new Set();
  const pageIndex = project.analysis_result.source?.page_index ?? 0;
  const inBounds = (point) => point && Number.isFinite(point.x) && Number.isFinite(point.y) &&
    point.x >= 0 && point.y >= 0 &&
    point.x <= project.analysis_result.image.width &&
    point.y <= project.analysis_result.image.height;
  const validSegments = segments.every((segment) => {
    const manual = segment?.created_by_user === true && /^manual-wall-[0-9]{3,}$/.test(segment.id || "");
    const reconstructed = segment?.created_by_reconstruction === true &&
      /^reconstructed-wall-[0-9]{4,}$/.test(segment.id || "") &&
      typeof segment.source_detection_id === "string" &&
      Number.isFinite(segment.detector_confidence) &&
      segment.detector_confidence >= 0 && segment.detector_confidence <= 1 &&
      ["horizontal", "vertical"].includes(segment.wall_orientation);
    if (!segment || typeof segment.id !== "string" || (!manual && !reconstructed) ||
        ids.has(segment.id) || segment.type !== "wall_segment" ||
        !Number.isInteger(segment.source_page_index) || segment.source_page_index !== pageIndex) return false;
    ids.add(segment.id);
    return inBounds(segment.start_px) && inBounds(segment.end_px) &&
      Math.hypot(segment.end_px.x - segment.start_px.x, segment.end_px.y - segment.start_px.y) >= 3;
  });
  if (!validSegments) return false;
  return rooms.every((room) => {
    if (!room || typeof room.id !== "string" || !/^manual-room-[0-9]{3,}$/.test(room.id) ||
        ids.has(room.id) || room.type !== "room_polygon" || room.created_by_user !== true ||
        !Number.isInteger(room.source_page_index) || room.source_page_index !== pageIndex ||
        !Array.isArray(room.vertices_px) || room.vertices_px.length < 3 ||
        !room.vertices_px.every(inBounds)) return false;
    ids.add(room.id);
    return isSimplePolygon(room.vertices_px) && polygonAreaPx2(room.vertices_px) >= 9;
  });
}

async function openProjectFile(file) {
  if (!file) return;
  if (file.size > 100 * 1024 * 1024) {
    showNotice("Project file is too large", "Planline project files are limited to 100 MB.");
    return;
  }
  try {
    const project = JSON.parse(await file.text());
    if (project.format !== "planline-project" || project.format_version !== 1 ||
        !project.source?.filename || !project.source?.data_base64 ||
        !project.analysis_result?.image || !Array.isArray(project.analysis_result.detections) ||
        !project.analysis_result.preview_data_url || !project.review ||
        !Array.isArray(project.review.manual_dimension_text_review) ||
        !isValidProjectGeometry(project) ||
        !/\\.(png|jpe?g|webp|tiff?|pdf)$/i.test(project.source.filename) ||
        !Number.isInteger(project.source.size_bytes) || project.source.size_bytes < 1 || project.source.size_bytes > 25 * 1024 * 1024 ||
        !Number.isFinite(project.analysis_result.image.width) || project.analysis_result.image.width < 1 ||
        !Number.isFinite(project.analysis_result.image.height) || project.analysis_result.image.height < 1) {
      throw new Error("This is not a supported Planline project file.");
    }
    const bytes = decodeFileBase64(project.source.data_base64);
    if (project.source.size_bytes && bytes.byteLength !== project.source.size_bytes) {
      throw new Error("The embedded source drawing failed its size check.");
    }
    const sourceFile = new File([bytes], project.source.filename, {
      type: project.source.mime_type || "application/octet-stream",
      lastModified: project.source.last_modified || Date.now()
    });
    setFile(sourceFile);
    state.result = project.analysis_result;
    state.geometry.segments = Array.isArray(project.geometry) ? project.geometry : [];
    state.reconstruction = project.reconstruction && typeof project.reconstruction === "object"
      ? project.reconstruction : null;
    $("#reconstructionStatus").textContent = state.reconstruction
      ? "Restored " + (state.reconstruction.segments?.length || 0) +
        " generated wall-face edges. Inspect them before exporting."
      : "Analyse a drawing, verify horizontal and vertical dimensions, and confirm their wall pairs.";
    $("#reconstructionStatus").dataset.state = state.reconstruction ? "warning" : "";
    state.geometry.nextId = Number.isInteger(project.geometry_next_id) ? project.geometry_next_id : state.geometry.segments.length + 1;
    state.geometry.rooms = Array.isArray(project.rooms) ? project.rooms : [];
    state.geometry.nextRoomId = Number.isInteger(project.room_next_id) ? project.room_next_id : state.geometry.rooms.length + 1;
    state.geometry.selectedId = null;
    state.geometry.pendingPoint = null;
    state.previewUrl = project.analysis_result.preview_data_url;
    state.detections = project.analysis_result.detections || [];
    renderResults(state.result);
    updateWorkflow("review");
    $("#geometryDetails").open = true;
    renderGeometryControls();
    restoreProjectReview(project.review);
    $("#saveProject").disabled = false;
    showNotice("Project opened", "The source drawing, previous analysis, manual transcriptions, associations and calibration were restored locally.");
  } catch (error) {
    showNotice("Could not open project", error.message || "The project file is damaged or uses an unsupported version.");
  } finally {
    $("#projectInput").value = "";
  }
}

$("#saveProject").addEventListener("click", saveProject);
$("#openProject").addEventListener("click", () => $("#projectInput").click());
$("#projectInput").addEventListener("change", (event) => openProjectFile(event.target.files?.[0]));

$("#exportReview").addEventListener("click", exportReviewJson);
$("#brightnessControl").addEventListener("input", () => {
  $("#brightnessValue").textContent = $("#brightnessControl").value;
});
$("#contrastControl").addEventListener("input", () => {
  $("#contrastValue").textContent = Number($("#contrastControl").value).toFixed(2) + "×";
});
$("#resetImageCleanup").addEventListener("click", () => {
  $("#brightnessControl").value = "0";
  $("#contrastControl").value = "1";
  $("#brightnessValue").textContent = "0";
  $("#contrastValue").textContent = "1.00×";
});
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
  if (result.candidate_available && result.candidate_index !== null) {
    const proposal = document.createElement("div");
    proposal.className = "chain-candidate";
    const explanation = document.createElement("p");
    explanation.textContent = "Calculated candidate for Segment " + (result.candidate_index + 1) +
      ": " + result.candidate_value + " " + result.unit +
      ". This is arithmetic only; it is not independently verified.";
    const apply = document.createElement("button");
    apply.className = "toolbar-button";
    apply.type = "button";
    apply.textContent = "Use candidate in Segment " + (result.candidate_index + 1);
    apply.addEventListener("click", () => {
      const row = $("#chainSegments").querySelectorAll(".chain-segment-row")[result.candidate_index];
      if (!row) return;
      row.querySelector(".segment-value").value = result.candidate_value;
      row.querySelector(".segment-verified").checked = false;
      row.querySelector(".segment-value").focus();
      apply.disabled = true;
      apply.textContent = "Added — verify this value manually";
    });
    proposal.append(explanation, apply);
    box.append(proposal);
  } else if (result.candidate_reason && result.unresolved_indices.length) {
    const line = document.createElement("p");
    line.textContent = "Cannot calculate a candidate: " + result.candidate_reason;
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
if (PREVIEW_MODE) {
  $("#apiStatus").textContent = "Static UI preview · backend disabled";
  $(".local-dot").classList.add("preview-mode");
} else {
  fetch("/api/health").then((r) => r.json()).then((health) => {
    const meta = $(".top-meta");
    if (health.status === "ok") {
      $("#apiStatus").textContent = (health.detector_weights_present ? "Detector ready" : "Detector missing") + " · " + (health.ocr_available ? "OCR ready" : "OCR runtime missing") + " · " + (health.dimension_association_available ? "dimension matching ready" : "dimension matching unavailable");
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
}

$("#drawingDatasetSelect").addEventListener("change", updateDatasetCaptureButtons);
$("#drawingSourceId").addEventListener("input", updateDatasetCaptureButtons);
state.ocrCapabilitiesPromise = loadOcrCapabilities();

const $ = (selector) => document.querySelector(selector);
const state = { file: null, objectUrl: null, result: null, previewUrl: null, detections: [], selectedId: null, activeFilter: "all", overlayVisible: true, resizeObserver: null, resizeHandler: null, controller: null, zoom: 1 };

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
  $("#fileInput").value = "";
  $("#fileCard").classList.add("hidden");
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
  $("#imageDimensions").textContent = "Waiting for analysis";
  $("#detectionCount").textContent = "0 detected regions";
  $("#resultStatus").textContent = "NOT ANALYSED";
  $("#summary").classList.add("hidden");
  $("#detectionList").innerHTML = "";
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
function renderResults(payload) {
  const detections = payload.detections || [];
  $("#exportReview").disabled = false;
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
  if (payload.source && payload.source.note) showNotice("Detection finished — first PDF page only", notes + " " + payload.source.note);
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
    textInput.addEventListener("input", () => {
      region.manual_text = textInput.value;
    });
    textLabel.append(textInput);

    const verifiedLabel = document.createElement("label");
    verifiedLabel.className = "dimension-text-verified";
    const verifiedInput = document.createElement("input");
    verifiedInput.className = "dimension-text-verified-input";
    verifiedInput.type = "checkbox";
    verifiedInput.addEventListener("change", () => {
      region.manual_verified = verifiedInput.checked;
    });
    verifiedLabel.append(verifiedInput, document.createTextNode(" I checked this transcription"));

    fields.append(meta, textLabel, verifiedLabel);
    row.append(fields);
    container.append(row);
  });
}

function renderDetectionRows(detections) {
  document.querySelectorAll(".detection-row").forEach((row) => {
    const visible = state.activeFilter === "all" || row.dataset.className === state.activeFilter;
    row.classList.toggle("hidden", !visible);
    const selected = row.dataset.detectionId === state.selectedId;
    row.classList.toggle("selected", selected);
    row.setAttribute("aria-pressed", selected ? "true" : "false");
  });
}

$("#classFilter").addEventListener("change", (event) => {
  state.activeFilter = event.target.value;
  renderDetectionRows(state.detections || []);
  if (state.result) drawDetections(state.previewUrl, state.detections, state.result.image);
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
    manual_dimension_text_review: (result.dimension_regions || []).map((region) => ({
        detection_id: region.id,
        raw_text: region.manual_text || "",
        verified: Boolean(region.manual_verified),
        detector_confidence: region.confidence,
        bbox: region.bbox,
        crop_bbox: region.crop_bbox || null
      })),
    limitations: [
      "No OCR has been performed; manual transcription entries are user-entered and not machine-verified.",
      "No dimension-to-wall association, scale calibration or geometric reconstruction has been performed.",
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

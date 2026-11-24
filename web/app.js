const $ = (selector) => document.querySelector(selector);
const state = { file: null, objectUrl: null, result: null, previewUrl: null, detections: [], selectedId: null, activeFilter: "all", overlayVisible: true, resizeObserver: null, resizeHandler: null };

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function setFile(file) {
  if (!file) return;
  const allowed = /\.(png|jpe?g|webp|tiff?)$/i.test(file.name) || /\.pdf$/i.test(file.name);
  if (!allowed) return showNotice("Unsupported file type", "Choose a PNG, JPG, WEBP, TIFF or PDF drawing.");
  if (file.size > 25 * 1024 * 1024) return showNotice("File is too large", "The maximum upload size is 25 MB.");
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.file = file;
  state.objectUrl = URL.createObjectURL(file);
  state.result = null;
  state.selectedId = null;
  state.detections = [];
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
  showNotice("Drawing ready", "Run local detection to locate candidate walls and dimension annotations. No measurements will be inferred.");
  if (file.type.startsWith("image/")) {
    const img = $("#previewImage");
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

function drawDetections(previewUrl, detections, imageSize) {
  const img = $("#previewImage");
  const canvas = $("#overlay");
  const wrap = $("#canvasWrap");
  state.previewUrl = previewUrl;
  state.detections = detections;
  state.imageSize = imageSize;
  const paint = () => {
    if (!img.complete || !img.naturalWidth || img.classList.contains("hidden")) return;
    const imageRect = img.getBoundingClientRect();
    const wrapRect = wrap.getBoundingClientRect();
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    canvas.style.width = imageRect.width + "px";
    canvas.style.height = imageRect.height + "px";
    canvas.style.left = (imageRect.left - wrapRect.left + wrap.scrollLeft) + "px";
    canvas.style.top = (imageRect.top - wrapRect.top + wrap.scrollTop) + "px";
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const sx = img.naturalWidth / imageSize.width;
    const sy = img.naturalHeight / imageSize.height;
    detections.forEach((d) => {
      if (state.activeFilter !== "all" && d.class_name !== state.activeFilter) return;
      const b = d.bbox;
      const selected = state.selectedId === d.id;
      ctx.strokeStyle = selected ? "#d34e3e" : d.class_name === "wall" ? "#287c56" : d.class_name === "dimension_value" ? "#c47734" : "#4778a8";
      ctx.lineWidth = selected ? Math.max(4, canvas.width / 450) : Math.max(2, canvas.width / 700);
      ctx.strokeRect(b.x1 * sx, b.y1 * sy, b.width * sx, b.height * sy);
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
  const notes = (payload.notes || []).join(" ");
  showNotice(detections.length ? "Detection finished — OCR has not run" : "No candidate regions detected", detections.length ? notes : "The model returned no boxes at its current confidence threshold. This does not prove that the drawing contains no walls or dimensions. " + notes);
  if (payload.source && payload.source.note) showNotice("Detection finished — first PDF page only", notes + " " + payload.source.note);
  if (payload.preview_data_url) drawDetections(payload.preview_data_url, detections, payload.image);
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
$("#overlayToggle").addEventListener("click", () => {
  state.overlayVisible = !state.overlayVisible;
  $("#overlayToggle").textContent = state.overlayVisible ? "Hide boxes" : "Show boxes";
  $("#overlay").classList.toggle("hidden", !state.overlayVisible);
});

async function analyse() {
  if (!state.file) return;
  const button = $("#analyzeButton");
  button.disabled = true;
  button.textContent = "Analysing…";
  $("#loader").classList.remove("hidden");
  $("#detectStep").classList.remove("complete");
  try {
    const form = new FormData();
    form.append("file", state.file);
    const response = await fetch("/api/analyze", { method: "POST", body: form });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "Analysis failed (HTTP " + response.status + ").");
    state.result = payload;
    $("#detectStep").classList.add("complete");
    renderResults(payload);
  } catch (error) {
    $("#detectStep").classList.remove("complete");
    showNotice("Analysis could not be completed", error.message || "Check that the local API is running.");
    $("#resultStatus").textContent = "ANALYSIS FAILED";
  } finally {
    $("#loader").classList.add("hidden");
    button.disabled = false;
    button.innerHTML = 'Analyse again <span>→</span>';
  }
}

$("#fileInput").addEventListener("change", (event) => setFile(event.target.files[0]));
$("#analyzeButton").addEventListener("click", analyse);
$("#removeFile").addEventListener("click", () => {
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.file = null; state.objectUrl = null; state.result = null; state.detections = []; state.previewUrl = null; state.selectedId = null;
  $("#fileInput").value = "";
  $("#fileCard").classList.add("hidden");
  $("#dropzone").classList.remove("hidden");
  $("#analyzeButton").disabled = true;
  $("#analyzeButton").innerHTML = "Analyse drawing <span>→</span>";
  $("#detectStep").classList.remove("complete");
  $("#sourceState").textContent = "Waiting";
  $("#drawingTitle").textContent = "No drawing loaded";
  $("#viewTag").textContent = "EMPTY CANVAS";
  $("#previewImage").classList.add("hidden");
  $("#overlay").classList.add("hidden");
  $("#emptyState").classList.remove("hidden");
  $("#imageDimensions").textContent = "No source dimensions";
  $("#detectionCount").textContent = "0 detected regions";
  $("#summary").classList.add("hidden");
  $("#detectionList").innerHTML = "";
  $("#resultStatus").textContent = "NOT ANALYSED";
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

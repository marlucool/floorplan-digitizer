const $ = (selector) => document.querySelector(selector);
const state = { file: null, objectUrl: null, result: null, previewUrl: null };

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function clearDrawing() {
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state = { file: null, objectUrl: null, result: null, previewUrl: null };
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
  $("#overlay").classList.add("hidden");
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
  img.src = previewUrl;
  img.classList.remove("hidden");
  $("#emptyState").classList.add("hidden");
  img.onload = () => {
    const rect = img.getBoundingClientRect();
    const scaleX = img.naturalWidth / imageSize.width;
    const scaleY = img.naturalHeight / imageSize.height;
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    canvas.style.width = rect.width + "px";
    canvas.style.height = rect.height + "px";
    canvas.style.left = img.offsetLeft + "px";
    canvas.style.top = img.offsetTop + "px";
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    detections.forEach((d) => {
      const b = d.bbox;
      const x = b.x1 / scaleX, y = b.y1 / scaleY;
      const w = b.width / scaleX, h = b.height / scaleY;
      ctx.strokeStyle = d.class_name === "wall" ? "#287c56" : d.class_name === "dimension_value" ? "#c47734" : "#4778a8";
      ctx.lineWidth = Math.max(2, canvas.width / 700);
      ctx.strokeRect(x, y, w, h);
    });
    canvas.classList.remove("hidden");
  };
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
  if (!detections.length) {
    showNotice("No candidate regions detected", "The model returned no boxes at its current confidence threshold. This does not prove that the drawing contains no walls or dimensions.");
  }
  detections.forEach((d) => {
    const row = document.createElement("div");
    row.className = "detection-row";
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
    $("#detectionList").append(row);
  });
  const notes = (payload.notes || []).join(" ");
  showNotice("Detection finished — OCR has not run", notes);
  if (payload.preview_data_url) {
    drawDetections(payload.preview_data_url, detections, payload.image);
  }
}

async function analyse() {
  if (!state.file) return;
  const button = $("#analyzeButton");
  button.disabled = true;
  button.textContent = "Analysing…";
  $("#loader").classList.remove("hidden");
  $("#detectStep").classList.add("complete");
  try {
    const form = new FormData();
    form.append("file", state.file);
    const response = await fetch("/api/analyze", { method: "POST", body: form });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Analysis failed.");
    state.result = payload;
    renderResults(payload);
  } catch (error) {
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
  state.file = null; state.objectUrl = null; state.result = null;
  $("#fileInput").value = "";
  $("#fileCard").classList.add("hidden");
  $("#dropzone").classList.remove("hidden");
  $("#analyzeButton").disabled = true;
  $("#analyzeButton").textContent = "Analyse drawing →";
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
  if (!health.detector_weights_present) showNotice("Detector model missing", "The UI is available, but yolo_floorplan.pt must be present in the repository root before analysis can run.");
}).catch(() => showNotice("API unavailable", "Start the local Planline API to enable drawing analysis."));

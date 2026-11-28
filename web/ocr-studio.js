(() => {
  const $ = (selector) => document.querySelector(selector);
  const state = {
    datasets: [], datasetId: null, dataset: null, queue: [], queueIndex: 0,
    image: null, imageFile: null, cropBlob: null, cropRect: null,
    pointerStart: null, editingId: null, activeJobId: null, pollTimer: null,
    lastTrainedModel: null, busy: false, paddleReady: false, ocrReady: false,
    pythonCompatible: false, paddleGpuAvailable: false, trainingAssets: null
  };

  const terminalStatuses = new Set(["completed", "completed_no_export", "failed", "cancelled", "interrupted"]);

  function message(text, kind = "info") {
    const node = $("#annotationMessage");
    node.textContent = text;
    node.dataset.kind = kind;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(payload.detail)
        ? payload.detail.map((item) => item.msg || "Invalid input").join("; ")
        : payload.detail || `Request failed (${response.status})`;
      throw new Error(detail);
    }
    return payload;
  }

  function setView() {
    const studio = $("#ocrStudio");
    if (studio) studio.classList.remove("hidden");
    loadDatasets().then(restoreActiveJob).catch((error) => message(error.message, "error"));
  }

  async function restoreActiveJob() {
    if (window.PLANLINE_PREVIEW === true) return;
    try {
      const payload = await api("/api/ocr/jobs");
      const jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
      const active = jobs.find((job) => ["queued", "running"].includes(job.status));
      if (active) {
        beginJob(active, active.kind === "benchmark" ? "OCR benchmark" : "Fine-tuning dimension recogniser");
        message("Restored the running OCR job after reloading the workspace.", "success");
        return;
      }
      const interrupted = jobs.find((job) => job.status === "interrupted");
      if (interrupted) {
        $("#jobPanel").classList.remove("hidden");
        $("#jobTitle").textContent = interrupted.kind === "benchmark" ? "OCR benchmark" : "Fine-tuning dimension recogniser";
        $("#jobStatus").textContent = "INTERRUPTED";
        $("#jobLog").textContent = (interrupted.logs || "") + "\n" + (interrupted.error || "The application restarted before this job finished.");
        $("#jobProgressBar").style.width = "0%";
        $("#cancelJobButton").classList.add("hidden");
      }
    } catch (error) {
      message("Could not restore previous OCR job status: " + error.message, "error");
    }
  }

  function setBusy(busy) {
    state.busy = busy;
    $("#saveCropButton").disabled = busy || !state.cropBlob || !$("#sampleText").value.trim() || !$("#labelVerified").checked || Boolean(state.editingId);
    $("#saveCorrectionButton").disabled = busy || !state.editingId;
    $("#deleteSampleButton").disabled = busy || !state.editingId;
    $("#buildSplitsButton").disabled = busy || !state.dataset || state.dataset.summary.samples < 1;
    $("#auditDatasetButton").disabled = busy || !state.dataset;
    refreshTrainingButtons();
  }

  function refreshTrainingButtons() {
    const summary = state.dataset?.summary;
    const splitCounts = summary?.split_counts || {};
    const splitReady = Boolean(summary?.splits_present && splitCounts.train > 0 && splitCounts.validation > 0 && splitCounts.test > 0);
    const hasJob = Boolean(state.activeJobId);
    $("#auditDatasetButton").disabled = state.busy || !state.dataset;
    const assetsReady = Boolean(state.trainingAssets?.ready);
    $("#trainButton").disabled = state.busy || hasJob || !splitReady || !state.paddleReady || !assetsReady || summary?.valid === false;
    $("#prepareTrainingAssetsButton").disabled = state.busy || assetsReady || !state.paddleReady;
    $("#benchmarkBaseButton").disabled = state.busy || hasJob || !splitReady || !state.ocrReady || summary?.valid === false;
    const selectedModel = $("#trainedModelSelect")?.value || state.lastTrainedModel;
    $("#benchmarkTrainedButton").disabled = state.busy || hasJob || !splitReady || !state.ocrReady || !selectedModel;
    $("#cancelJobButton").classList.toggle("hidden", !hasJob);
    const readiness = $("#trainingReadiness");
    if (!state.pythonCompatible) readiness.textContent = "Compatible Python runtime required";
    else if (!state.paddleReady) readiness.textContent = "PaddlePaddle runtime not installed";
    else if (!assetsReady) readiness.textContent = "Prepare official training files";
    else if (!summary || !summary.samples) readiness.textContent = "Add verified crops to begin";
    else if (summary.independent_groups < 3) readiness.textContent = `${summary.samples} crops · need 3 independent groups`;
    else if (!splitReady) readiness.textContent = `${summary.samples} crops · build splits before training`;
    else readiness.textContent = `${summary.samples} crops · split plan ready`;
  }

  async function loadTrainingAssets() {
    const variant = $("#modelVariant").value;
    try {
      const assets = await api(`/api/ocr/training-assets?model_variant=${encodeURIComponent(variant)}`);
      state.trainingAssets = assets;
      $("#paddleSourcePath").value = assets.paddleocr_dir || "";
      $("#pretrainedPath").value = assets.pretrained_model || "";
      $("#prepareTrainingAssetsButton").disabled = state.busy || assets.ready || !state.paddleReady;
      $("#trainingAssetsStatus").textContent = assets.ready
        ? `Official PaddleOCR ${assets.source_version} source and ${variant} checkpoint are ready locally.`
        : "Training files are not downloaded yet. Prepare them once; subsequent training runs reuse the local files.";
    } catch (error) {
      state.trainingAssets = null;
      $("#prepareTrainingAssetsButton").disabled = state.busy;
      $("#trainingAssetsStatus").textContent = error.message;
    }
    refreshTrainingButtons();
  }

  async function loadDatasets(preferredId) {
    if (window.PLANLINE_PREVIEW === true) {
      $("#apiStatus").textContent = "Static OCR preview · backend disabled";
      $("#ocrDependencyNote").textContent = "Dataset storage, OCR inference and model training are disabled in the static preview. Run the desktop app to use OCR Studio.";
      $("#gpuAvailabilityNote").textContent = "GPU availability is not queried in the static preview.";
      $("#trainingAssetsStatus").textContent = "Training assets are not loaded in the static preview.";
      message("OCR datasets, model downloads and training are disabled in this static preview.", "info");
      refreshTrainingButtons();
      return;
    }
    try {
      const status = await api("/api/ocr/status");
      state.pythonCompatible = Boolean(status.python_compatible_for_paddle);
      state.paddleReady = Boolean(status.training_runtime_ready ?? (state.pythonCompatible && status.paddle_installed));
      state.ocrReady = Boolean(status.inference_runtime_ready ?? (state.pythonCompatible && status.paddle_installed && status.paddleocr_installed));
      state.paddleGpuAvailable = Boolean(status.paddle_cuda_available);
      $("#useGpu").checked = state.paddleGpuAvailable;
      $("#useGpu").disabled = !state.paddleGpuAvailable;
      $("#gpuAvailabilityNote").textContent = !state.paddleReady
        ? "PaddlePaddle is not installed. Rerun the Planline installer before preparing training files."
        : state.paddleGpuAvailable
          ? "PaddlePaddle CUDA runtime detected. GPU training and benchmarking are available."
          : "This installation has a CPU-only PaddlePaddle runtime. Training and benchmarking will use CPU.";
      $("#apiStatus").textContent = state.ocrReady
        ? "Local OCR engine ready"
        : !state.pythonCompatible
          ? "Dataset editor ready · compatible OCR runtime required"
          : "Dataset editor ready · OCR runtime not installed";
      $("#ocrDependencyNote").textContent = !state.pythonCompatible
        ? status.training_note + " No install command will fix this Python-version mismatch; Planline needs a separate compatible OCR runtime."
        : state.ocrReady
          ? status.training_note
          : status.training_note + " Dataset annotation and verified crop storage remain available without the OCR engine.";
    } catch (_) {
      state.paddleGpuAvailable = false;
      $("#useGpu").checked = false;
      $("#useGpu").disabled = true;
      $("#gpuAvailabilityNote").textContent = "Could not verify Paddle GPU support. CPU mode is selected.";
      $("#apiStatus").textContent = "Local OCR workbench";
    }
    await loadTrainingAssets();
    const payload = await api("/api/ocr/datasets");
    state.datasets = payload.datasets || [];
    if (!state.datasets.length) {
      const created = await api("/api/ocr/datasets", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "handwriting" })
      });
      state.datasets = [{ dataset_id: created.dataset_id, summary: created.summary }];
    }
    const select = $("#datasetSelect");
    select.replaceChildren();
    state.datasets.forEach((dataset) => {
      const option = document.createElement("option");
      option.value = dataset.dataset_id;
      option.textContent = dataset.dataset_id;
      select.append(option);
    });
    const nextId = preferredId || state.datasetId;
    state.datasetId = state.datasets.some((item) => item.dataset_id === nextId) ? nextId : state.datasets[0].dataset_id;
    select.value = state.datasetId;
    await loadDataset();
    $("#datasetState").textContent = "LOCAL";
  }

  async function loadDataset() {
    if (!state.datasetId) return;
    state.dataset = await api(`/api/ocr/datasets/${encodeURIComponent(state.datasetId)}`);
    renderDataset();
  }

  function renderDataset() {
    const dataset = state.dataset;
    const summary = dataset?.summary || {};
    const stats = $("#datasetStats");
    stats.replaceChildren();
    [[summary.samples || 0, "CROPS"], [summary.sources || 0, "DRAWINGS"], [summary.writers || 0, "WRITERS"]].forEach(([value, label]) => {
      const item = document.createElement("div");
      const strong = document.createElement("strong"); strong.textContent = String(value);
      const small = document.createElement("span"); small.textContent = label;
      item.append(strong, small); stats.append(item);
    });
    if (summary.splits_present) {
      const splits = summary.split_counts || {};
      $("#datasetHint").textContent = `Train ${splits.train || 0} · validation ${splits.validation || 0} · held-out test ${splits.test || 0}. Editing labels invalidates these splits.`;
    } else {
      $("#datasetHint").textContent = `${summary.independent_groups || 0} independent source/writer groups. Need at least three to make leak-resistant train, validation and test splits.`;
    }
    $("#datasetState").textContent = summary.valid === false ? "CHECK DATA" : "LOCAL";
    $("#exportDatasetButton").disabled = !state.datasetId || summary.valid === false;
    updateReviewImportButton();
    renderSamples();
    renderAvailableModels();
    refreshTrainingButtons();
  }

  function renderAvailableModels() {
    const select = $("#trainedModelSelect");
    if (!select) return;
    const previous = select.value || state.lastTrainedModel;
    select.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = ""; placeholder.textContent = "Select an exported fine-tuned model";
    select.append(placeholder);
    (state.dataset?.available_models || []).forEach((model) => {
      const option = document.createElement("option");
      option.value = model.model_dir; option.textContent = model.label;
      select.append(option);
    });
    if (state.lastTrainedModel && ![...select.options].some((option) => option.value === state.lastTrainedModel)) {
      const option = document.createElement("option"); option.value = state.lastTrainedModel; option.textContent = "Newly trained model"; select.append(option);
    }
    if (previous && [...select.options].some((option) => option.value === previous)) select.value = previous;
  }

  function renderSamples() {
    const list = $("#sampleList");
    list.replaceChildren();
    const all = state.dataset?.samples || [];
    const filter = $("#sampleFilter").value;
    const visible = all.filter((sample) => filter === "all" || sample.text_style === filter);
    $("#sampleCount").textContent = `${visible.length} / ${all.length} samples`;
    if (!visible.length) {
      const empty = document.createElement("div"); empty.className = "sample-list-empty";
      empty.textContent = all.length ? "No samples match this style filter." : "No saved crops yet. Add a scan, draw a crop and type its exact dimension.";
      list.append(empty); return;
    }
    visible.forEach((sample) => {
      const button = document.createElement("button");
      button.type = "button"; button.className = "sample-row";
      if (state.editingId === sample.crop_id) button.classList.add("selected");
      const image = document.createElement("img"); image.src = sample.image_url; image.alt = ""; image.loading = "lazy";
      const info = document.createElement("span"); info.className = "sample-row-info";
      const text = document.createElement("strong"); text.textContent = sample.text;
      const meta = document.createElement("small"); meta.textContent = `${sample.text_style} · ${sample.source_id}${sample.writer_id ? ` · ${sample.writer_id}` : ""}`;
      info.append(text, meta);
      const split = document.createElement("span"); split.className = "sample-split"; split.textContent = sample.split || "unsplit";
      button.append(image, info, split);
      button.addEventListener("click", () => editSample(sample));
      list.append(button);
    });
  }

  $("#datasetSelect").addEventListener("change", async () => {
    state.datasetId = $("#datasetSelect").value;
    state.editingId = null; clearEditMode();
    try { await loadDataset(); message("Dataset loaded."); }
    catch (error) { message(error.message, "error"); }
  });
  $("#exportDatasetButton").addEventListener("click", async () => {
    if (!state.datasetId) return;
    const button = $("#exportDatasetButton");
    button.disabled = true;
    $("#datasetTransferStatus").textContent = "Preparing a ZIP with verified labels, crop images and split metadata…";
    try {
      const response = await fetch("/api/ocr/datasets/" + encodeURIComponent(state.datasetId) + "/export");
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Dataset export failed.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "planline-" + state.datasetId + "-dataset.zip";
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      $("#datasetTransferStatus").textContent = "Dataset ZIP exported. Model checkpoints and training logs are intentionally excluded.";
    } catch (error) {
      $("#datasetTransferStatus").textContent = "Export failed: " + error.message;
    } finally {
      button.disabled = !state.datasetId || state.dataset?.summary?.valid === false;
    }
  });

  $("#importDatasetButton").addEventListener("click", () => {
    $("#datasetArchiveFile").click();
  });

  $("#datasetArchiveFile").addEventListener("change", async () => {
    const file = $("#datasetArchiveFile").files?.[0];
    if (!file || !state.datasetId) return;
    const button = $("#importDatasetButton");
    button.disabled = true;
    $("#datasetTransferStatus").textContent = "Checking the archive and importing verified crop labels…";
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("text_style", $("#datasetImportStyle").value);
      const payload = await api("/api/ocr/datasets/" + encodeURIComponent(state.datasetId) + "/import-archive", {
        method: "POST",
        body: form
      });
      await loadDataset();
      $("#datasetTransferStatus").textContent = "Imported " + payload.added + " verified crops. Skipped " + (payload.skipped_unverified || 0) + " unverified, " + (payload.skipped_style || 0) + " other-style and " + (payload.skipped_blank || 0) + " blank rows.";
      message("Dataset archive imported. Rebuild splits before training.", "success");
    } catch (error) {
      $("#datasetTransferStatus").textContent = "Import failed: " + error.message;
    } finally {
      $("#datasetArchiveFile").value = "";
      button.disabled = false;
    }
  });
  function updateReviewImportButton() {
    $("#importReviewButton").disabled = !state.datasetId || !$("#reviewJsonFile").files?.length || !$("#reviewImageFile").files?.length;
  }
  $("#reviewJsonFile").addEventListener("change", updateReviewImportButton);
  $("#reviewImageFile").addEventListener("change", updateReviewImportButton);
  $("#importReviewButton").addEventListener("click", async () => {
    const reviewFile = $("#reviewJsonFile").files?.[0];
    const imageFile = $("#reviewImageFile").files?.[0];
    if (!state.datasetId || !reviewFile || !imageFile) return;
    const button = $("#importReviewButton");
    button.disabled = true;
    $("#datasetTransferStatus").textContent = "Reading the review export and importing only verified crops…";
    try {
      const form = new FormData();
      form.append("file", imageFile);
      form.append("review_json", await reviewFile.text());
      form.append("text_style", $("#datasetImportStyle").value);
      form.append("writer_id", $("#reviewWriterId").value.trim());
      const payload = await api("/api/ocr/datasets/" + encodeURIComponent(state.datasetId) + "/import-review", {
        method: "POST",
        body: form
      });
      await loadDataset();
      $("#datasetTransferStatus").textContent = "Imported " + payload.added + " verified review crops. Skipped " + (payload.skipped_unverified || 0) + " unverified, " + (payload.skipped_style || 0) + " other-style, " + (payload.skipped_blank || 0) + " blank and " + (payload.skipped_no_crop || 0) + " crops without bounds.";
      message("Verified crops imported from the drawing review. Rebuild splits before training.", "success");
    } catch (error) {
      $("#datasetTransferStatus").textContent = "Review import failed: " + error.message;
    } finally {
      updateReviewImportButton();
    }
  });
  $("#sampleFilter").addEventListener("change", renderSamples);
  $("#newDatasetButton").addEventListener("click", () => $("#newDatasetForm").classList.toggle("hidden"));
  $("#createDatasetButton").addEventListener("click", async () => {
    const name = $("#newDatasetName").value.trim();
    if (!name) return message("Enter a dataset name.", "error");
    try {
      const payload = await api("/api/ocr/datasets", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
      $("#newDatasetName").value = ""; $("#newDatasetForm").classList.add("hidden");
      state.editingId = null; clearEditMode(); await loadDatasets(payload.dataset_id);
      message(`Created dataset ${payload.dataset_id}.`, "success");
    } catch (error) { message(error.message, "error"); }
  });

  function fitCropCanvas() {
    if (!state.image) return;
    const canvas = $("#cropCanvas");
    const zoom = Number($("#cropZoom").value || 1);
    const ratio = Math.min(1, 1400 / state.image.naturalWidth, 660 / state.image.naturalHeight) * zoom;
    canvas.width = Math.max(1, Math.round(state.image.naturalWidth * ratio));
    canvas.height = Math.max(1, Math.round(state.image.naturalHeight * ratio));
    canvas.style.width = `${canvas.width}px`;
    canvas.style.height = `${canvas.height}px`;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(state.image, 0, 0, canvas.width, canvas.height);
    if (state.cropRect) {
      const scaleX = canvas.width / state.image.naturalWidth;
      const scaleY = canvas.height / state.image.naturalHeight;
      drawSelection({ x: state.cropRect.x * scaleX, y: state.cropRect.y * scaleY,
        width: state.cropRect.width * scaleX, height: state.cropRect.height * scaleY });
    }
    $("#cropZoomValue").textContent = `${zoom.toFixed(1)}×`;
    canvas.classList.remove("hidden");
    $("#cropCanvasEmpty").classList.add("hidden");
    $("#cropDimensions").textContent = `${state.image.naturalWidth} × ${state.image.naturalHeight} PX`;
    $("#useWholeImageButton").disabled = false;
  }

  function drawSelection(rect) {
    if (!state.image) return;
    const canvas = $("#cropCanvas"); const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(state.image, 0, 0, canvas.width, canvas.height);
    context.fillStyle = "rgba(20, 28, 20, .36)";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.clearRect(rect.x, rect.y, rect.width, rect.height);
    context.drawImage(state.image, 0, 0, canvas.width, canvas.height);
    context.strokeStyle = "#d34e3e"; context.lineWidth = 2;
    context.setLineDash([7, 4]); context.strokeRect(rect.x, rect.y, rect.width, rect.height); context.setLineDash([]);
  }

  async function selectCrop(rect) {
    if (!state.image || !rect || rect.width < 4 || rect.height < 4) return;
    const canvas = document.createElement("canvas");
    const scaleX = state.image.naturalWidth / $("#cropCanvas").width;
    const scaleY = state.image.naturalHeight / $("#cropCanvas").height;
    const x = Math.max(0, Math.floor(rect.x * scaleX));
    const y = Math.max(0, Math.floor(rect.y * scaleY));
    const right = Math.min(state.image.naturalWidth, Math.ceil((rect.x + rect.width) * scaleX));
    const bottom = Math.min(state.image.naturalHeight, Math.ceil((rect.y + rect.height) * scaleY));
    canvas.width = right - x; canvas.height = bottom - y;
    if (canvas.width < 1 || canvas.height < 1) return;
    canvas.getContext("2d").drawImage(state.image, x, y, canvas.width, canvas.height, 0, 0, canvas.width, canvas.height);
    state.cropBlob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    state.cropRect = { x, y, width: canvas.width, height: canvas.height };
    drawSelection(rect);
    $("#cropSelectionInfo").textContent = `${canvas.width} × ${canvas.height} px crop`;
    setBusy(state.busy);
  }

  function loadQueueImage() {
    if (state.queueIndex >= state.queue.length) {
      if (state.image?.__queueUrl) URL.revokeObjectURL(state.image.__queueUrl);
      state.image = null; state.imageFile = null; state.cropBlob = null; state.cropRect = null;
      $("#cropCanvas").classList.add("hidden"); $("#cropCanvasEmpty").classList.remove("hidden");
      $("#cropCanvasEmpty").querySelector("strong").textContent = "Queue complete";
      $("#cropCanvasEmpty").querySelector("span").textContent = "Add more images or review your saved labels below.";
      $("#queueStatus").textContent = "QUEUE COMPLETE"; $("#cropDimensions").textContent = "—";
      $("#cropSelectionInfo").textContent = "No crop selected"; $("#useWholeImageButton").disabled = true;
      $("#saveCropButton").disabled = true; $("#skipCropButton").disabled = true;
      return;
    }
    const file = state.queue[state.queueIndex];
    state.imageFile = file; state.cropBlob = null; state.cropRect = null; state.editingId = null;
    clearEditMode();
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      if (state.image?.__queueUrl) URL.revokeObjectURL(state.image.__queueUrl);
      image.__queueUrl = url; state.image = image; fitCropCanvas();
      $("#queueStatus").textContent = `${state.queueIndex + 1} / ${state.queue.length} · ${file.name}`;
      $("#cropSelectionInfo").textContent = "Drag to select a complete dimension";
      $("#sampleText").value = ""; $("#labelVerified").checked = true;
      $("#saveCropButton").textContent = "Save label + next →";
      $("#skipCropButton").disabled = false; $("#useWholeImageButton").disabled = false;
      setBusy(false);
    };
    image.onerror = () => { URL.revokeObjectURL(url); message(`Could not open ${file.name}.`, "error"); skipQueueItem(); };
    image.src = url;
  }

  $("#cropFiles").addEventListener("change", (event) => {
    const files = [...(event.target.files || [])];
    const usable = files.filter((file) => /\.(png|jpe?g|webp|tiff?)$/i.test(file.name) && file.size <= 25 * 1024 * 1024);
    if (!usable.length) return message("Choose PNG, JPG, WEBP or TIFF images no larger than 25 MB each.", "error");
    state.queue = usable; state.queueIndex = 0; state.editingId = null;
    $("#cropZoom").value = "1";
    $("#cropFiles").value = "";
    if (!$("#sourceId").value.trim()) $("#sourceId").value = "plan-01";
    message(`${usable.length} image${usable.length === 1 ? "" : "s"} added to the local crop queue.`);
    loadQueueImage();
  });

  const canvas = $("#cropCanvas");
  function canvasPoint(event) {
    const bounds = canvas.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(canvas.width, (event.clientX - bounds.left) * canvas.width / bounds.width)),
      y: Math.max(0, Math.min(canvas.height, (event.clientY - bounds.top) * canvas.height / bounds.height))
    };
  }
  $("#cropZoom").addEventListener("input", () => { if (state.image) fitCropCanvas(); });
  canvas.addEventListener("pointerdown", (event) => {
    if (!state.image || state.editingId) return;
    state.pointerStart = canvasPoint(event);
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!state.pointerStart || !state.image) return;
    const { x, y } = canvasPoint(event);
    const start = state.pointerStart;
    const selection = { x: Math.min(start.x, x), y: Math.min(start.y, y), width: Math.abs(x - start.x), height: Math.abs(y - start.y) };
    drawSelection(selection);
  });
  canvas.addEventListener("pointerup", async (event) => {
    if (!state.pointerStart) return;
    const { x, y } = canvasPoint(event);
    const start = state.pointerStart; state.pointerStart = null;
    const selection = { x: Math.min(start.x, x), y: Math.min(start.y, y), width: Math.abs(x - start.x), height: Math.abs(y - start.y) };
    await selectCrop(selection);
  });
  $("#useWholeImageButton").addEventListener("click", () => {
    if (state.image) selectCrop({ x: 0, y: 0, width: canvas.width, height: canvas.height });
  });
  $("#sampleText").addEventListener("input", () => setBusy(state.busy));
  $("#labelVerified").addEventListener("change", () => setBusy(state.busy));

  async function saveCurrentCrop() {
    if (!state.cropBlob) return message("Draw a crop around the whole dimension first.", "error");
    const text = $("#sampleText").value.trim(); const sourceId = $("#sourceId").value.trim();
    if (!text) return message("Type exactly what is written in the crop, including units and punctuation.", "error");
    if (!sourceId) return message("Enter a drawing/source ID. Reuse it for every crop from the same plan.", "error");
    if (!$("#labelVerified").checked) return message("Check the transcription against the source drawing before saving it as training data.", "error");
    const form = new FormData();
    form.append("file", state.cropBlob, "dimension-crop.png");
    form.append("text", text); form.append("source_id", sourceId);
    form.append("writer_id", $("#writerId").value.trim());
    form.append("text_style", $("#textStyle").value); form.append("verified", "true");
    setBusy(true); message("Saving verified crop locally…");
    try {
      const result = await api(`/api/ocr/datasets/${encodeURIComponent(state.datasetId)}/samples`, { method: "POST", body: form });
      state.dataset = result.dataset; renderDataset();
      state.queueIndex += 1; message(`Saved “${text}”.`, "success"); loadQueueImage();
    } catch (error) { message(error.message, "error"); }
    finally { setBusy(false); }
  }
  $("#saveCropButton").addEventListener("click", saveCurrentCrop);
  function skipQueueItem() { state.queueIndex += 1; loadQueueImage(); }
  $("#skipCropButton").addEventListener("click", skipQueueItem);

  function clearEditMode() {
    $("#editActions").classList.add("hidden"); $("#saveCropButton").classList.remove("hidden");
    $("#savedImagePreviewWrap").classList.add("hidden"); $("#savedImagePreview").removeAttribute("src");
    $("#sampleText").value = ""; $("#saveCropButton").textContent = "Save label + next →";
    $("#saveCropButton").disabled = !state.cropBlob;
  }
  function editSample(sample) {
    state.editingId = sample.crop_id; state.cropBlob = null; state.cropRect = null;
    $("#sampleText").value = sample.text; $("#sourceId").value = sample.source_id;
    $("#writerId").value = sample.writer_id; $("#textStyle").value = sample.text_style;
    $("#labelVerified").checked = sample.verified;
    $("#saveCropButton").classList.add("hidden"); $("#editActions").classList.remove("hidden");
    $("#savedImagePreview").src = sample.image_url; $("#savedImagePreviewWrap").classList.remove("hidden");
    $("#cropCanvas").classList.add("hidden"); $("#cropCanvasEmpty").classList.remove("hidden");
    $("#cropCanvasEmpty").querySelector("strong").textContent = "Editing saved label";
    $("#cropCanvasEmpty").querySelector("span").textContent = "Correct the transcription or grouping, then save the correction.";
    $("#cropDimensions").textContent = "SAVED SAMPLE"; $("#queueStatus").textContent = "EDITING LABEL";
    $("#cropSelectionInfo").textContent = `${sample.split || "Unsplit"} · ${sample.crop_id}`;
    renderSamples(); setBusy(false); message("Editing an existing crop. Corrections invalidate any previous train/test split.");
  }
  $("#saveCorrectionButton").addEventListener("click", async () => {
    if (!state.editingId) return;
    const payload = {
      text: $("#sampleText").value.trim(), source_id: $("#sourceId").value.trim(),
      writer_id: $("#writerId").value.trim() || null, text_style: $("#textStyle").value,
      verified: $("#labelVerified").checked
    };
    setBusy(true);
    try {
      const result = await api(`/api/ocr/datasets/${encodeURIComponent(state.datasetId)}/samples/${encodeURIComponent(state.editingId)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
      });
      state.dataset = result.dataset; state.editingId = null; clearEditMode(); renderDataset(); message("Label corrected. Rebuild splits before benchmarking/training.", "success");
    } catch (error) { message(error.message, "error"); }
    finally { setBusy(false); }
  });
  $("#deleteSampleButton").addEventListener("click", async () => {
    if (!state.editingId || !window.confirm("Delete this crop and its label from the local dataset?")) return;
    setBusy(true);
    try {
      const result = await api(`/api/ocr/datasets/${encodeURIComponent(state.datasetId)}/samples/${encodeURIComponent(state.editingId)}`, { method: "DELETE" });
      state.dataset = result.dataset; state.editingId = null; clearEditMode(); renderDataset(); message("Crop deleted. Previous splits have been removed.", "success");
    } catch (error) { message(error.message, "error"); }
    finally { setBusy(false); }
  });
  $("#cancelEditButton").addEventListener("click", () => { state.editingId = null; clearEditMode(); renderSamples(); message("Label editing closed."); });


  function renderQualityReport(report) {
    const panel = $("#qualityPanel");
    panel.classList.remove("hidden");
    $("#qualityTitle").textContent = "Dataset quality report · " + report.dataset;
    const ready = Boolean(report.ready_for_training);
    $("#qualityReadiness").textContent = ready ? "BASIC CHECKS PASSED" : "NEEDS ATTENTION";
    $("#qualityReadiness").dataset.ready = ready ? "true" : "false";
    const stats = $("#qualityStats");
    stats.replaceChildren();
    [
      [report.sample_count, "CROPS"],
      [report.verified_count, "VERIFIED"],
      [report.source_count, "DRAWINGS"],
      [report.writer_count, "WRITERS"],
      [report.duplicate_crop_count, "DUPLICATES"],
      [report.conflicting_duplicate_image_count, "CONFLICTS"]
    ].forEach(([value, label]) => {
      const card = document.createElement("div"); card.className = "quality-stat";
      const strong = document.createElement("strong"); strong.textContent = String(value ?? 0);
      const small = document.createElement("span"); small.textContent = label;
      card.append(strong, small); stats.append(card);
    });
    const warnings = $("#qualityWarnings"); warnings.replaceChildren();
    const warningItems = Array.isArray(report.warnings) ? report.warnings : [];
    if (!warningItems.length) {
      const good = document.createElement("p"); good.className = "quality-good"; good.textContent = "No dataset hygiene warnings found."; warnings.append(good);
    } else {
      warningItems.forEach((item) => {
        const row = document.createElement("div"); row.className = "quality-warning";
        const code = document.createElement("strong"); code.textContent = String(item.code || "warning").replaceAll("_", " ");
        const detail = document.createElement("span"); detail.textContent = item.message || "";
        row.append(code, detail); warnings.append(row);
      });
    }
    const chars = $("#qualityCharacters"); chars.replaceChildren();
    const frequency = Object.entries(report.character_frequencies || {}).sort((a, b) => b[1] - a[1]);
    frequency.slice(0, 36).forEach(([character, count]) => {
      const pill = document.createElement("span"); pill.className = "quality-character";
      const label = document.createElement("b"); label.textContent = character === " " ? "space" : character;
      const number = document.createElement("small"); number.textContent = String(count);
      pill.append(label, number); chars.append(pill);
    });
    if (!frequency.length) {
      const empty = document.createElement("p"); empty.className = "quality-good"; empty.textContent = "No characters to report yet."; chars.append(empty);
    }
    const notes = Array.isArray(report.notes) ? report.notes : [];
    $("#qualityNotes").textContent = notes.length
      ? notes.join(" ") + " A clean audit is not evidence of model accuracy or sufficient data."
      : "The audit is read-only. Basic hygiene checks do not prove that the dataset is large or representative enough to train a reliable model.";
  }

  $("#auditDatasetButton").addEventListener("click", async () => {
    setBusy(true); message("Checking labels, duplicate crops and split leakage…");
    try {
      const report = await api("/api/ocr/datasets/" + encodeURIComponent(state.datasetId) + "/quality");
      renderQualityReport(report);
      message("Quality audit completed. It did not change your dataset.", "success");
    } catch (error) { message(error.message, "error"); }
    finally { setBusy(false); }
  });

  $("#buildSplitsButton").addEventListener("click", async () => {
    setBusy(true); message("Grouping by source drawing and writer…");
    try {
      const result = await api(`/api/ocr/datasets/${encodeURIComponent(state.datasetId)}/splits`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ seed: 42, force: true })
      });
      state.dataset = result.dataset; renderDataset();
      const split = result.splits.sample_counts;
      message(`Splits built: train ${split.train}, validation ${split.validation}, test ${split.test}. No shared source/writer groups cross splits.`, "success");
    } catch (error) { message(error.message, "error"); }
    finally { setBusy(false); }
  });

  function beginJob(job, title) {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.activeJobId = job.job_id;
    $("#jobPanel").classList.remove("hidden"); $("#jobTitle").textContent = title;
    $("#jobLog").textContent = job.logs || "Starting job…";
    $("#jobStatus").textContent = (job.status || "queued").toUpperCase();
    $("#jobProgressBar").style.width = "0%";
    $("#cancelJobButton").classList.remove("hidden"); refreshTrainingButtons();
    pollJob(); state.pollTimer = setInterval(pollJob, 1800);
  }

  async function pollJob() {
    if (!state.activeJobId) return;
    try {
      const job = await api(`/api/ocr/jobs/${encodeURIComponent(state.activeJobId)}`);
      $("#jobStatus").textContent = (job.status || "unknown").replaceAll("_", " ").toUpperCase();
      $("#jobLog").textContent = job.logs || "";
      $("#jobLog").scrollTop = $("#jobLog").scrollHeight;
      const progress = job.epochs ? Math.round((job.epoch || 0) / job.epochs * 100) : (terminalStatuses.has(job.status) ? 100 : 8);
      $("#jobProgressBar").style.width = `${Math.max(0, Math.min(100, progress))}%`;
      if (job.metrics) renderMetrics(job.metrics);
      if (job.model_dir) {
        state.lastTrainedModel = job.model_dir;
        renderAvailableModels();
        $("#trainedModelSelect").value = job.model_dir;
      }
      if (terminalStatuses.has(job.status)) {
        clearInterval(state.pollTimer); state.pollTimer = null; state.activeJobId = null;
        $("#cancelJobButton").classList.add("hidden"); refreshTrainingButtons();
        message(job.status === "completed" ? "Job completed." : `Job ${job.status.replaceAll("_", " ")}. Check its log for details.`, job.status === "completed" ? "success" : "error");
      }
    } catch (error) {
      $("#jobStatus").textContent = "STATUS ERROR";
      $("#jobLog").textContent += `\n${error.message}`;
    }
  }

  $("#cancelJobButton").addEventListener("click", async () => {
    if (!state.activeJobId) return;
    try { await api(`/api/ocr/jobs/${encodeURIComponent(state.activeJobId)}/cancel`, { method: "POST" }); message("Cancellation requested. The current process is being stopped."); }
    catch (error) { message(error.message, "error"); }
  });

  $("#prepareTrainingAssetsButton").addEventListener("click", async () => {
    setBusy(true);
    $("#trainingAssetsStatus").textContent = "Downloading the pinned PaddleOCR source and matching pretrained checkpoint. The first setup can take a few minutes.";
    try {
      const assets = await api("/api/ocr/training-assets/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_variant: $("#modelVariant").value })
      });
      state.trainingAssets = assets;
      $("#paddleSourcePath").value = assets.paddleocr_dir;
      $("#pretrainedPath").value = assets.pretrained_model;
      $("#trainingAssetsStatus").textContent = `Ready: PaddleOCR ${assets.source_version} and ${assets.model_variant} pretrained weights are stored locally.`;
      message("Official training files are ready. You can now start fine-tuning.", "success");
    } catch (error) {
      state.trainingAssets = null;
      $("#trainingAssetsStatus").textContent = error.message;
      message(error.message, "error");
    } finally {
      setBusy(false);
      refreshTrainingButtons();
    }
  });

  $("#modelVariant").addEventListener("change", () => {
    state.trainingAssets = null;
    loadTrainingAssets();
  });

  $("#trainButton").addEventListener("click", async () => {
    const payload = {
      paddleocr_dir: $("#paddleSourcePath").value.trim(), pretrained_model: $("#pretrainedPath").value.trim(),
      model_variant: $("#modelVariant").value, epochs: Number($("#trainingEpochs").value),
      batch_size: Number($("#trainingBatch").value), use_gpu: $("#useGpu").checked
    };
    setBusy(true); message("Checking PaddleOCR source, checkpoint and dataset…");
    try {
      const job = await api(`/api/ocr/datasets/${encodeURIComponent(state.datasetId)}/train`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
      });
      beginJob(job, "Fine-tuning dimension recogniser"); message("Training job started. Keep this window open while it runs.", "success");
    } catch (error) { message(error.message, "error"); }
    finally { setBusy(false); }
  });

  function renderMetrics(report) {
    const metrics = report.metrics || report;
    const box = $("#benchmarkMetrics"); box.replaceChildren(); box.classList.remove("hidden");
    const items = [
      [metrics.exact_match_rate, "EXACT MATCH"],
      [metrics.prediction_coverage_rate, "COVERAGE"],
      [metrics.character_error_rate, "CHARACTER ERROR"]
    ];
    items.forEach(([value, label]) => {
      const card = document.createElement("div"); card.className = "benchmark-metric";
      const strong = document.createElement("strong"); strong.textContent = value == null ? "—" : `${(value * 100).toFixed(1)}%`;
      const small = document.createElement("span"); small.textContent = label;
      card.append(strong, small); box.append(card);
    });
    const note = document.createElement("p"); note.className = "metrics-note";
    note.textContent = `${metrics.sample_count ?? "—"} held-out samples · ${report.model || "OCR model"} · transcription only`;
    box.append(note);
  }

  async function runBenchmark(trained) {
    const modelDir = trained ? ($("#trainedModelSelect").value || state.lastTrainedModel) : null;
    if (trained && !modelDir) return message("Select a fine-tuned model to benchmark.", "error");
    const payload = {
      model: $("#modelVariant").value === "mobile" ? "PP-OCRv5_mobile_rec" : "PP-OCRv5_server_rec", model_dir: modelDir,
      device: $("#useGpu").checked ? "gpu:0" : "cpu"
    };
    setBusy(true); message(trained ? "Benchmarking your fine-tuned recogniser…" : "Benchmarking the base recogniser…");
    try {
      const job = await api(`/api/ocr/datasets/${encodeURIComponent(state.datasetId)}/benchmark`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
      });
      $("#benchmarkMetrics").classList.add("hidden"); beginJob(job, trained ? "Fine-tuned model benchmark" : "Base model benchmark");
    } catch (error) { message(error.message, "error"); }
    finally { setBusy(false); }
  }
  $("#benchmarkBaseButton").addEventListener("click", () => runBenchmark(false));
  $("#benchmarkTrainedButton").addEventListener("click", () => runBenchmark(true));
  $("#trainedModelSelect").addEventListener("change", refreshTrainingButtons);
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !$("#ocrStudio").classList.contains("hidden")) {
      event.preventDefault();
      if (state.editingId) $("#saveCorrectionButton").click(); else $("#saveCropButton").click();
    }
    if (event.key === "Escape" && state.editingId) $("#cancelEditButton").click();
  });

  // This page is a dedicated local OCR workbench; drawing review remains a separate route.
  setView();
  setBusy(false);
})();

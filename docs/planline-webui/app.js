(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const state = {
    sample: true,
    currentStep: 1,
    file: null,
    projectId: null,
    apiAvailable: false,
    objectUrl: null,
    measurements: [
      { id: 'a', value: 3000, confidence: 98, verified: true },
      { id: 'b', value: 4500, confidence: 96, verified: true },
      { id: 'c', value: 2500, confidence: 76, verified: false }
    ],
    overall: 10000
  };

  const fileInput = $('#fileInput');
  const toast = $('#toast');
  let toastTimer = null;

  function canOpenPreview() {
    const sum = state.measurements.reduce((total, item) => total + (Number(item.value) || 0), 0);
    const overall = Number($('#overallValue').value) || 0;
    return state.sample && state.measurements.every(item => item.verified) && sum === overall;
  }

  function showStep(step) {
    const target = Number(step);
    if (target === 3 && !canOpenPreview()) {
      showToast(state.sample ? 'Confirm every sample dimension and resolve the chain before opening the preview.' : 'Preview and export need the processing backend for uploaded drawings.');
      return;
    }
    state.currentStep = target;
    $$('.step-page').forEach(page => page.classList.toggle('active', page.id === `stepPage${target}`));
    $$('.step-tab').forEach(tab => {
      const tabStep = Number(tab.dataset.step);
      tab.classList.toggle('active', tabStep === target);
      tab.classList.toggle('complete', tabStep < target);
      tab.setAttribute('aria-current', tabStep === target ? 'step' : 'false');
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add('show');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove('show'), 2800);
  }

  function formatNumber(value) {
    return Number.isFinite(value) ? Math.round(value).toLocaleString('en-AU') : '—';
  }

  function revokeObjectUrl() {
    if (state.objectUrl) {
      URL.revokeObjectURL(state.objectUrl);
      state.objectUrl = null;
    }
  }

  function setSourceMode(mode) {
    $('#samplePaper').classList.toggle('hidden', mode !== 'sample');
    $('#imagePreviewWrap').classList.toggle('hidden', mode !== 'image');
    $('#filePreviewWrap').classList.toggle('hidden', mode !== 'pdf');
    $('#sourceEmpty').classList.toggle('hidden', mode !== 'empty');
  }

  function updateFileMeta(file) {
    $('#projectFileName').textContent = file.name;
    const size = file.size < 1024 * 1024
      ? `${Math.max(1, Math.round(file.size / 1024))} KB`
      : `${(file.size / (1024 * 1024)).toFixed(1)} MB`;
    $('#projectFileMeta').textContent = `${size} · local file · not processed`;
    $('#sourceTypeChip').textContent = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf') ? 'PDF DOCUMENT' : 'UPLOADED SCAN';
    $('#sourceDimensions').textContent = 'Preview only · analysis not connected';
    $('#exportNote').textContent = 'Uploaded drawing is not reconstructed. Export is limited to the illustrative sample geometry.';
  }

  async function checkApi() {
    if (window.location.protocol === 'file:') return;
    try {
      const response = await fetch('/api/health', { headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error('Service unavailable');
      const health = await response.json();
      state.apiAvailable = health.status === 'ok';
      if (state.apiAvailable) {
        $('#apiStatus').innerHTML = '<span class="status-dot"></span> Local backend connected';
      }
    } catch {
      $('#apiStatus').innerHTML = '<span class="status-dot amber"></span> Local preview mode';
    }
  }

  async function createBackendProject(file) {
    if (!state.apiAvailable) return;
    const data = new FormData();
    data.append('file', file, file.name);
    const response = await fetch('/api/projects', { method: 'POST', body: data });
    if (!response.ok) throw new Error('The local service could not store this drawing.');
    const project = await response.json();
    state.projectId = project.id;
    $('#projectFileMeta').textContent = `${Math.max(1, Math.round(project.size_bytes / 1024))} KB · stored locally · not analysed`;
    const analysis = await fetch(`/api/projects/${project.id}/analyze`, { method: 'POST' });
    if (!analysis.ok) throw new Error('The local service stored the drawing, but could not start analysis.');
    const result = await analysis.json();
    renderPreflightNotice(result.analysis.preflight);
  }

  function renderPreflightNotice(preflight) {
    const notice = $('#uploadNotice');
    notice.replaceChildren();
    const title = document.createElement('strong');
    title.textContent = 'Local source preflight complete.';
    const summary = document.createElement('span');
    summary.textContent = ' Your scan is stored locally. OCR, detection, and 2D reconstruction have not run because model adapters are not configured.';
    notice.append(title, summary);
    const findings = preflight && Array.isArray(preflight.findings) ? preflight.findings : [];
    if (findings.length) {
      const list = document.createElement('ul');
      list.className = 'preflight-findings';
      findings.forEach(finding => {
        const item = document.createElement('li');
        item.textContent = finding.message;
        list.appendChild(item);
      });
      notice.appendChild(list);
    }
  }

  async function handleFile(file) {
    if (!file) return;
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    const isImage = /^image\/(png|jpeg|webp|tiff)$/.test(file.type) || /\.(png|jpe?g|webp|tif|tiff)$/i.test(file.name);
    if (!isPdf && !isImage) {
      showToast('Choose a PNG, JPG, WEBP, TIFF or PDF file.');
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      showToast('This file is larger than 50 MB. Choose a smaller scan.');
      return;
    }
    revokeObjectUrl();
    state.file = file;
    state.sample = false;
    state.projectId = null;
    updateFileMeta(file);
    if (isPdf) {
      $('#pdfName').textContent = file.name;
      setSourceMode('pdf');
    } else {
      state.objectUrl = URL.createObjectURL(file);
      $('#uploadedPreview').src = state.objectUrl;
      $('#uploadedPreview').onerror = () => showToast('This image could not be previewed by the browser.');
      setSourceMode('image');
      $('#uploadedPreview').onload = () => {
        const image = $('#uploadedPreview');
        $('#sourceDimensions').textContent = `${image.naturalWidth} × ${image.naturalHeight} px · preview only`;
      };
    }
    $('#uploadNotice').classList.remove('hidden');
    $('#uploadNotice').innerHTML = '<strong>Preview only — no analysis has run.</strong>The review values and confidence scores are illustrative sample data, not readings from this file. Review and export are paused until a local OCR and geometry service is connected.';
    renderMeasurementRows();
    updateReviewState();
    $('#reviewModeChip').textContent = 'SAMPLE PLACEHOLDERS';
    $('.status-pill').innerHTML = '<span class="status-dot amber"></span> Uploaded · not analysed';
    $('#cadSummary').textContent = 'Sample geometry only · uploaded drawing not reconstructed';
    $('#cadSummary').setAttribute('aria-label', 'Sample geometry only. Uploaded drawing not reconstructed.');
    showToast('Drawing loaded locally. OCR and reconstruction are not connected yet.');
    $('#exportNote').textContent = 'Your uploaded drawing has not been processed. The downloadable DXF remains a separate sample layout.';
    $('#exportButton').disabled = true;
    try {
      await createBackendProject(file);
      if (state.apiAvailable) showToast('Drawing stored locally. Source preflight is complete; OCR is not configured.');
    } catch (error) {
      showToast(error.message || 'Drawing previewed, but the local service was unavailable.');
    }
  }

  function resetSample() {
    revokeObjectUrl();
    state.file = null;
    state.projectId = null;
    state.sample = true;
    state.measurements = [
      { id: 'a', value: 3000, confidence: 98, verified: true },
      { id: 'b', value: 4500, confidence: 96, verified: true },
      { id: 'c', value: 2500, confidence: 76, verified: false }
    ];
    state.overall = 10000;
    $('#projectFileName').textContent = 'sample-house-scan.png';
    $('#projectFileMeta').textContent = 'Illustrative sample · 2D residential plan';
    $('#sourceTypeChip').textContent = 'SAMPLE SCAN';
    $('#sourceDimensions').textContent = 'Illustrative scan · 650 × 400';
    $('.status-pill').innerHTML = '<span class="status-dot amber"></span> Demo project';
    $('#cadSummary').textContent = 'Illustrative geometry · 10,000 × 7,000 mm';
    $('#exportNote').textContent = 'The sample geometry can be exported. Uploaded drawings need the processing backend first.';
    $('#exportButton').disabled = false;
    $('#uploadNotice').classList.add('hidden');
    $('#reviewModeChip').textContent = 'SAMPLE DATA';
    setSourceMode('sample');
    renderMeasurementRows();
    $('#overallValue').value = state.overall;
    updateReviewState();
    showStep(1);
    showToast('Sample project restored.');
  }

  function renderMeasurementRows() {
    const list = $('#measurementList');
    list.innerHTML = '';
    state.measurements.forEach((measurement, index) => {
      const letter = measurement.id.toUpperCase();
      const statusClass = measurement.verified ? 'verified' : 'needs-review';
      const confidenceClass = measurement.confidence >= 90 ? 'high' : 'medium';
      const confidenceLabel = measurement.confidence >= 90 ? 'High' : 'Review';
      const article = document.createElement('article');
      article.className = `measurement-row ${statusClass}`;
      article.dataset.id = measurement.id;
      article.innerHTML = `
        <div class="measurement-main">
          <span class="measurement-index">${letter}</span>
          <div class="measurement-copy">
            <label for="value-${measurement.id}">Horizontal span</label>
            <div class="measurement-input-wrap">
              <input id="value-${measurement.id}" class="dimension-input" type="number" min="1" step="1" value="${measurement.value}" aria-label="Dimension ${letter} in millimetres">
              <span>mm</span>
            </div>
            ${measurement.verified ? '' : '<span class="row-note">Confirm this reading</span>'}
          </div>
        </div>
        <div class="confidence-cell">
          <span class="confidence-score ${confidenceClass}">${measurement.confidence}%</span>
          <span class="confidence-caption">${confidenceLabel}</span>
          <button class="verify-toggle ${measurement.verified ? 'checked' : ''}" type="button" aria-label="${measurement.verified ? `Mark dimension ${letter} unverified` : `Verify dimension ${letter}`}" aria-pressed="${measurement.verified}">✓</button>
        </div>`;
      list.appendChild(article);
      const input = $('.dimension-input', article);
      input.disabled = !state.sample;
      const toggle = $('.verify-toggle', article);
      toggle.disabled = !state.sample;
      input.addEventListener('input', () => {
        const value = Number(input.value);
        measurement.value = Number.isFinite(value) && value > 0 ? value : 0;
        measurement.verified = false;
        updateReviewState();
        $('.verify-toggle', article).classList.remove('checked');
        $('.verify-toggle', article).setAttribute('aria-pressed', 'false');
        $('.verify-toggle', article).setAttribute('aria-label', `Verify dimension ${letter}`);
        article.classList.add('needs-review');
        article.classList.remove('verified');
        const note = $('.row-note', article);
        if (!note) {
          const noteEl = document.createElement('span');
          noteEl.className = 'row-note';
          noteEl.textContent = 'Edited · verify this value';
          $('.measurement-copy', article).appendChild(noteEl);
        } else {
          note.textContent = 'Edited · verify this value';
        }
      });
      toggle.addEventListener('click', () => {
        measurement.verified = !measurement.verified;
        renderMeasurementRows();
        updateReviewState();
      });
    });
  }

  function updateCadDrawing() {
    const a = Math.max(500, Number(state.measurements[0].value) || 3000);
    const b = Math.max(500, Number(state.measurements[1].value) || 4500);
    const c = Math.max(500, Number(state.measurements[2].value) || 2500);
    const total = a + b + c;
    const height = 7000;
    const scale = Math.min(480 / total, 235 / height);
    const widthPx = total * scale;
    const heightPx = height * scale;
    const originX = (680 - widthPx) / 2;
    const originY = (345 - heightPx) / 2 + 7;
    const x0 = originX;
    const x1 = originX + a * scale;
    const x2 = originX + (a + b) * scale;
    const x3 = originX + total * scale;
    const y0 = originY;
    const y1 = originY + heightPx;
    const midY = originY + heightPx * .5;
    const wall = '#355441';
    const stroke = 5.2;
    const d = (x1p,y1p,x2p,y2p,w=stroke,color=wall) => `<line x1="${x1p}" y1="${y1p}" x2="${x2p}" y2="${y2p}" stroke="${color}" stroke-width="${w}" stroke-linecap="square"/>`;
    const outer = `<rect x="${x0}" y="${y0}" width="${widthPx}" height="${heightPx}" fill="#fff" fill-opacity=".62" stroke="${wall}" stroke-width="${stroke}"/>`;
    const interior = [
      d(x1,y0,x1,y1,stroke), d(x2,y0,x2,y1,stroke),
      d(x0,midY,x1,midY,stroke), d(x2,midY,x3,midY,stroke),
      d(x1,originY+heightPx*.30,x2,originY+heightPx*.30,stroke)
    ].join('');
    const doors = [
      d(x1+12,midY,x1+52,midY,2,'#91b09b'),
      `<path d="M ${x1+12} ${midY} A 40 40 0 0 1 ${x1+52} ${midY-40}" fill="none" stroke="#91b09b" stroke-width="1.6"/>`,
      d(x2+10,y1-40,x2+48,y1-40,2,'#91b09b'),
      `<path d="M ${x2+10} ${y1-40} A 38 38 0 0 0 ${x2+48} ${y1-2}" fill="none" stroke="#91b09b" stroke-width="1.6"/>`
    ].join('');
    $('#cadDrawing').innerHTML = `${outer}${interior}${doors}`;

    const dimY = y0 - 23;
    const dimLine = (xStart,xEnd,y,text) => `
      <g stroke="#bf8a5d" fill="none" stroke-width="1">
        <path d="M ${xStart} ${y-5} V ${y+5} M ${xEnd} ${y-5} V ${y+5} M ${xStart} ${y} H ${xEnd}"/>
      </g>
      <text x="${(xStart+xEnd)/2}" y="${y-6}" text-anchor="middle" fill="#a8754d" font-size="10" font-family="DM Sans, sans-serif">${text}</text>`;
    const verticalDim = `<g stroke="#bf8a5d" fill="none" stroke-width="1"><path d="M ${x3+24} ${y0} H ${x3+35} M ${x3+24} ${y1} H ${x3+35} M ${x3+30} ${y0} V ${y1}"/></g><text x="${x3+42}" y="${midY}" fill="#a8754d" font-size="9" transform="rotate(90 ${x3+42} ${midY})" text-anchor="middle">7,000</text>`;
    $('#cadDimensions').innerHTML = dimLine(x0,x1,dimY,formatNumber(a)) + dimLine(x1,x2,dimY,formatNumber(b)) + dimLine(x2,x3,dimY,formatNumber(c)) + dimLine(x0,x3,y1+20,formatNumber(total)) + verticalDim;
    $('#cadSummary').textContent = `Illustrative geometry · ${formatNumber(total)} × ${formatNumber(height)} mm`;
  }

  function updateReviewState() {
    const verified = state.measurements.filter(item => item.verified).length;
    const total = state.measurements.length;
    const pending = total - verified;
    const sum = state.measurements.reduce((acc,item) => acc + (Number(item.value) || 0), 0);
    const overall = Number($('#overallValue').value) || 0;
    const chainMatches = overall > 0 && sum === overall;
    $('#verifiedCount').innerHTML = `${verified} <span>/ ${total}</span>`;
    $('#progressValue').style.width = `${(verified / total) * 100}%`;
    $('#progressLabel').textContent = `${Math.round((verified / total) * 100)}% reviewed`;
    $('#reviewCount').textContent = pending === 0 ? 'All reviewed' : `${pending} needs review`;
    $('#navReviewCount').textContent = String(pending);
    $('#navReviewCount').classList.toggle('hidden', pending === 0);
    $('#chainStatus').textContent = chainMatches ? 'Matches' : 'Mismatch';
    $('#chainStatus').classList.toggle('mismatch', !chainMatches);
    $('#overallCheck').querySelector('.overall-copy span').textContent = `${state.measurements.map(item => formatNumber(item.value)).join(' + ')} = ${formatNumber(sum)} mm`;
    $('#overallValue').disabled = !state.sample;
    const canVerify = state.sample && chainMatches;
    $('#verifyAllButton').disabled = !canVerify;
    $('#exportButton').disabled = !state.sample;
    $('#nextToPreview').disabled = !canOpenPreview();
    $('#stepNav3').disabled = !canOpenPreview();
    $('#verifyAllButton').style.opacity = canVerify ? '1' : '.55';
    $('#verifyAllButton').title = !state.sample ? 'Review will be available when OCR and geometry processing are connected' : chainMatches ? 'Mark all example measurements as reviewed' : 'Resolve the dimension-chain mismatch first';
    updateCadDrawing();
  }

  function makeDxf() {
    const a = Math.max(500, Number(state.measurements[0].value) || 3000);
    const b = Math.max(500, Number(state.measurements[1].value) || 4500);
    const c = Math.max(500, Number(state.measurements[2].value) || 2500);
    const width = a + b + c;
    const height = 7000;
    const midY = 3500;
    const x1 = a;
    const x2 = a + b;
    const lines = [
      [0,0,width,0,'WALLS'],[width,0,width,height,'WALLS'],[width,height,0,height,'WALLS'],[0,height,0,0,'WALLS'],
      [x1,0,x1,height,'WALLS'],[x2,0,x2,height,'WALLS'],
      [0,midY,x1,midY,'WALLS'],[x2,midY,width,midY,'WALLS'],
      [x1+100,midY,x1+900,midY,'OPENINGS'],[x2+100,height-500,x2+850,height-500,'OPENINGS']
    ];
    const pairs = [];
    const add = (code,value) => pairs.push(String(code),String(value));
    add(0,'SECTION'); add(2,'HEADER'); add(9,'$INSUNITS'); add(70,4); add(0,'ENDSEC');
    add(0,'SECTION'); add(2,'TABLES'); add(0,'TABLE'); add(2,'LAYER'); add(70,3);
    const layer = (name,color) => { add(0,'LAYER'); add(2,name); add(70,0); add(62,color); add(6,'CONTINUOUS'); };
    layer('WALLS',3); layer('OPENINGS',4); layer('DIMENSIONS',30);
    add(0,'ENDTAB'); add(0,'ENDSEC'); add(0,'SECTION'); add(2,'ENTITIES');
    lines.forEach(([x1p,y1p,x2p,y2p,layerName]) => {
      add(0,'LINE'); add(8,layerName); add(10,x1p); add(20,y1p); add(30,0); add(11,x2p); add(21,y2p); add(31,0);
    });
    // Dimension labels in this sample DXF are reference annotations, not associative CAD dimensions.
    [[a/2,-250,formatNumber(a)],[a+b/2,-250,formatNumber(b)],[a+b+c/2,-250,formatNumber(c)],[width/2,height+350,formatNumber(width) ]].forEach(([x,y,label]) => {
      add(0,'TEXT'); add(8,'DIMENSIONS'); add(10,x); add(20,y); add(30,0); add(40,180); add(1,String(label)); add(7,'STANDARD');
    });
    add(0,'ENDSEC'); add(0,'EOF');
    return pairs.join('\r\n') + '\r\n';
  }

  function exportDxf() {
    if (!state.sample) {
      showToast('DXF export is available for the sample geometry only; the uploaded scan has not been reconstructed.');
      return;
    }
    const blob = new Blob([makeDxf()], {type:'application/dxf'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'planline-sample-floorplan.dxf';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast('Sample DXF exported in millimetres.');
  }

  function bindEvents() {
    const openFilePicker = () => fileInput.click();
    $('#uploadTopButton').addEventListener('click', openFilePicker);
    $('#replaceFileButton').addEventListener('click', openFilePicker);
    $('#changeFileText').addEventListener('click', openFilePicker);
    $('#emptyUploadButton').addEventListener('click', openFilePicker);
    fileInput.addEventListener('change', event => {
      const file = event.target.files && event.target.files[0];
      void handleFile(file);
      fileInput.value = '';
    });
    $('#resetButton').addEventListener('click', resetSample);
    $$('.step-tab').forEach(tab => tab.addEventListener('click', () => showStep(tab.dataset.step)));
    $('#nextToReview').addEventListener('click', () => showStep(2));
    $('#nextToPreview').addEventListener('click', () => showStep(3));
    $$('.step-back').forEach(button => button.addEventListener('click', () => showStep(button.dataset.goStep)));
    $('#verifyAllButton').addEventListener('click', () => {
      const sum = state.measurements.reduce((acc,item) => acc + (Number(item.value) || 0), 0);
      const overall = Number($('#overallValue').value) || 0;
      if (sum !== overall) {
        showToast('The dimension chain does not match the overall dimension.');
        return;
      }
      state.measurements.forEach(item => item.verified = true);
      renderMeasurementRows();
      updateReviewState();
      showToast('All sample measurements marked as reviewed.');
    });
    $('#overallValue').addEventListener('input', () => updateReviewState());
    $('#exportButton').addEventListener('click', exportDxf);
    $('#fitViewButton').addEventListener('click', () => showToast('The sample drawing is already fitted to the preview.'));

    const sourceStage = $('#sourceStage');
    ['dragenter','dragover'].forEach(type => sourceStage.addEventListener(type, event => {
      event.preventDefault();
      document.body.classList.add('drag-active');
    }));
    ['dragleave','drop'].forEach(type => sourceStage.addEventListener(type, event => {
      event.preventDefault();
      document.body.classList.remove('drag-active');
    }));
    sourceStage.addEventListener('drop', event => {
      const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      void handleFile(file);
    });
    document.addEventListener('dragover', event => event.preventDefault());
    document.addEventListener('drop', event => {
      if (!sourceStage.contains(event.target)) event.preventDefault();
    });
    window.addEventListener('beforeunload', revokeObjectUrl);
  }

  bindEvents();
  renderMeasurementRows();
  updateReviewState();
  void checkApi();
})();

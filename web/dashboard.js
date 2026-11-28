const $ = (selector) => document.querySelector(selector);
async function refreshHealth() {
  const card = $("#healthCard");
  const dot = $("#healthDot");
  const label = $("#healthLabel");
  if (window.PLANLINE_PREVIEW === true) {
    $("#healthTitle").textContent = "Static preview";
    $("#healthDetails").textContent = "Backend services are disabled in this preview. Run Planline locally for live application health.";
    card.dataset.state = "preview";
    if (dot) dot.style.color = "#8b8b7d";
    if (label) label.textContent = "Static UI preview";
    $("#refreshHealth").hidden = true;
    return;
  }
  $("#healthTitle").textContent = "Connecting to local API";
  $("#healthDetails").textContent = "Checking application readiness…";
  try {
    const response = await fetch("/api/health", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Local API returned HTTP " + response.status);
    const health = await response.json();
    if (health.status !== "ok") throw new Error("Local API is not ready");
    const detector = health.detector_weights_present ? "detector ready" : "detector missing";
    const ocr = health.ocr_available ? "OCR ready" : "OCR runtime missing";
    const matching = health.dimension_association_available ? "dimension matching ready" : "dimension matching unavailable";
    const geometry = health.manual_geometry_available ? "manual geometry ready" : "manual geometry unavailable";
    $("#healthTitle").textContent = "Local API is online";
    $("#healthDetails").textContent = [health.version ? "Version " + health.version : "", detector, ocr, matching, geometry].filter(Boolean).join(" · ");
    card.dataset.state = health.detector_weights_present ? "ok" : "warning";
    if (dot) dot.style.color = health.detector_weights_present ? "#6d9a6e" : "#c08a38";
    if (label) label.textContent = health.detector_weights_present ? "Local services online" : "Detector model missing";
  } catch (error) {
    $("#healthTitle").textContent = "Local API unavailable";
    $("#healthDetails").textContent = error.message + " · Start Planline again or check the installation.";
    card.dataset.state = "error";
    if (dot) dot.style.color = "var(--red)";
    if (label) label.textContent = "API unavailable";
  }
}
$("#refreshHealth").addEventListener("click", refreshHealth);
refreshHealth();

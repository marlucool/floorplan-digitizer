const $ = (selector) => document.querySelector(selector);
async function refreshHealth() {
  const card = $("#healthCard");
  const dot = $("#healthDot");
  const label = $("#healthLabel");
  if (window.PLANLINE_PREVIEW === true) {
    $("#healthTitle").textContent = "Static preview";
    $("#healthDetails").textContent = "Backend services are disabled in this preview. Run Planline locally for live application health.";
    card.dataset.state = "preview";
    dot.style.background = "#8b8b7d";
    label.textContent = "Static UI preview";
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
    const detector = health.detector_weights_present ? "Detector weights available" : "Detector weights missing";
    $("#healthTitle").textContent = "Local API is online";
    $("#healthDetails").textContent = (health.version ? "Version " + health.version + " · " : "") + detector;
    card.dataset.state = "ok";
    dot.style.background = "#6d9a6e";
    label.textContent = "Local services online";
  } catch (error) {
    $("#healthTitle").textContent = "Local API unavailable";
    $("#healthDetails").textContent = error.message + " · Start Planline again or check the installation.";
    card.dataset.state = "error";
    dot.style.background = "var(--red)";
    label.textContent = "API unavailable";
  }
}
$("#refreshHealth").addEventListener("click", refreshHealth);
refreshHealth();

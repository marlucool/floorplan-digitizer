const $ = (selector) => document.querySelector(selector);
const moon='<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20.2 15.1A8.5 8.5 0 0 1 8.9 3.8 8.7 8.7 0 1 0 20.2 15.1Z"/></svg>';
const sun='<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg>';
const themeButton = $("#themeToggle");
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const dark = theme === "dark";
  themeButton.innerHTML = dark ? sun : moon;
  themeButton.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  themeButton.setAttribute("title", dark ? "Switch to light theme" : "Switch to dark theme");
  themeButton.setAttribute("aria-pressed", String(dark));
  try { localStorage.setItem("planline-theme", theme); } catch (_) {}
}
let savedTheme = "light";
try { savedTheme = localStorage.getItem("planline-theme") || "light"; } catch (_) {}
setTheme(savedTheme === "dark" ? "dark" : "light");
themeButton.addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});

async function refreshHealth() {
  const card = $("#healthCard");
  const dot = $("#healthDot");
  const label = $("#healthLabel");
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

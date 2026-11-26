const $ = (selector) => document.querySelector(selector);
const CHECK_KEY = "planline-auto-check-updates";

const themeButton = $("#themeToggle");
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const dark = theme === "dark";
  themeButton.innerHTML = dark ? '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg>' : '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20.2 15.1A8.5 8.5 0 0 1 8.9 3.8 8.7 8.7 0 1 0 20.2 15.1Z"/></svg>';
  themeButton.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  themeButton.setAttribute("title", dark ? "Switch to light theme" : "Switch to dark theme");
  themeButton.setAttribute("aria-pressed", String(dark));
  try { localStorage.setItem("planline-theme", theme); } catch (_) {}
}
let theme = "dark";
try { theme = localStorage.getItem("planline-theme") || "dark"; } catch (_) {}
setTheme(theme === "light" ? "light" : "dark");
themeButton.addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});

const autoCheck = $("#autoCheckUpdates");
try { autoCheck.checked = localStorage.getItem(CHECK_KEY) !== "false"; } catch (_) {}
autoCheck.addEventListener("change", () => {
  try { localStorage.setItem(CHECK_KEY, String(autoCheck.checked)); } catch (_) {}
});

let latest = null;
function setUpdateState(kind, title, message) {
  $("#updateIndicator").textContent = title;
  $("#updateIndicator").dataset.state = kind;
  $("#updateTitle").textContent = title;
  $("#updateMessage").textContent = message;
}
function showReleaseNotes(text) {
  const wrap = $("#releaseNotesWrap");
  if (!text || !text.trim()) {
    wrap.classList.add("hidden");
    $("#releaseNotes").textContent = "";
    return;
  }
  $("#releaseNotes").textContent = text;
  wrap.classList.remove("hidden");
}

async function checkUpdates() {
  const button = $("#checkUpdates");
  button.disabled = true;
  button.textContent = "Checking GitHub…";
  setUpdateState("checking", "Checking for updates", "Contacting the Planline GitHub Releases API…");
  $("#installUpdate").hidden = true;
  $("#viewRelease").classList.add("hidden");
  try {
    const response = await fetch("/api/updates/check", { cache: "no-store" });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "GitHub could not be checked.");
    latest = result;
    $("#currentVersion").textContent = "v" + result.current_version;
    $("#viewRelease").href = result.release_url || "https://github.com/marlucool/floorplan-digitizer/releases";
    $("#viewRelease").classList.remove("hidden");
    showReleaseNotes(result.release_notes || "");
    if (result.status === "update_available" && result.install_available) {
      setUpdateState("available", "Update available · v" + result.latest_version,
        result.message + (result.installer_size ? " Installer size: " + (result.installer_size / (1024 * 1024)).toFixed(1) + " MB." : ""));
      $("#installUpdate").hidden = false;
      $("#installUpdate").disabled = false;
    } else if (result.status === "update_available") {
      setUpdateState("warning", "Release found · installer unavailable", result.message);
    } else if (result.status === "no_release") {
      setUpdateState("neutral", "No release published yet", result.message);
      showReleaseNotes("");
    } else {
      setUpdateState("current", "You're up to date · v" + result.current_version, result.message);
    }
  } catch (error) {
    setUpdateState("error", "Update check failed", error.message || "GitHub could not be reached.");
    showReleaseNotes("");
  } finally {
    button.disabled = false;
    button.textContent = "Check for updates";
  }
}

$("#checkUpdates").addEventListener("click", checkUpdates);
$("#installUpdate").addEventListener("click", async () => {
  const button = $("#installUpdate");
  button.disabled = true;
  button.textContent = "Downloading and verifying…";
  setUpdateState("checking", "Preparing update", "Downloading the release installer and validating its SHA-256 checksum…");
  try {
    const response = await fetch("/api/updates/install", { method: "POST" });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "The update could not be prepared.");
    setUpdateState("available", "Installing v" + result.version, result.message);
    button.textContent = "Closing Planline…";
    window.setTimeout(async () => {
      try {
        if (window.pywebview?.api?.close_window) await window.pywebview.api.close_window();
        else window.close();
      } catch (_) { window.close(); }
    }, 900);
  } catch (error) {
    button.disabled = false;
    button.textContent = "Download and install update →";
    setUpdateState("error", "Update failed", error.message || "The update could not be installed.");
  }
});

async function loadCurrentVersion() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) return;
    const health = await response.json();
    if (health.version) $("#currentVersion").textContent = "v" + health.version;
  } catch (_) {}
}

if (window.PLANLINE_PREVIEW === true) {
  $("#currentVersion").textContent = "Unavailable in preview";
  setUpdateState("neutral", "Updates disabled in static preview", "Release checks and installation are available in the local desktop application.");
  $("#checkUpdates").disabled = true;
  $("#installUpdate").hidden = true;
} else {
  loadCurrentVersion();
  if (autoCheck.checked) checkUpdates();
}

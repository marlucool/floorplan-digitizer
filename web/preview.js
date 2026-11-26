/* Static desktop-UI preview. Included only by the GitHub Pages build. */
window.PLANLINE_PREVIEW = true;

(() => {
  const nativeFetch = window.fetch.bind(window);
  const demoDetections = [
    { id: "demo-001", class_name: "wall", confidence: 0.98, bbox: { x1: 120, y1: 115, x2: 1080, y2: 129, width: 960, height: 14 }, centre: { x: 600, y: 122 } },
    { id: "demo-002", class_name: "wall", confidence: 0.97, bbox: { x1: 120, y1: 115, x2: 134, y2: 735, width: 14, height: 620 }, centre: { x: 127, y: 425 } },
    { id: "demo-003", class_name: "wall", confidence: 0.96, bbox: { x1: 1066, y1: 115, x2: 1080, y2: 735, width: 14, height: 620 }, centre: { x: 1073, y: 425 } },
    { id: "demo-004", class_name: "wall", confidence: 0.98, bbox: { x1: 120, y1: 721, x2: 1080, y2: 735, width: 960, height: 14 }, centre: { x: 600, y: 728 } },
    { id: "demo-005", class_name: "wall", confidence: 0.94, bbox: { x1: 570, y1: 122, x2: 584, y2: 420, width: 14, height: 298 }, centre: { x: 577, y: 271 } },
    { id: "demo-006", class_name: "wall", confidence: 0.93, bbox: { x1: 570, y1: 414, x2: 1080, y2: 428, width: 510, height: 14 }, centre: { x: 825, y: 421 } },
    { id: "demo-007", class_name: "wall", confidence: 0.92, bbox: { x1: 790, y1: 421, x2: 804, y2: 728, width: 14, height: 307 }, centre: { x: 797, y: 574 } },
    { id: "demo-008", class_name: "dimension_line", confidence: 0.91, bbox: { x1: 145, y1: 55, x2: 1055, y2: 62, width: 910, height: 7 }, centre: { x: 600, y: 58.5 } },
    { id: "demo-009", class_name: "dimension_line", confidence: 0.89, bbox: { x1: 65, y1: 140, x2: 72, y2: 705, width: 7, height: 565 }, centre: { x: 68.5, y: 422.5 } },
    { id: "demo-010", class_name: "dimension_value", confidence: 0.95, bbox: { x1: 535, y1: 36, x2: 665, y2: 78, width: 130, height: 42 }, centre: { x: 600, y: 57 } },
    { id: "demo-011", class_name: "dimension_value", confidence: 0.92, bbox: { x1: 26, y1: 390, x2: 112, y2: 435, width: 86, height: 45 }, centre: { x: 69, y: 412.5 } }
  ];

  function jsonResponse(payload, status = 503) {
    return new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json", "X-Planline-Preview": "static-demo" }
    });
  }

  window.fetch = async (input, init = {}) => {
    const rawUrl = typeof input === "string" ? input : input.url;
    const url = new URL(rawUrl, window.location.href);
    if (!url.pathname.startsWith("/api/")) return nativeFetch(input, init);

    if (url.pathname === "/api/analyze" && (init.method || "GET").toUpperCase() === "POST") {
      return jsonResponse({
        filename: "planline-demo.png",
        source: { source_type: "image", page_count: 1, page_index: 0 },
        image: { width: 1200, height: 850 },
        preprocessing: { brightness: 0, contrast: 1, method: "demo-fixture" },
        preview_data_url: new URL("demo-floorplan.svg", document.baseURI).href,
        counts: { wall: 7, dimension_line: 2, dimension_value: 2 },
        confidence_threshold: 0.25,
        detections: demoDetections,
        dimension_regions: [],
        association_candidates: [],
        notes: [
          "This is a static interface demonstration using fixed sample detections.",
          "No detector, OCR model, training job or backend API is running.",
          "The sample confidence values and boxes are illustrative, not model output."
        ],
        export_ready: false
      }, 200);
    }

    return jsonResponse({
      detail: "Backend features are disabled in the public desktop UI preview. No files or drawings are sent to a server."
    });
  };

  window.addEventListener("DOMContentLoaded", async () => {
    const banner = document.createElement("aside");
    banner.setAttribute("role", "status");
    banner.style.cssText = "position:sticky;top:0;z-index:10000;display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:8px;padding:10px 16px;background:#263d2b;color:#fff;font:600 12px/1.4 'DM Sans',sans-serif;letter-spacing:.02em;text-align:center";
    banner.innerHTML = '<span>DESKTOP UI PREVIEW</span><span style="opacity:.65">·</span><span>Sample data only — no uploads, OCR, training or backend processing</span>';
    document.body.prepend(banner);

    const drawingPage = Boolean(document.querySelector("#fileInput"));
    if (!drawingPage) {
      document.querySelectorAll("input, select, textarea, button").forEach((control) => {
        if (control.id === "themeToggle" || control.id === "refreshHealth" ||
            control.classList.contains("view-nav-button")) return;
        control.disabled = true;
      });
      return;
    }

    ["#fileInput", "#exportReview", "#saveProject", "#exportDxf", "#checkChain", "#runOcrButton"].forEach((selector) => {
      const control = document.querySelector(selector);
      if (control) control.disabled = true;
    });

    const dropzone = document.querySelector("#dropzone");
    if (dropzone) {
      dropzone.style.pointerEvents = "none";
      dropzone.setAttribute("aria-disabled", "true");
      const title = dropzone.querySelector("strong");
      const detail = dropzone.querySelector("span");
      if (title) title.textContent = "Sample drawing loaded below";
      if (detail) detail.textContent = "Uploads are disabled in this preview";
    }

    try {
      const response = await nativeFetch(new URL("demo-floorplan.svg", document.baseURI));
      if (!response.ok) throw new Error("Could not load the demo drawing.");
      const blob = await response.blob();
      const file = new File([blob], "planline-demo.svg", { type: "image/svg+xml" });
      if (typeof window.setFile !== "function" || typeof window.analyse !== "function") {
        throw new Error("The drawing workspace did not finish loading.");
      }
      window.setFile(file);
      document.querySelector("#fileMeta").textContent = "Static sample · no upload";
      window.setTimeout(async () => {
        await window.analyse();
        ["#fileInput", "#exportReview", "#saveProject", "#exportDxf", "#checkChain", "#runOcrButton"].forEach((selector) => {
          const control = document.querySelector(selector);
          if (control) control.disabled = true;
        });
      }, 350);
    } catch (error) {
      const notice = document.querySelector("#notice");
      if (notice) {
        notice.classList.remove("hidden");
        notice.textContent = "Preview sample unavailable: " + error.message;
      }
    }
  });
})();

"""Render the maintained Planline architecture notes as a readable HTML page."""

from __future__ import annotations

import markdown


def render_architecture_page(
    markdown_source: str,
    *,
    asset_prefix: str = "/",
    home_href: str = "/",
    drawing_href: str = "/drawing",
    ocr_href: str = "/ocr",
    settings_href: str = "/settings",
    architecture_href: str = "/architecture",
    source_href: str = "https://github.com/marlucool/floorplan-digitizer/blob/main/docs/PLANLINE_ARCHITECTURE.md",
) -> str:
    """Render repository-owned Markdown inside the Planline application shell."""
    parser = markdown.Markdown(
        extensions=["fenced_code", "tables", "toc", "sane_lists"],
        extension_configs={"toc": {"toc_depth": "2-3"}},
    )
    article = parser.convert(markdown_source)
    toc = parser.toc or '<p class="architecture-toc-empty">No section links available.</p>'

    # All URL arguments are fixed by the application or the trusted static-site
    # builder. The Markdown source itself is repository-maintained, not user input.
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark light">
  <meta name="description" content="Planline implementation status, technical architecture, research notes and engineering roadmap.">
  <title>Planline — Architecture &amp; roadmap</title>
  <link rel="stylesheet" href="{asset_prefix}styles.css">
  <script>
    (() => {{
      try {{
        const saved = localStorage.getItem("planline-theme-v2");
        document.documentElement.dataset.theme = saved === "light" ? "light" : "dark";
      }} catch (_) {{
        document.documentElement.dataset.theme = "dark";
      }}
    }})();
  </script>
  <script src="{asset_prefix}theme.js" defer></script>
</head>
<body class="architecture-page">
  <a class="skip-link" href="#mainContent">Skip to content</a>
  <header class="topbar">
    <a class="brand" href="{home_href}" aria-label="Planline dashboard">
      <img class="brand-mark" src="{asset_prefix}icon.svg" alt=""><span>planline<span class="brand-dot">.</span></span>
    </a>
    <div class="top-meta"><span class="local-dot"></span><span>TECHNICAL REFERENCE</span></div>
    <button class="nav-menu-toggle" type="button" aria-label="Open navigation" aria-expanded="false" aria-controls="primaryNavigation"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button>
    <nav class="top-links" id="primaryNavigation" aria-label="Primary navigation">
      <a class="repo-link" href="{home_href}">Dashboard</a>
      <a class="repo-link" href="{drawing_href}">Drawing</a>
      <a class="repo-link" href="{ocr_href}">OCR Studio</a>
      <a class="repo-link" href="{settings_href}">Settings</a>
      <a class="repo-link" href="/documentation">Documentation</a>
      <a class="repo-link active" href="{architecture_href}" aria-current="page">Architecture</a>
      <button id="themeToggle" class="toolbar-button theme-toggle" type="button"
              aria-label="Switch to light theme" title="Switch to light theme" aria-pressed="false">
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <path d="M20.2 15.1A8.5 8.5 0 0 1 8.9 3.8 8.7 8.7 0 1 0 20.2 15.1Z"/>
        </svg>
      </button>
    </nav>
  </header>

  <div class="architecture-shell">
    <aside class="architecture-sidebar">
      <p class="eyebrow">ON THIS PAGE</p>
      <nav class="architecture-toc" aria-label="Architecture contents">{toc}</nav>
      <a class="architecture-source-link" href="{source_href}">View Markdown source ↗</a>
    </aside>

    <main class="architecture-main" id="mainContent">
      <div class="architecture-page-heading">
        <p class="eyebrow">PLANLINE / ENGINEERING NOTES</p>
        <p class="architecture-lede">What exists today, what is deliberately not automated, and what must be proven before Planline can produce measured CAD geometry.</p>
      </div>
      <article class="architecture-prose">{article}</article>
      <footer class="architecture-footer">
        <span>PLANLINE · 2D FLOOR-PLAN DIGITISATION</span>
        <span><a href="{home_href}">Back to dashboard</a> · <a href="https://github.com/marlucool/floorplan-digitizer" target="_blank" rel="noreferrer">Source repository ↗</a></span>
      </footer>
    </main>
  </div>
</body>
</html>
"""

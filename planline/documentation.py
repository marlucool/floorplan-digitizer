"""Browse and render the files maintained under the repository docs/ directory."""

from __future__ import annotations

import html
import mimetypes
import posixpath
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import markdown
from markdown.extensions.toc import slugify, unique

SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
SUPPORTED_CODE_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".css", ".html", ".htm", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".txt", ".csv", ".tsv", ".sh",
    ".bash", ".bat", ".cmd", ".ps1", ".xml", ".cs", ".sql", ".gitignore",
    ".md", ".markdown",
}


def _kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix == ".pdf":
        return "pdf"
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return "image"
    if suffix in SUPPORTED_CODE_SUFFIXES:
        return "source"
    return "download"


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _title_for(path: Path, kind: str) -> str:
    if kind == "markdown":
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[:30]:
                match = re.match(r"^#\s+(.+?)\s*#*\s*$", line)
                if match:
                    return match.group(1).strip()
        except (OSError, UnicodeError):
            pass
    return path.stem.replace("_", " ").replace("-", " ").strip().title()


def discover_documents(docs_root: Path) -> list[dict[str, Any]]:
    """Return a stable catalogue of every non-hidden file under docs_root."""
    root = Path(docs_root).resolve()
    if not root.is_dir():
        return []
    documents: list[dict[str, Any]] = []
    for source in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not source.is_file():
            continue
        relative = source.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        path = relative.as_posix()
        kind = _kind(path)
        if path.startswith("archive/"):
            group = "Archived references"
        elif kind == "image":
            group = "Images and examples"
        elif kind == "download":
            group = "Files and attachments"
        else:
            group = "Guides and technical references"
        try:
            size = source.stat().st_size
        except OSError:
            size = 0
        documents.append({
            "path": path,
            "title": _title_for(source, kind),
            "kind": kind,
            "group": group,
            "size": size,
            "size_label": _human_size(size),
            "suffix": source.suffix.lower().lstrip(".") or "file",
        })
    return documents


def _page_path(path: str) -> str:
    return f"documentation/{quote(path, safe='/')}.html"


def _rewrite_markdown_links(
    rendered: str,
    *,
    current_path: str,
    known_paths: set[str],
    static_site: bool,
    current_output_path: str,
) -> str:
    """Rewrite links to other docs so Markdown references open the right viewer."""
    current_parent = posixpath.dirname(current_path)

    def replace(match: re.Match[str]) -> str:
        attribute, raw_url = match.group(1), html.unescape(match.group(2))
        parts = urlsplit(raw_url)
        if (
            not parts.path
            or parts.scheme
            or parts.netloc
            or parts.path.startswith(("/", "data:"))
        ):
            return match.group(0)
        decoded_path = unquote(parts.path)
        target = posixpath.normpath(posixpath.join(current_parent, decoded_path))
        if target.startswith("../") or target == "..":
            return match.group(0)
        if target not in known_paths:
            return match.group(0)

        if _kind(target) == "markdown":
            destination = _page_path(target)
        else:
            destination = f"docs/{quote(target, safe='/')}"

        if static_site:
            link = posixpath.relpath(destination, posixpath.dirname(current_output_path) or ".")
        else:
            link = (
                f"/documentation/{quote(target, safe='/')}"
                if _kind(target) == "markdown"
                else f"/docs/{quote(target, safe='/')}"
            )
        rewritten = urlunsplit(("", "", link, parts.query, parts.fragment))
        return f'{attribute}="{html.escape(rewritten, quote=True)}"'

    return re.sub(r'\b(href|src)="([^"]*)"', replace, rendered)


def _document_catalog_html(
    documents: list[dict[str, Any]],
    *,
    static_site: bool,
    current_output_path: str,
) -> str:
    groups = (
        "Guides and technical references",
        "Images and examples",
        "Files and attachments",
        "Archived references",
    )
    chunks: list[str] = []
    for group in groups:
        items = [item for item in documents if item["group"] == group]
        if not items:
            continue
        rows = []
        for item in items:
            if static_site:
                destination = posixpath.relpath(
                    _page_path(item["path"]),
                    posixpath.dirname(current_output_path) or ".",
                )
            else:
                destination = f"/documentation/{quote(item['path'], safe='/')}"
            rows.append(
                f'<a class="documentation-file" href="{html.escape(destination, quote=True)}" '
                f'data-search="{html.escape((item["title"] + " " + item["path"] + " " + item["kind"]).casefold(), quote=True)}">'
                f'<span class="documentation-file-icon" aria-hidden="true">{_file_symbol(item["kind"])}</span>'
                f'<span class="documentation-file-name"><strong>{html.escape(item["title"])}</strong>'
                f'<small>{html.escape(item["path"])}</small></span>'
                f'<span class="documentation-file-meta"><span class="documentation-type">{html.escape(item["suffix"].upper())}</span>'
                f'<small>{html.escape(item["size_label"])}</small></span><span class="documentation-file-arrow" aria-hidden="true">→</span></a>'
            )
        chunks.append(
            f'<section class="documentation-group"><div class="documentation-group-heading">'
            f'<h2>{html.escape(group)}</h2><span>{len(items)} files</span></div>'
            + "".join(rows)
            + "</section>"
        )
    return "".join(chunks) or '<p class="documentation-empty">No documentation files were found.</p>'


def _file_symbol(kind: str) -> str:
    return {
        "markdown": "¶",
        "source": "{ }",
        "pdf": "PDF",
        "image": "▧",
        "download": "↓",
    }.get(kind, "•")


def _navigation(
    *,
    home_href: str,
    drawing_href: str,
    ocr_href: str,
    settings_href: str,
    documentation_href: str,
) -> str:
    return f"""
  <header class="topbar">
    <a class="brand" href="{home_href}" aria-label="Planline dashboard"><span class="brand-mark">P</span><span>planline<span class="brand-dot">.</span></span></a>
    <div class="top-meta"><span class="local-dot"></span><span>DOCUMENTATION</span></div>
    <nav class="top-links" aria-label="Main navigation">
      <a class="repo-link" href="{home_href}">Dashboard</a>
      <a class="repo-link" href="{drawing_href}">Drawing workspace</a>
      <a class="repo-link" href="{ocr_href}">OCR Studio</a>
      <a class="repo-link" href="{settings_href}">Settings</a>
      <a class="repo-link active" href="{documentation_href}" aria-current="page">Documentation</a>\n      <a class="repo-link" href="/architecture">Architecture</a>
      <button id="themeToggle" class="toolbar-button theme-toggle" type="button" aria-label="Switch to light theme" title="Switch to light theme" aria-pressed="false">
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20.2 15.1A8.5 8.5 0 0 1 8.9 3.8 8.7 8.7 0 1 0 20.2 15.1Z"/></svg>
      </button>
    </nav>
  </header>
"""


def _page_shell(
    *,
    title: str,
    asset_prefix: str,
    home_href: str,
    drawing_href: str,
    ocr_href: str,
    settings_href: str,
    documentation_href: str,
    body: str,
    description: str = "Planline documentation, technical references and supporting files.",
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <meta name="theme-color" content="#0b1017">
  <meta name="color-scheme" content="dark light">
  <meta name="description" content="{html.escape(description, quote=True)}">
  <title>{html.escape(title)} — Planline</title>
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
  <script>
    (() => {{
      const root = document.documentElement;
      const syncOffset = () => {{
        const header = document.querySelector(".topbar");
        if (!header) return;
        root.style.setProperty("--docs-anchor-offset", Math.ceil(header.getBoundingClientRect().height + 16) + "px");
      }};
      document.addEventListener("DOMContentLoaded", () => {{
        syncOffset();
        const header = document.querySelector(".topbar");
        if (header && "ResizeObserver" in window) new ResizeObserver(syncOffset).observe(header);
      }}, {{ once: true }});
      window.addEventListener("resize", syncOffset, {{ passive: true }});
    }})();
  </script>
</head>
<body class="documentation-page">
{_navigation(home_href=home_href, drawing_href=drawing_href, ocr_href=ocr_href, settings_href=settings_href, documentation_href=documentation_href)}
{body}
</body>
</html>
"""


def render_documentation_index(
    documents: list[dict[str, Any]],
    *,
    static_site: bool = False,
    current_output_path: str = "documentation/index.html",
    asset_prefix: str = "/",
    home_href: str = "/",
    drawing_href: str = "/drawing",
    ocr_href: str = "/ocr",
    settings_href: str = "/settings",
    documentation_href: str = "/documentation",
) -> str:
    rows = _document_catalog_html(
        documents,
        static_site=static_site,
        current_output_path=current_output_path,
    )
    body = f"""
  <main class="documentation-hub">
    <section class="documentation-hero">
      <p class="eyebrow">PLANLINE / KNOWLEDGE BASE</p>
      <h1>Documentation<span>.</span></h1>
      <p>Technical guides, architecture notes, data-quality references and supporting files. The contents are generated from the repository's <code>docs/</code> folder.</p>
      <label class="documentation-search"><span>Search files</span><input id="documentationSearch" type="search" placeholder="Search by title, filename or type" autocomplete="off"><span id="documentationResultCount">{len(documents)} files</span></label>
    </section>
    <div class="documentation-list" id="documentationList">{rows}</div>
    <footer class="documentation-footer"><span>PLANLINE · DOCUMENTATION</span><span><a href="https://github.com/marlucool/floorplan-digitizer/tree/main/docs" target="_blank" rel="noreferrer">Browse docs on GitHub ↗</a></span></footer>
  </main>
  <script>
    (() => {{
      const input = document.querySelector("#documentationSearch");
      const rows = [...document.querySelectorAll(".documentation-file")];
      const counter = document.querySelector("#documentationResultCount");
      const groups = [...document.querySelectorAll(".documentation-group")];
      input?.addEventListener("input", () => {{
        const query = input.value.trim().toLocaleLowerCase();
        let visible = 0;
        for (const row of rows) {{
          const shown = !query || row.dataset.search.includes(query);
          row.hidden = !shown;
          if (shown) visible += 1;
        }}
        for (const group of groups) {{
          group.hidden = !group.querySelector(".documentation-file:not([hidden])");
        }}
        if (counter) counter.textContent = visible + (visible === 1 ? " file" : " files");
      }});
    }})();
  </script>
"""
    return _page_shell(
        title="Documentation",
        asset_prefix=asset_prefix,
        home_href=home_href,
        drawing_href=drawing_href,
        ocr_href=ocr_href,
        settings_href=settings_href,
        documentation_href=documentation_href,
        body=body,
        description="Browse all Planline documentation and reference files.",
    )


def _add_heading_ids_and_render_toc(rendered_html: str) -> tuple[str, str]:
    """Ensure stable heading anchors, then build the sidebar TOC from those IDs."""
    heading_pattern = re.compile(
        r'<h([1-6])([^>]*)>(.*?)</h[1-6]>',
        re.IGNORECASE | re.DOTALL,
    )
    used_ids: set[str] = set()
    entries: list[str] = []

    def add_heading(match: re.Match[str]) -> str:
        level_text, attributes, inner_html = match.groups()
        level = int(level_text)
        label = re.sub(r"<[^>]+>", " ", inner_html)
        label = re.sub(r"\s+", " ", html.unescape(label)).strip()

        existing = re.search(r'\bid="([^"]+)"', attributes, re.IGNORECASE)
        if existing:
            anchor_id = unique(existing.group(1), used_ids)
            if anchor_id != existing.group(1):
                attributes = re.sub(
                    r'\bid="[^"]+"',
                    f'id="{html.escape(anchor_id, quote=True)}"',
                    attributes,
                    count=1,
                    flags=re.IGNORECASE,
                )
        else:
            base_id = slugify(label, "-") or f"section-{level}"
            anchor_id = unique(base_id, used_ids)
            attributes = attributes.rstrip() + f' id="{html.escape(anchor_id, quote=True)}"'

        if 2 <= level <= 4 and label:
            entries.append(
                f'<li class="documentation-toc-level-{level}">'
                f'<a href="#{html.escape(anchor_id, quote=True)}">{html.escape(label)}</a></li>'
            )
        return f"<h{level_text}{attributes}>{inner_html}</h{level_text}>"

    rendered = heading_pattern.sub(add_heading, rendered_html)
    toc = (
        '<ul class="documentation-toc-list">' + "".join(entries) + "</ul>"
        if entries
        else '<p class="documentation-muted">No section links available.</p>'
    )
    return rendered, toc


def render_document_page(
    document: dict[str, Any],
    content: bytes,
    documents: list[dict[str, Any]],
    *,
    static_site: bool = False,
    current_output_path: str,
    asset_prefix: str,
    home_href: str,
    drawing_href: str,
    ocr_href: str,
    settings_href: str,
    documentation_href: str,
) -> str:
    path = str(document["path"])
    kind = str(document["kind"])
    known_paths = {str(item["path"]) for item in documents}
    title = str(document["title"])
    body_content = ""
    toc_html = ""

    if kind == "markdown":
        parser = markdown.Markdown(
            extensions=["fenced_code", "tables", "toc", "sane_lists"],
            extension_configs={"toc": {"toc_depth": "2-4"}},
        )
        markdown_source = content.decode("utf-8-sig")
        rendered = parser.convert(markdown_source)
        rendered, toc_html = _add_heading_ids_and_render_toc(rendered)
        rendered = _rewrite_markdown_links(
            rendered,
            current_path=path,
            known_paths=known_paths,
            static_site=static_site,
            current_output_path=current_output_path,
        )
        body_content = rendered
    elif kind == "image":
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        raw_href = f"docs/{quote(path, safe='/')}" if static_site else f"/docs/{quote(path, safe='/')}"
        if static_site:
            raw_href = posixpath.relpath(raw_href, posixpath.dirname(current_output_path) or ".")
        body_content = (
            f'<figure class="documentation-image"><img src="{html.escape(raw_href, quote=True)}" '
            f'alt="{html.escape(title, quote=True)}" loading="lazy"><figcaption>{html.escape(path)} · {html.escape(mime)}</figcaption></figure>'
        )
    elif kind == "pdf":
        raw_href = f"docs/{quote(path, safe='/')}" if static_site else f"/docs/{quote(path, safe='/')}"
        if static_site:
            raw_href = posixpath.relpath(raw_href, posixpath.dirname(current_output_path) or ".")
        body_content = (
            f'<div class="documentation-pdf"><iframe src="{html.escape(raw_href, quote=True)}" title="{html.escape(title, quote=True)}"></iframe></div>'
            f'<p><a href="{html.escape(raw_href, quote=True)}" target="_blank" rel="noreferrer">Open PDF in a new tab ↗</a></p>'
        )
    elif kind == "source":
        try:
            source = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            source = ""
        if source:
            body_content = f'<pre class="documentation-code"><code>{html.escape(source)}</code></pre>'
        else:
            body_content = '<p>This file cannot be displayed as UTF-8 text. Use the download link below.</p>'
    else:
        raw_href = f"docs/{quote(path, safe='/')}" if static_site else f"/docs/{quote(path, safe='/')}"
        if static_site:
            raw_href = posixpath.relpath(raw_href, posixpath.dirname(current_output_path) or ".")
        body_content = (
            f'<p>This file type is provided as a downloadable attachment.</p>'
            f'<p><a class="documentation-download" href="{html.escape(raw_href, quote=True)}" download>Download {html.escape(Path(path).name)} ↓</a></p>'
        )

    source_href = f"docs/{quote(path, safe='/')}" if static_site else f"/docs/{quote(path, safe='/')}"
    if static_site:
        source_href = posixpath.relpath(source_href, posixpath.dirname(current_output_path) or ".")
    sidebar_links = _document_catalog_html(
        documents,
        static_site=static_site,
        current_output_path=current_output_path,
    )
    source_link_attributes = (
        "download"
        if kind in {"source", "download"}
        else 'target="_blank" rel="noreferrer"'
    )
    source_link_label = (
        "Download original source ↓"
        if kind in {"source", "download"}
        else "Open original file ↗"
    )

    body = f"""
  <main class="documentation-layout">
    <aside class="documentation-sidebar">
      <a class="documentation-back" href="{documentation_href}">← All documentation</a>
      <p class="eyebrow">FILES</p>
      <nav class="documentation-file-list">{sidebar_links}</nav>
      {"<p class='eyebrow documentation-toc-heading'>ON THIS PAGE</p><nav class='documentation-toc' aria-label='On this page'>" + toc_html + "</nav>" if toc_html else ""}
    </aside>
    <article class="documentation-article">
      <div class="documentation-article-heading">
        <p class="eyebrow">{html.escape(str(document["group"]).upper())} / {html.escape(str(document["suffix"]).upper())}</p>
        <h1>{html.escape(title)}</h1>
        <p class="documentation-path">{html.escape(path)} · {html.escape(str(document["size_label"]))}</p>
        <a class="documentation-source-link" href="{html.escape(source_href, quote=True)}" {source_link_attributes}>{source_link_label}</a>
      </div>
      <div class="documentation-prose">{body_content}</div>
      <footer class="documentation-footer"><span>PLANLINE · DOCUMENTATION</span><span><a href="{documentation_href}">Back to documentation</a></span></footer>
    </article>
  </main>
"""
    # Keep the doc path available for assistive technology and browser tests.
    return _page_shell(
        title=title,
        asset_prefix=asset_prefix,
        home_href=home_href,
        drawing_href=drawing_href,
        ocr_href=ocr_href,
        settings_href=settings_href,
        documentation_href=documentation_href,
        body=body,
        description=f"Planline documentation: {path}",
    )


def safe_document_path(docs_root: Path, requested_path: str) -> Path:
    """Resolve a requested file without allowing traversal outside docs_root."""
    root = Path(docs_root).resolve()
    decoded = unquote(requested_path).replace("\\", "/")
    candidate = (root / decoded).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise FileNotFoundError(requested_path)
    return candidate

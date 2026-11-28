from __future__ import annotations

import re
from pathlib import Path

from scripts.build_ui_preview import PAGE_SOURCES, build_preview
from planline.documentation import discover_documents


def test_preview_contains_every_workspace_and_uses_one_stylesheet(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "site")

    for page in ("index.html", "drawing.html", "ocr.html", "settings.html"):
        assert (output / page).is_file(), f"Missing preview page: {page}"
    for asset in ("app.js", "dashboard.js", "ocr-studio.js", "settings.js", "theme.js",
                  "styles.css", "preview.js", "demo-floorplan.svg", "architecture.html",
                  "architecture-source.md", "documentation/index.html", ".nojekyll"):
        assert (output / asset).is_file(), f"Missing preview asset: {asset}"

    assert not (output / "dashboard.css").exists()
    assert not (output / "settings.css").exists()
    assert not (output / "ocr-studio.css").exists()

    for page in output.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        links = re.findall(r'(?:href|src)="([^"]+)"', html)
        for link in links:
            if link.startswith(("http://", "https://", "data:", "#")):
                continue
            local = link.split("?", 1)[0].split("#", 1)[0]
            if local.endswith((".css", ".js", ".svg", ".png", ".webp", ".woff", ".woff2")):
                assert (output / local).is_file(), f"{page.name} references missing asset {local}"

    assert (output / "architecture.md").is_dir()
    assert (output / "architecture.md" / "index.html").is_file()
    architecture = (output / "architecture.html").read_text(encoding="utf-8")
    legacy_architecture = (output / "architecture.md" / "index.html").read_text(encoding="utf-8")
    assert '<article class="documentation-article">' in architecture
    assert "class='documentation-toc'" in architecture
    assert 'href="documentation/index.html"' in architecture
    assert 'href="styles.css"' in architecture
    assert 'src="theme.js" defer' in architecture
    assert 'href="../styles.css"' in legacy_architecture
    assert 'src="../theme.js" defer' in legacy_architecture
    assert "Planline architecture and implementation roadmap" in architecture

    documents = discover_documents(Path(__file__).resolve().parents[1] / "docs")
    assert len(documents) > 5
    assert (output / "documentation" / "ARCHITECTURE.md.html").is_file()
    assert (output / "documentation" / "OCR_DATASET_QUALITY.md.html").is_file()
    assert (output / "documentation" / "PLANLINE_ARCHITECTURE.md.html").is_file()
    assert (output / "documentation" / "archive" / "planline-webui-prototype" / "backend" / "app.py.html").is_file()
    assert (output / "docs" / "rysunek.png").is_file()

    hub = (output / "documentation" / "index.html").read_text(encoding="utf-8")
    assert "Guides and technical references" in hub
    assert "Images and examples" in hub
    assert "Archived references" in hub
    assert 'href="ARCHITECTURE.md.html"' in hub
    assert 'href="rysunek.png.html"' in hub

    architecture_notes = (output / "documentation" / "ARCHITECTURE.md.html").read_text(encoding="utf-8")
    assert 'href="PLANLINE_ARCHITECTURE.md.html"' in architecture_notes
    assert 'class="documentation-file is-active"' in architecture_notes
    stylesheet = (output / "styles.css").read_text(encoding="utf-8")
    assert "minmax(320px,350px)" in stylesheet
    assert ".documentation-toc{font-size:13px" in stylesheet
    assert ".documentation-file-name strong{font-size:13px" in stylesheet
    assert "--app-accent:#557b58" in stylesheet
    assert ".dashboard-workspaces{display:grid" in stylesheet
    assert ".documentation-layout{grid-template-columns:minmax(340px,380px)" in stylesheet
    assert ".documentation-prose{font-size:16px" in stylesheet

    for page in (output / "documentation").rglob("*.html"):
        page_html = page.read_text(encoding="utf-8")
        for link in re.findall(r'(?:href|src)="([^"]+)"', page_html):
            if link.startswith(("http://", "https://", "data:", "#", "mailto:")):
                continue
            local = link.split("?", 1)[0].split("#", 1)[0]
            if Path(local).suffix:
                assert (page.parent / local).resolve().is_file(), f"{page.relative_to(output)} references missing {local}"


def test_preview_navigation_opens_dashboard_and_keeps_pages_separate(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "site")
    dashboard = (output / "index.html").read_text(encoding="utf-8")
    drawing = (output / "drawing.html").read_text(encoding="utf-8")
    ocr = (output / "ocr.html").read_text(encoding="utf-8")
    settings = (output / "settings.html").read_text(encoding="utf-8")

    assert 'href="index.html" aria-label="Planline dashboard"' in dashboard
    assert 'href="index.html" aria-current="page">Dashboard</a>' in dashboard
    assert 'href="drawing.html"' in dashboard
    assert 'href="ocr.html"' in dashboard
    assert 'href="settings.html"' in dashboard

    for page, app_script in ((drawing, "app.js"), (ocr, "ocr-studio.js"), (settings, "settings.js")):
        assert 'href="index.html"' in page
        assert 'href="drawing.html"' in page
        assert 'href="styles.css"' in page
        assert 'src="theme.js" defer></script>' in page
        assert 'src="preview.js" defer></script>' in page
        assert f'src="{app_script}" defer></script>' in page

    assert 'src="theme.js" defer></script>' in dashboard
    assert 'src="preview.js" defer></script>' in dashboard
    assert 'src="dashboard.js" defer></script>' in dashboard
    assert 'dashboard.css' not in dashboard
    assert 'settings.css' not in settings
    assert 'ocr-studio.css' not in ocr


def test_nested_pr_preview_contains_dashboard_and_drawing_entry_points(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "_site" / "pr-preview" / "34")

    for page in ("index.html", "drawing.html", "ocr.html", "settings.html"):
        assert (output / page).is_file()
    dashboard = (output / "index.html").read_text(encoding="utf-8")
    drawing = (output / "drawing.html").read_text(encoding="utf-8")
    assert 'href="drawing.html"' in dashboard
    assert 'href="index.html" aria-label="Planline dashboard"' in drawing
    assert (output / "theme.js").is_file()
    assert (output / "documentation" / "index.html").is_file()
    assert (output / "documentation" / "PLANLINE_ARCHITECTURE.md.html").is_file()
    assert (output / "docs" / "rysunek.png").is_file()

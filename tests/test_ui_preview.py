from __future__ import annotations

import re
from pathlib import Path

from scripts.build_ui_preview import PAGE_SOURCES, build_preview


def test_preview_contains_every_workspace_and_uses_one_stylesheet(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "site")

    for page in ("index.html", "drawing.html", "ocr.html", "settings.html"):
        assert (output / page).is_file(), f"Missing preview page: {page}"
    for asset in ("app.js", "dashboard.js", "ocr-studio.js", "settings.js", "theme.js",
                  "styles.css", "preview.js", "demo-floorplan.svg", ".nojekyll"):
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

    assert (output / "architecture.md").is_file()


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
        assert 'src="styles.css"' in page
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

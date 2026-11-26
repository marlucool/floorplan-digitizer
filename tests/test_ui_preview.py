from __future__ import annotations

from pathlib import Path

from scripts.build_ui_preview import PAGES, build_preview


def test_preview_contains_all_available_workspaces_and_static_assets(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "site")

    assert (output / "index.html").is_file()  # Dashboard is the site landing page.
    assert (output / "drawing.html").is_file()
    assert (output / "app.js").is_file()
    assert (output / "theme.js").is_file()
    assert (output / "styles.css").is_file()
    assert (output / "preview.js").is_file()
    assert (output / "demo-floorplan.svg").is_file()
    assert (output / ".nojekyll").is_file()

    source_pages = {
        "drawing.html": "index.html",
        "index.html": "dashboard.html",
        "ocr.html": "ocr.html",
        "settings.html": "settings.html",
    }
    for output_page, assets in PAGES.items():
        source = Path("web") / source_pages[output_page]
        if source.is_file():
            assert (output / output_page).is_file(), f"Missing preview page: {output_page}"
            for asset in assets:
                assert (output / asset).is_file(), f"Missing asset for {output_page}: {asset}"

    assert (output / "ocr.html").is_file()
    assert (output / "settings.html").is_file()
    assert (output / "dashboard.js").is_file()
    assert not (output / "dashboard.css").exists()
    assert not (output / "settings.css").exists()
    assert not (output / "ocr-studio.css").exists()
    if (Path("docs") / "PLANLINE_ARCHITECTURE.md").is_file():
        assert (output / "architecture.md").is_file()
    assert not (output / "api").exists()


def test_preview_rewrites_routes_and_injects_preview_guard(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "site")
    dashboard = (output / "index.html").read_text(encoding="utf-8")
    drawing = (output / "drawing.html").read_text(encoding="utf-8")

    assert 'href="styles.css"' in dashboard
    assert 'src="preview.js" defer></script>' in dashboard
    assert 'src="dashboard.js" defer></script>' in dashboard
    assert 'src="theme.js" defer></script>' in dashboard
    assert 'href="drawing.html"' in dashboard
    assert 'href="settings.html"' in dashboard
    assert 'href="styles.css"' in drawing
    assert 'src="app.js" defer></script>' in drawing
    assert 'src="theme.js" defer></script>' in drawing
    assert 'href="index.html"' in drawing
    assert 'href="ocr.html"' in drawing
    assert 'href="settings.html"' in drawing
    assert 'href="/api/' not in drawing

    ocr = (output / "ocr.html").read_text(encoding="utf-8")
    settings = (output / "settings.html").read_text(encoding="utf-8")
    assert 'href="index.html"' in ocr
    assert 'href="index.html"' in settings
    assert 'src="ocr-studio.js"' in ocr
    assert 'src="settings.js"' in settings
    assert 'src="preview.js" defer></script>' in ocr
    assert 'src="preview.js" defer></script>' in settings


def test_preview_build_supports_nested_pr_subdirectory_urls(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "_site" / "pr-preview" / "123")

    for page in ("index.html", "drawing.html", "ocr.html", "settings.html"):
        assert (output / page).is_file()
    assert (output / "styles.css").is_file()
    html = (output / "index.html").read_text(encoding="utf-8")
    drawing = (output / "drawing.html").read_text(encoding="utf-8")
    assert 'href="styles.css"' in html
    assert 'src="dashboard.js" defer></script>' in html
    assert 'src="app.js" defer></script>' in drawing
    assert 'src="theme.js" defer></script>' in drawing
    assert 'src="dashboard.js" defer></script>' in html
    assert (output / "demo-floorplan.svg").is_file()

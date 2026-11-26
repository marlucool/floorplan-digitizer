from __future__ import annotations

from pathlib import Path

from scripts.build_ui_preview import PAGE_SOURCES, build_preview


def test_preview_contains_dashboard_first_workspaces_and_referenced_assets(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "site")

    assert (output / "index.html").is_file()
    assert (output / "drawing.html").is_file()
    assert (output / "ocr.html").is_file()
    assert (output / "settings.html").is_file()
    assert (output / "preview.js").is_file()
    assert (output / "demo-floorplan.svg").is_file()
    assert (output / ".nojekyll").is_file()

    for source_name in PAGE_SOURCES.values():
        source = Path("web") / source_name
        if source.exists():
            assert source.is_file()

    for page in output.glob("*.html"):
        html = page.read_text(encoding="utf-8")
        for asset in html.split('href="')[1:]:
            local = asset.split('"', 1)[0]
            if local.endswith((".css", ".js", ".svg", ".png", ".webp")):
                assert (output / local).is_file(), f"Missing {local} referenced by {page.name}"

    if (Path("docs") / "PLANLINE_ARCHITECTURE.md").is_file():
        assert (output / "architecture.md").is_file()
    assert not (output / "api").exists()


def test_preview_rewrites_navigation_with_dashboard_as_home(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "site")
    dashboard = (output / "index.html").read_text(encoding="utf-8")
    drawing = (output / "drawing.html").read_text(encoding="utf-8")
    ocr = (output / "ocr.html").read_text(encoding="utf-8")
    settings = (output / "settings.html").read_text(encoding="utf-8")

    assert 'href="index.html" aria-label="Planline dashboard"' in dashboard
    assert 'href="drawing.html"' in dashboard
    assert 'href="ocr.html"' in dashboard
    assert 'href="settings.html"' in dashboard
    assert 'src="preview.js" defer></script>' in dashboard
    assert 'src="dashboard.js" defer></script>' in dashboard

    assert 'href="index.html" aria-label="Planline dashboard"' in drawing
    assert 'src="preview.js" defer></script>' in drawing
    assert 'src="app.js" defer></script>' in drawing

    for page, script in ((ocr, "ocr-studio.js"), (settings, "settings.js")):
        assert 'href="index.html"' in page
        assert 'href="drawing.html"' in page
        assert 'src="preview.js" defer></script>' in page
        assert f'src="{script}" defer></script>' in page
        assert 'href="/api/' not in page


def test_preview_build_supports_nested_pr_subdirectory_urls(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "_site" / "pr-preview" / "123")

    for page in ("index.html", "drawing.html", "ocr.html", "settings.html"):
        assert (output / page).is_file()
    assert (output / "styles.css").is_file()
    assert (output / "preview.js").is_file()
    assert (output / "demo-floorplan.svg").is_file()
    dashboard = (output / "index.html").read_text(encoding="utf-8")
    assert 'href="drawing.html"' in dashboard

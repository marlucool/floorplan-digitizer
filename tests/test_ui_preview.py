from __future__ import annotations

from pathlib import Path

from scripts.build_ui_preview import PAGES, build_preview


def test_preview_contains_all_available_workspaces_and_static_assets(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "site")

    assert (output / "index.html").is_file()
    assert (output / "app.js").is_file()
    assert (output / "styles.css").is_file()
    assert (output / "preview.js").is_file()
    assert (output / "demo-floorplan.svg").is_file()
    assert (output / ".nojekyll").is_file()

    for page, assets in PAGES.items():
        source = Path("web") / page
        if source.is_file():
            assert (output / page).is_file(), f"Missing preview page: {page}"
            for asset in assets:
                assert (output / asset).is_file(), f"Missing asset for {page}: {asset}"

    assert (output / "ocr.html").is_file()
    assert (output / "settings.html").is_file()
    if (Path("web") / "dashboard.html").is_file():
        assert (output / "dashboard.html").is_file()
        assert (output / "dashboard.js").is_file()
        assert (output / "dashboard.css").is_file()
    if (Path("docs") / "PLANLINE_ARCHITECTURE.md").is_file():
        assert (output / "architecture.md").is_file()
    assert not (output / "api").exists()


def test_preview_rewrites_routes_and_injects_preview_guard(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "site")
    drawing = (output / "index.html").read_text(encoding="utf-8")

    assert 'href="styles.css"' in drawing
    assert 'src="preview.js" defer></script>' in drawing
    assert 'src="app.js" defer></script>' in drawing
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

    for page in ("index.html", "ocr.html", "settings.html"):
        assert (output / page).is_file()
    assert (output / "styles.css").is_file()
    html = (output / "index.html").read_text(encoding="utf-8")
    assert 'href="styles.css"' in html
    assert 'src="app.js" defer></script>' in html
    assert (output / "demo-floorplan.svg").is_file()

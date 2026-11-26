from __future__ import annotations

from pathlib import Path

from scripts.build_ui_preview import build_preview


def test_preview_build_contains_only_static_ui_assets(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "site")

    assert (output / "index.html").is_file()
    assert (output / "app.js").is_file()
    assert (output / "styles.css").is_file()
    assert (output / "preview.js").is_file()
    assert (output / "demo-floorplan.svg").is_file()
    assert not (output / "ocr.html").exists()
    assert not (output / "settings.html").exists()


def test_preview_build_rewrites_assets_and_disables_backend_pages(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "site")
    html = (output / "index.html").read_text(encoding="utf-8")

    assert 'href="styles.css"' in html
    assert 'src="preview.js" defer></script>' in html
    assert 'src="app.js" defer></script>' in html
    assert 'href="/api/' not in html
    assert 'href="#preview-disabled"' in html


def test_preview_build_supports_pr_subdirectory_urls(tmp_path: Path) -> None:
    output = build_preview(tmp_path / "_site" / "pr-preview" / "123")

    assert (output / "index.html").is_file()
    html = (output / "index.html").read_text(encoding="utf-8")
    assert 'href="styles.css"' in html
    assert 'src="app.js" defer></script>' in html
    assert (output / "demo-floorplan.svg").is_file()

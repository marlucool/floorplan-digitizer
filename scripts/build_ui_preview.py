"""Build a backend-free, multi-page static copy of the Planline desktop UI."""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

# Each page is copied only when that workspace exists in the source revision.
PAGES = {
    "drawing.html": ("app.js", "styles.css", "theme.js"),
    "index.html": ("dashboard.js", "styles.css", "theme.js"),
    "ocr.html": ("ocr-studio.js", "styles.css", "theme.js"),
    "settings.html": ("settings.js", "styles.css", "theme.js"),
}
SHARED_ASSETS = ("preview.js", "demo-floorplan.svg")
ROUTES = {
    "/": "index.html",
    "/dashboard": "index.html",
    "/drawing": "drawing.html",
    "/ocr": "ocr.html",
    "/settings": "settings.html",
    "/architecture": "architecture.md",
}


def rewrite_routes(html: str) -> str:
    """Rewrite server-root routes to files relative to the preview directory."""
    for route, target in sorted(ROUTES.items(), key=lambda item: len(item[0]), reverse=True):
        html = html.replace(f'href="{route}"', f'href="{target}"')
    html = re.sub(r'(href|src)="/([^"]+)"', lambda match: f'{match.group(1)}="{match.group(2)}"', html)
    return html


def prepare_page(source: Path, destination: Path) -> None:
    html = rewrite_routes(source.read_text(encoding="utf-8"))
    script = re.search(r'<script src="([^"]+\.js)" defer></script>', html)
    if not script:
        raise RuntimeError(f"Could not find the deferred application script in {source.name}.")
    preview_tag = '<script src="preview.js" defer></script>\n  '
    if "src=\"preview.js\"" not in html:
        html = html[:script.start()] + preview_tag + html[script.start():]
    destination.write_text(html, encoding="utf-8")


def build_preview(output_dir: Path) -> Path:
    """Build all available workspaces as a static site suitable for nested PR URLs."""
    output_dir = Path(output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    copied_assets: set[str] = set()
    page_count = 0
    source_pages = {
        "drawing.html": "index.html",
        "index.html": "dashboard.html",
        "ocr.html": "ocr.html",
        "settings.html": "settings.html",
    }
    for output_name, assets in PAGES.items():
        source = WEB / source_pages[output_name]
        if not source.is_file():
            continue
        prepare_page(source, output_dir / output_name)
        page_count += 1
        copied_assets.update(assets)

    if "index.html" not in {path.name for path in output_dir.glob("*.html")} or "drawing.html" not in {path.name for path in output_dir.glob("*.html")}:
        raise RuntimeError("The dashboard and drawing workspace are both required to build a preview.")

    for asset in sorted(copied_assets | set(SHARED_ASSETS)):
        source = WEB / asset
        if source.is_file():
            shutil.copy2(source, output_dir / asset)
        elif asset in copied_assets:
            raise RuntimeError(f"Required UI asset is missing: web/{asset}")

    docs = ROOT / "docs" / "PLANLINE_ARCHITECTURE.md"
    if docs.is_file():
        shutil.copy2(docs, output_dir / "architecture.md")

    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Included {page_count} workspace page(s).")
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    args = parser.parse_args()
    result = build_preview(args.output)
    print(f"Built static Planline UI preview in {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

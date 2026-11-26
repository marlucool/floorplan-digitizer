"""Build a backend-free, dashboard-first static copy of the Planline UI."""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planline.architecture import render_architecture_page

WEB = ROOT / "web"

# The public site and every PR preview enter through index.html (the dashboard).
# The full drawing editor remains available as a separate workspace page.
PAGE_SOURCES = {
    "index.html": "dashboard.html",
    "drawing.html": "index.html",
    "ocr.html": "ocr.html",
    "settings.html": "settings.html",
}
ROUTES = {
    "/dashboard": "index.html",
    "/drawing": "drawing.html",
    "/ocr": "ocr.html",
    "/settings": "settings.html",
    "/architecture": "architecture.html",
}
SHARED_ASSETS = ("preview.js", "demo-floorplan.svg")


def _normalise_brand(html: str) -> str:
    """Make the wordmark and Dashboard nav item return to the site homepage."""
    html = re.sub(
        r'(<a\s+class="brand"[^>]*\bhref=")[^"]*(")',
        r'\1/dashboard\2',
        html,
        count=1,
    )
    return re.sub(
        r'(<a\s+class="repo-link(?: active)?"[^>]*\bhref=")[^"]*(">Dashboard</a>)',
        r'\1/dashboard\2',
        html,
        count=1,
    )


def rewrite_routes(html: str) -> str:
    """Rewrite application routes and root-relative assets for a static site."""
    html = _normalise_brand(html)
    # A bare root link means Drawing in page content; the wordmark was already
    # normalised to /dashboard above.
    html = html.replace('href="/"', 'href="/drawing"')
    for route, target in sorted(ROUTES.items(), key=lambda item: len(item[0]), reverse=True):
        html = html.replace(f'href="{route}"', f'href="{target}"')
    html = re.sub(
        r'(href|src)="/([^"]+)"',
        lambda match: f'{match.group(1)}="{match.group(2)}"',
        html,
    )
    return html


def prepare_page(source: Path, destination: Path) -> set[str]:
    """Rewrite one page and return its local stylesheet/script dependencies."""
    html = rewrite_routes(source.read_text(encoding="utf-8"))
    script = re.search(r'<script\s+src="([^"]+\.js)"\s+defer></script>', html)
    if not script:
        raise RuntimeError(f"Could not find the deferred application script in {source.name}.")

    preview_tag = '<script src="preview.js" defer></script>\n  '
    if 'src="preview.js"' not in html:
        html = html[:script.start()] + preview_tag + html[script.start():]
    destination.write_text(html, encoding="utf-8")

    dependencies: set[str] = set()
    for raw_path in re.findall(r'(?:href|src)="([^"]+)"', html):
        if raw_path.startswith(("http://", "https://", "data:", "#")):
            continue
        path = raw_path.split("?", 1)[0].split("#", 1)[0]
        if path.endswith((".css", ".js", ".svg", ".png", ".webp", ".woff", ".woff2")):
            dependencies.add(path.lstrip("/"))
    dependencies.update(SHARED_ASSETS)
    return dependencies


def build_preview(output_dir: Path) -> Path:
    """Build all workspaces into a root-dashboard site, including nested PR previews."""
    output_dir = Path(output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    copied_assets: set[str] = set()
    page_count = 0
    for output_name, source_name in PAGE_SOURCES.items():
        source = WEB / source_name
        if not source.is_file():
            if output_name in {"index.html", "drawing.html"}:
                raise RuntimeError(f"Required workspace page is missing: web/{source_name}")
            continue
        copied_assets.update(prepare_page(source, output_dir / output_name))
        page_count += 1

    expected_pages = {"index.html", "drawing.html"}
    missing_pages = [name for name in expected_pages if not (output_dir / name).is_file()]
    if missing_pages:
        raise RuntimeError(f"Preview is missing required page(s): {', '.join(sorted(missing_pages))}")

    for asset in sorted(copied_assets):
        source = WEB / asset
        target = output_dir / asset
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        elif asset in SHARED_ASSETS:
            raise RuntimeError(f"Required static preview asset is missing: web/{asset}")
        else:
            raise RuntimeError(f"Page references a missing UI asset: web/{asset}")

    docs = ROOT / "docs" / "PLANLINE_ARCHITECTURE.md"
    if not docs.is_file():
        raise RuntimeError("Required architecture notes are missing: docs/PLANLINE_ARCHITECTURE.md")

    source = docs.read_text(encoding="utf-8")
    (output_dir / "architecture-source.md").write_text(source, encoding="utf-8")

    # The human-readable viewer is the primary page. Keep the historical
    # /architecture.md URL working as a directory index as well; static hosts
    # redirect that path to architecture.md/ and serve this index.html.
    (output_dir / "architecture.html").write_text(
        render_architecture_page(
            source,
            asset_prefix="",
            home_href="index.html",
            drawing_href="drawing.html",
            ocr_href="ocr.html",
            settings_href="settings.html",
            architecture_href="architecture.html",
            source_href="architecture-source.md",
        ),
        encoding="utf-8",
    )

    legacy_viewer = output_dir / "architecture.md"
    legacy_viewer.mkdir()
    (legacy_viewer / "index.html").write_text(
        render_architecture_page(
            source,
            asset_prefix="../",
            home_href="../index.html",
            drawing_href="../drawing.html",
            ocr_href="../ocr.html",
            settings_href="../settings.html",
            architecture_href="../architecture.html",
            source_href="../architecture-source.md",
        ),
        encoding="utf-8",
    )

    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Included {page_count} workspace page(s); index.html is the dashboard.")
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

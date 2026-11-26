"""Build a static, backend-free copy of the current Planline drawing UI."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ASSETS = ("app.js", "styles.css", "preview.js", "demo-floorplan.svg")


def build_preview(output_dir: Path) -> Path:
    """Copy the live drawing UI and rewrite its routes for static hosting."""
    output_dir = Path(output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    html = (WEB / "index.html").read_text(encoding="utf-8")
    replacements = {
        'href="/styles.css"': 'href="styles.css"',
        'src="/app.js"': 'src="app.js"',
        'href="/"': 'href="./"',
        'href="/ocr"': 'href="#preview-disabled"',
        'href="/settings"': 'href="#preview-disabled"',
        'href="/architecture"': 'href="#preview-disabled"',
    }
    for old, new in replacements.items():
        html = html.replace(old, new)

    app_script = '<script src="app.js" defer></script>'
    preview_scripts = (
        '<script src="preview.js" defer></script>\n'
        '  <script src="app.js" defer></script>'
    )
    if app_script not in html:
        raise RuntimeError("Could not find the main application script tag.")
    html = html.replace(app_script, preview_scripts, 1)
    if 'href="styles.css"' not in html or 'src="preview.js"' not in html:
        raise RuntimeError("The static preview asset paths were not rewritten.")

    (output_dir / "index.html").write_text(html, encoding="utf-8")
    for asset in ASSETS:
        shutil.copy2(WEB / asset, output_dir / asset)

    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
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

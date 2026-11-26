from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

from scripts.build_ui_preview import build_preview


def test_static_preview_starts_at_dashboard_and_keeps_workspaces_available() -> None:
    api_requests: list[str] = []
    with TemporaryDirectory(prefix="planline-preview-") as temporary:
        site = build_preview(Path(temporary) / "site")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])

        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "http.server",
                str(port),
                "--bind",
                "127.0.0.1",
                "--directory",
                str(site),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            url = f"http://127.0.0.1:{port}/"
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError("Static preview server exited before becoming ready.")
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("Static preview server did not become ready.")

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    page.on(
                        "request",
                        lambda request: api_requests.append(request.url)
                        if "/api/" in request.url
                        else None,
                    )
                    page.add_init_script("localStorage.setItem('planline-theme', 'light');")
                    page.goto(url, wait_until="domcontentloaded")
                    expect(page.locator("h1").first).to_contain_text("Your floor-plan")
                    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
                    theme_toggle = page.locator("#themeToggle")
                    expect(theme_toggle).to_be_visible()
                    theme_toggle.click()
                    expect(page.locator("html")).to_have_attribute("data-theme", "light")
                    theme_toggle.click()
                    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
                    expect(page.locator("#healthTitle")).to_have_text("Static preview")
                    expect(page.locator("#healthDetails")).to_contain_text("Backend services are disabled")
                    expect(page.locator("#refreshHealth")).to_be_hidden()
                    expect(page.locator('.workspace-card.drawing-card[href="drawing.html"]')).to_be_visible()
                    expect(page.locator('.workspace-card.ocr-card[href="ocr.html"]')).to_be_visible()
                    expect(page.locator('.workspace-card.settings-card[href="settings.html"]')).to_be_visible()
                    expect(page.locator('.top-links a[href="drawing.html"]')).to_be_visible()

                    page.goto(url + "drawing.html", wait_until="domcontentloaded")
                    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
                    expect(page.locator("#resultStatus")).to_have_text("DETECTION COMPLETE", timeout=15000)
                    expect(page.locator("#apiStatus")).to_contain_text("Static UI preview")
                    expect(page.locator("#detectionList .detection-row")).to_have_count(11)
                    expect(page.locator("#ocrAssistStatus")).to_contain_text("OCR is disabled")
                    expect(page.locator("#fileInput")).to_be_disabled()
                    expect(page.locator("#saveProject")).to_be_disabled()
                    expect(page.locator("#exportReview")).to_be_disabled()
                    expect(page.locator("#checkChain")).to_be_disabled()
                    page.wait_for_function(
                        "() => { const image = document.querySelector('#previewImage'); return image && image.complete && image.naturalWidth === 1200; }",
                        timeout=10000,
                    )

                    page.goto(url + "ocr.html", wait_until="domcontentloaded")
                    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
                    expect(page.locator("h1").first).to_be_visible()
                    expect(page.locator("#apiStatus")).to_contain_text("Static OCR preview")
                    expect(page.locator("#annotationMessage")).to_contain_text("disabled in this static preview")

                    page.goto(url + "settings.html", wait_until="domcontentloaded")
                    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
                    expect(page.locator("h1").first).to_be_visible()
                    expect(page.locator("#updateTitle")).to_have_text("Updates disabled in static preview")
                    expect(page.locator("#currentVersion")).to_have_text("Unavailable in preview")

                    # The docs index contains several document formats and the archive.
                    page.goto(url + "documentation/", wait_until="domcontentloaded")
                    expect(page.locator("h1").first).to_have_text("Documentation.")
                    assert page.locator(".documentation-file").count() > 10
                    expect(page.locator('.documentation-file[href="PLANLINE_ARCHITECTURE.md.html"]')).to_be_visible()
                    expect(page.locator('.documentation-file[href="rysunek.png.html"]')).to_be_visible()

                    page.goto(url + "documentation/ARCHITECTURE.md.html", wait_until="domcontentloaded")
                    expect(page.locator(".documentation-article h1")).to_contain_text("Planline architecture")
                    expect(page.locator(".documentation-toc")).to_be_visible()
                    architecture_link = page.locator('.documentation-prose a[href="PLANLINE_ARCHITECTURE.md.html"]')
                    expect(architecture_link).to_be_visible()
                    architecture_link.click()
                    expect(page).to_have_url(url + "documentation/PLANLINE_ARCHITECTURE.md.html")

                    # Clicking a section link must leave its heading below the
                    # measured sticky header, including after the header wraps on mobile.
                    section_link = page.locator(".documentation-toc a").last
                    target_id = section_link.get_attribute("href").removeprefix("#")
                    section_link.click()
                    page.wait_for_function(
                        """(targetId) => {
                          const target = document.getElementById(targetId);
                          const header = document.querySelector(".topbar");
                          if (!target || !header) return false;
                          const headerBottom = header.getBoundingClientRect().bottom;
                          const targetTop = target.getBoundingClientRect().top;
                          return targetTop >= headerBottom + 6 && targetTop <= headerBottom + 90;
                        }""",
                        arg=target_id,
                        timeout=5000,
                    )

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(150)
                    section_link = page.locator(".documentation-toc a").first
                    target_id = section_link.get_attribute("href").removeprefix("#")
                    section_link.click()
                    page.wait_for_function(
                        """(targetId) => {
                          const target = document.getElementById(targetId);
                          const header = document.querySelector(".topbar");
                          if (!target || !header) return false;
                          return target.getBoundingClientRect().top >= header.getBoundingClientRect().bottom + 6;
                        }""",
                        arg=target_id,
                        timeout=5000,
                    )


                    assert not api_requests, f"The static preview attempted backend requests: {api_requests}"
                finally:
                    browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)

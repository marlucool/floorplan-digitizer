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


def test_static_preview_renders_real_workspace_without_backend_requests() -> None:
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
                    page.goto(url, wait_until="domcontentloaded")
                    expect(page.locator("#resultStatus")).to_have_text("DETECTION COMPLETE", timeout=15000)
                    expect(page.locator("#apiStatus")).to_have_text("Static UI preview · backend disabled")
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
                    for page_name in ("ocr.html", "settings.html", "dashboard.html"):
                        workspace = site / page_name
                        if not workspace.is_file():
                            continue
                        page.goto(url + page_name, wait_until="domcontentloaded")
                        expect(page.locator('aside[role="status"]')).to_contain_text("DESKTOP UI PREVIEW")
                        expect(page.locator("h1").first).to_be_visible()
                        theme_toggle = page.locator("#themeToggle")
                        expect(theme_toggle).to_be_visible()
                        theme_toggle.click()
                        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
                        theme_toggle.click()
                        expect(page.locator("html")).to_have_attribute("data-theme", "light")

                    if (site / "dashboard.html").is_file():
                        page.goto(url + "dashboard.html", wait_until="domcontentloaded")
                        expect(page.locator('.top-links a[href="ocr.html"]')).to_be_visible()
                        expect(page.locator('.workspace-card.ocr-card[href="ocr.html"]')).to_be_visible()
                        expect(page.locator('.top-links a[href="settings.html"]')).to_be_visible()
                        expect(page.locator('.workspace-card.settings-card[href="settings.html"]')).to_be_visible()

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

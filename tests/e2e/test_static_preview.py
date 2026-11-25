from __future__ import annotations

from playwright.sync_api import expect, sync_playwright


def test_static_preview_renders_real_workspace_without_backend_requests() -> None:
    api_requests: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on(
            "request",
            lambda request: api_requests.append(request.url)
            if "/api/" in request.url
            else None,
        )
        page.goto("http://127.0.0.1:8765/", wait_until="domcontentloaded")
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
        assert not api_requests, f"The static preview attempted backend requests: {api_requests}"
        browser.close()

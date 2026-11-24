from __future__ import annotations

import json
import struct
import threading
import zlib
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def make_png(width: int = 2, height: int = 2) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    pixels = b"".join(b"\x00" + b"\xff\xff\xff\xff" * width for _ in range(height))
    header = struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def test_drawing_zoom_and_manual_chain_checker() -> None:
    web_dir = Path(__file__).resolve().parents[2] / "web"
    handler = partial(QuietHandler, directory=str(web_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.route(
                "**/api/health",
                lambda route: route.fulfill(
                    json={
                        "status": "ok",
                        "detector_weights_present": True,
                        "detector_loaded": False,
                        "ocr_available": False,
                        "dimension_chain_validation_available": True,
                        "geometry_available": False,
                    }
                ),
            )
            submitted: dict[str, object] = {}

            def validate_chain(route) -> None:
                submitted.update(json.loads(route.request.post_data))
                route.fulfill(
                    json={
                        "status": "matches",
                        "segment_total": "7500",
                        "overall_value": "7500",
                        "difference": "0",
                        "tolerance": "0",
                        "unit": "mm",
                        "unresolved_indices": [],
                        "overall_unresolved": False,
                        "unverified_indices": [],
                        "overall_verified": True,
                    }
                )

            page.route("**/api/validate-dimension-chain", validate_chain)
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.set_input_files(
                "#fileInput",
                {
                    "name": "plan.png",
                    "mimeType": "image/png",
                    "buffer": make_png(),
                },
            )
            page.wait_for_function(
                "document.querySelector('#previewImage').naturalWidth === 2"
            )
            page.locator("#zoomIn").click()
            assert page.locator("#zoomLevel").inner_text() == "125%"

            page.locator("#chainChecker > summary").click()
            page.locator(".segment-value").nth(0).fill("3000")
            page.locator(".segment-verified").nth(0).check()
            page.locator("#addSegment").click()
            page.locator(".segment-value").nth(1).fill("4500")
            page.locator(".segment-verified").nth(1).check()
            page.locator("#overallValue").fill("7500")
            page.locator("#overallVerified").check()
            page.locator("#checkChain").click()
            page.wait_for_selector('#chainResult[data-status="matches"]')

            assert submitted["segment_values"] == ["3000", "4500"]
            assert submitted["segment_verified"] == [True, True]
            assert submitted["overall_value"] == "7500"
            assert "Chain matches" in page.locator("#chainResult").inner_text()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

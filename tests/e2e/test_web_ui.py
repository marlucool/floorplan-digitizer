from __future__ import annotations

import base64
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
            sample_png = make_png(400, 300)
            preview_data_url = "data:image/png;base64," + base64.b64encode(sample_png).decode("ascii")

            def analyse(route) -> None:
                request_body = route.request.post_data or ""
                assert "confidence_threshold" in request_body
                assert "0.4" in request_body
                route.fulfill(
                    json={
                        "confidence_threshold": 0.4,
                        "image": {"width": 400, "height": 300},
                        "counts": {"wall": 1, "dimension_line": 0, "dimension_value": 1},
                        "detections": [
                            {
                                "id": "det-001",
                                "class_name": "wall",
                                "bbox": {
                                    "x1": 10, "y1": 20, "x2": 110, "y2": 70,
                                    "width": 100, "height": 50,
                                },
                                "confidence": 0.95,
                            },
                            {
                                "id": "det-002",
                                "class_name": "dimension_value",
                                "bbox": {
                                    "x1": 120, "y1": 80, "x2": 180, "y2": 110,
                                    "width": 60, "height": 30,
                                },
                                "confidence": 0.77,
                            }
                        ],
                        "dimension_regions": [
                            {
                                "id": "det-002",
                                "class_name": "dimension_value",
                                "bbox": {
                                    "x1": 120, "y1": 80, "x2": 180, "y2": 110,
                                    "width": 60, "height": 30,
                                },
                                "confidence": 0.77,
                                "crop_bbox": {
                                    "x1": 111, "y1": 72, "x2": 189, "y2": 118,
                                    "width": 78, "height": 46,
                                },
                                "crop_data_url": preview_data_url,
                            }
                        ],
                        "preview_data_url": preview_data_url,
                        "notes": [],
                    }
                )

            page.route("**/api/analyze", analyse)
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
                    "buffer": sample_png,
                },
            )
            page.wait_for_function(
                "document.querySelector('#previewImage').naturalWidth === 400"
            )
            page.locator("#zoomIn").click()
            assert page.locator("#zoomLevel").inner_text() == "125%"
            page.locator("#confidenceThreshold").evaluate(
                "(element) => { element.value = '0.4'; element.dispatchEvent(new Event('input', { bubbles: true })); }"
            )
            assert page.locator("#confidenceValue").inner_text() == "0.40"
            page.locator("#analyzeButton").click()
            page.wait_for_function(
                "document.querySelector('#resultStatus').textContent === 'DETECTION COMPLETE'"
            )
            page.wait_for_function(
                "!document.querySelector('#overlay').classList.contains('hidden')"
            )
            alignment = page.evaluate(
                "() => { const image = document.querySelector('#previewImage').getBoundingClientRect(); const canvas = document.querySelector('#overlay').getBoundingClientRect(); return { left: Math.abs(image.left - canvas.left), top: Math.abs(image.top - canvas.top), width: Math.abs(image.width - canvas.width), height: Math.abs(image.height - canvas.height) }; }"
            )
            assert max(alignment.values()) < 2

            with page.expect_download() as download_info:
                page.locator("#exportReview").click()
            download = download_info.value
            assert download.suggested_filename == "plan-planline-review.json"
            exported = json.loads(Path(download.path()).read_text())
            assert exported["schema_version"] == "planline-detection-review/v1"
            schema = json.loads(
                (Path(__file__).resolve().parents[2] / "schemas" / "planline-detection-review-v1.schema.json").read_text()
            )
            from jsonschema import Draft202012Validator, FormatChecker
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(exported)
            assert exported["source"]["filename"] == "plan.png"
            assert exported["analysis"]["confidence_threshold"] == 0.4
            assert exported["detections"][0]["bbox"]["x1"] == 10
            assert exported["manual_dimension_text_review"][0]["detection_id"] == "det-002"
            assert exported["manual_dimension_text_review"][0]["raw_text"] == "4200"
            assert exported["manual_dimension_text_review"][0]["verified"] is True
            assert "preview_data_url" not in exported

            page.locator("#dimensionTextReview > summary").click()
            page.locator(".dimension-text-value").fill("4200")
            page.locator(".dimension-text-verified-input").check()

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

            page.locator("#fitView").click()
            assert page.locator("#zoomLevel").inner_text() == "100%"
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.locator("#zoomIn").is_visible()
            assert page.locator("#checkChain").is_visible()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

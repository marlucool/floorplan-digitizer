from __future__ import annotations

import struct
import shutil
import zlib
from pathlib import Path

from playwright.sync_api import sync_playwright


def make_png(width: int = 400, height: int = 180) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    pixels = b"".join(b"\x00" + b"\xff\xff\xff\xff" * width for _ in range(height))
    header = struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


def test_ocr_studio_manual_crop_and_typed_label() -> None:
    web_dir = Path(__file__).resolve().parents[2] / "web"
    samples: list[dict[str, object]] = []
    png = make_png()

    def dataset_payload() -> dict[str, object]:
        return {
            "dataset_id": "handwriting", "dataset_dir": "local",
            "summary": {"samples": len(samples), "sources": 1 if samples else 0, "writers": 0,
                        "by_text_style": {"handwritten": len(samples)}, "splits_present": False,
                        "independent_groups": len(samples), "verified_samples": len(samples),
                        "valid": True, "split_counts": {}, "split_group_counts": {}},
            "samples": samples,
        }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        def api_mock(route) -> None:
            request = route.request
            path = request.url.split("?", 1)[0]
            if path.endswith("/api/ocr/status"):
                route.fulfill(json={"status": "ok", "paddleocr_installed": True, "paddle_installed": True})
            elif path.endswith("/api/ocr/datasets") and request.method == "GET":
                route.fulfill(json={"datasets": [{"dataset_id": "handwriting", "summary": dataset_payload()["summary"]}]})
            elif path.endswith("/api/ocr/datasets/handwriting") and request.method == "GET":
                route.fulfill(json=dataset_payload())
            elif path.endswith("/api/ocr/datasets/handwriting/samples") and request.method == "POST":
                body = request.post_data_buffer or b""
                assert b"4,200 mm" in body
                assert b'name="source_id"' in body
                samples.append({"crop_id": "crop-001", "text": "4,200 mm", "text_style": "handwritten",
                                "source_id": "plan-01", "writer_id": "", "verified": True,
                                "split": None, "image_url": "/placeholder.png"})
                route.fulfill(status=201, json={"added": 1, "dataset": dataset_payload()})
            else:
                route.fulfill(status=404, json={"detail": f"Unexpected test route: {path}"})

        page.route("**/api/ocr/**", api_mock)
        page.set_content('<!doctype html><base href="http://planline.test/"><body>' +
                         (web_dir / "ocr.html").read_text(encoding="utf-8").split("<body>", 1)[1].split("</body>", 1)[0] +
                         '</body>')
        page.add_script_tag(content=(web_dir / "ocr-studio.js").read_text(encoding="utf-8"))
        page.wait_for_function("document.querySelector('#datasetSelect option[value=handwriting]') !== null")
        page.set_input_files("#cropFiles", {"name": "old-plan.png", "mimeType": "image/png", "buffer": png})
        page.wait_for_function("document.querySelector('#cropCanvas').width > 0")
        canvas_box = page.locator("#cropCanvas").bounding_box()
        assert canvas_box is not None
        page.mouse.move(canvas_box["x"] + 30, canvas_box["y"] + 35)
        page.mouse.down()
        page.mouse.move(canvas_box["x"] + 250, canvas_box["y"] + 100, steps=4)
        page.mouse.up()
        page.wait_for_function("document.querySelector('#cropSelectionInfo').textContent.includes('px crop')")
        page.locator("#sampleText").fill("4,200 mm")
        page.wait_for_function("!document.querySelector('#saveCropButton').disabled")
        page.locator("#saveCropButton").click()
        page.wait_for_selector(".sample-row")
        assert page.locator(".sample-row-info strong").inner_text() == "4,200 mm"
        assert "QUEUE COMPLETE" in page.locator("#queueStatus").inner_text()
        browser.close()

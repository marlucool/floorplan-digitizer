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
                assert "brightness" in request_body and "20" in request_body
                assert "contrast" in request_body and "1.25" in request_body
                route.fulfill(
                    json={
                        "confidence_threshold": 0.4,
                        "preprocessing": {"brightness": 20, "contrast": 1.25, "method": "linear_intensity_only"},
                        "image": {"width": 400, "height": 300},
                        "counts": {"wall": 2, "dimension_line": 1, "dimension_value": 1},
                        "detections": [
                            {"id": "det-001", "class_name": "wall", "bbox": {"x1": 100, "y1": 60, "x2": 110, "y2": 250, "width": 10, "height": 190}, "confidence": 0.95},
                            {"id": "det-002", "class_name": "dimension_line", "bbox": {"x1": 110, "y1": 50, "x2": 290, "y2": 54, "width": 180, "height": 4}, "confidence": 0.88},
                            {"id": "det-003", "class_name": "wall", "bbox": {"x1": 290, "y1": 60, "x2": 300, "y2": 250, "width": 10, "height": 190}, "confidence": 0.92},
                            {"id": "det-004", "class_name": "dimension_value", "bbox": {"x1": 170, "y1": 25, "x2": 230, "y2": 45, "width": 60, "height": 20}, "confidence": 0.77}
                        ],
                        "dimension_regions": [
                            {
                                "id": "det-004",
                                "class_name": "dimension_value",
                                "bbox": {"x1": 170, "y1": 25, "x2": 230, "y2": 45, "width": 60, "height": 20},
                                "confidence": 0.77,
                                "association": {
                                    "dimension_value_id": "det-004",
                                    "status": "candidate",
                                    "confirmed": False,
                                    "candidate_lines": [
                                        {
                                            "dimension_line_id": "det-002",
                                            "orientation": "horizontal",
                                            "score": 0.84,
                                            "assignment_score": 0.88,
                                            "wall_span_status": "candidate",
                                            "wall_spans": [
                                                {
                                                    "wall_ids": ["det-001", "det-003"],
                                                    "orientation": "horizontal",
                                                    "method": "between_vertical_walls",
                                                    "span_px": 180,
                                                    "score": 0.91,
                                                    "assignment_score": 0.90,
                                                    "globally_assigned": True,
                                                    "globally_assigned_to": "det-004",
                                                    "gap_center_px": 200,
                                                    "text_center_offset_px": 0,
                                                    "line_center_offset_px": 0,
                                                    "endpoint_residual_px": 0,
                                                    "perpendicular_offset_px": 0,
                                                    "intervening_wall_count": 0
                                                }
                                            ]
                                        }
                                    ]
                                },
                                "crop_bbox": {"x1": 161, "y1": 17, "x2": 239, "y2": 53, "width": 78, "height": 36},
                                "crop_data_url": preview_data_url
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
            page.locator("#brightnessControl").evaluate("(element) => { element.value = String(20); element.dispatchEvent(new Event('input', { bubbles: true })); }")
            page.locator("#contrastControl").evaluate("(element) => { element.value = String(1.25); element.dispatchEvent(new Event('input', { bubbles: true })); }")
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
            page.locator("#fitView").click()
            page.locator("#startCalibration").click()
            page.locator("#previewImage").click(position={"x": 50, "y": 100})
            page.locator("#previewImage").click(position={"x": 350, "y": 100})
            page.locator("#calibrationDistance").fill("3.5")
            page.locator("#calibrationUnit").select_option("m")
            page.locator("#applyCalibration").click()
            assert "0.085714" in page.locator("#calibrationResult").inner_text()
            assert page.locator("#calibrationState").inner_text() == "Applied"
            page.locator("#drawWallTool").click()
            page.locator("#previewImage").click(position={"x": 60, "y": 200})
            page.locator("#previewImage").click(position={"x": 300, "y": 200})
            assert page.locator("#geometryCount").inner_text() == "1 manual wall"
            page.locator("#selectWallTool").click()
            page.locator("#previewImage").click(position={"x": 180, "y": 200})
            assert page.locator("#deleteWall").is_enabled()
            page.locator("#deleteWall").click()
            assert page.locator("#geometryCount").inner_text() == "0 manual walls"
            page.locator("#drawWallTool").click()
            page.locator("#previewImage").click(position={"x": 60, "y": 220})
            page.locator("#previewImage").click(position={"x": 300, "y": 220})
            assert page.locator("#geometryCount").inner_text() == "1 manual wall"
            with page.expect_download() as svg_download_info:
                page.locator("#exportGeometry").click()
            svg_download = svg_download_info.value
            assert svg_download.suggested_filename == "plan-manual-geometry.svg"
            svg_text = Path(svg_download.path()).read_text()
            assert "<svg" in svg_text and 'id="manual-wall-002"' in svg_text
            page.locator("#drawRoomTool").click()
            page.locator("#previewImage").click(position={"x": 50, "y": 40})
            page.locator("#previewImage").click(position={"x": 150, "y": 40})
            page.locator("#previewImage").click(position={"x": 150, "y": 140})
            page.locator("#previewImage").click(position={"x": 50, "y": 140})
            assert page.locator("#finishRoom").is_enabled()
            page.locator("#finishRoom").click()
            assert page.locator("#roomCount").inner_text() == "1 room"
            assert "m²" in page.locator("#roomArea").inner_text()
            assert "not verified" in page.locator("#roomArea").inner_text()
            with page.expect_download() as room_svg_download_info:
                page.locator("#exportGeometry").click()
            room_svg_download = room_svg_download_info.value
            room_svg_text = Path(room_svg_download.path()).read_text()
            assert 'id="manual-room-001"' in room_svg_text
            page.locator("#detectionSearch").fill("dimension_value")
            assert page.locator(".detection-row:visible").count() == 1
            page.locator("#detectionSearch").fill("does-not-exist")
            assert page.locator("#noDetectionMatches").is_visible()
            page.locator("#detectionSearch").fill("")
            page.locator("#detectionSort").select_option("confidence")
            page.locator('.detection-row[data-detection-id="det-004"]').click()
            assert page.locator("#selectedDetection").is_visible()
            assert "det-004" in page.locator("#selectedDetection").inner_text().lower()
            page.locator("#themeToggle").click()
            assert page.locator("html").get_attribute("data-theme") == "dark"
            page.locator("#themeToggle").click()
            assert page.locator("html").get_attribute("data-theme") == "light"
            alignment = page.evaluate(
                "() => { const image = document.querySelector('#previewImage').getBoundingClientRect(); const canvas = document.querySelector('#overlay').getBoundingClientRect(); return { left: Math.abs(image.left - canvas.left), top: Math.abs(image.top - canvas.top), width: Math.abs(image.width - canvas.width), height: Math.abs(image.height - canvas.height) }; }"
            )
            assert max(alignment.values()) < 2

            assert page.locator("#dimensionTextReview").evaluate("(node) => node.open")
            page.locator(".dimension-text-value").fill("4200")
            page.locator(".dimension-text-style").select_option("handwritten")
            assert page.locator(".dimension-text-value").input_value() == "4200"
            assert page.locator(".dimension-text-item").get_attribute("data-detection-id") == "det-004"
            page.locator(".dimension-text-verified-input").check()
            page.locator(".dimension-line-select").select_option("det-002")
            page.locator(".dimension-wall-span-select").select_option("0")
            page.locator(".dimension-association-verified-input").check()

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
            assert page.locator(".dimension-text-value").input_value() == "4200"
            assert page.locator(".dimension-text-verified-input").is_checked()

            assert submitted["segment_values"] == ["3000", "4500"]
            assert submitted["segment_verified"] == [True, True]
            assert submitted["overall_value"] == "7500"
            assert "Chain matches" in page.locator("#chainResult").inner_text()

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
            assert exported["analysis"]["preprocessing"]["brightness"] == 20
            assert exported["analysis"]["preprocessing"]["contrast"] == 1.25
            assert exported["calibration"]["method"] == "user_two_point_reference"
            assert exported["calibration"]["input_unit"] == "m"
            assert exported["calibration"]["known_distance_mm"] == 3500
            assert exported["calibration"]["pixels_per_mm"] > 0
            assert exported["calibration"]["status"] == "user_supplied_reference_not_geometry_validation"
            assert exported["detections"][0]["bbox"]["x1"] == 100
            assert exported["manual_dimension_text_review"][0]["detection_id"] == "det-004"
            assert exported["manual_dimension_text_review"][0]["raw_text"] == "4200"
            assert exported["manual_dimension_text_review"][0]["text_style"] == "handwritten"
            assert exported["manual_dimension_text_review"][0]["verified"] is True
            assert exported["manual_dimension_text_review"][0]["association"]["dimension_line_id"] == "det-002"
            assert exported["manual_dimension_text_review"][0]["association"]["wall_ids"] == ["det-001", "det-003"]
            assert exported["manual_dimension_text_review"][0]["association"]["candidate_lines"][0]["wall_spans"][0]["globally_assigned"] is True
            assert exported["manual_dimension_text_review"][0]["association"]["confirmed"] is True
            assert "preview_data_url" not in exported

            with page.expect_download() as project_download_info:
                page.locator("#saveProject").click()
            project_download = project_download_info.value
            assert project_download.suggested_filename == "plan.planline"
            project_payload = json.loads(Path(project_download.path()).read_text())
            assert project_payload["format"] == "planline-project"
            assert project_payload["format_version"] == 1
            assert project_payload["source"]["filename"] == "plan.png"
            assert project_payload["analysis_result"]["image"] == {"width": 400, "height": 300}
            assert len(project_payload["geometry"]) == 1
            assert len(project_payload["rooms"]) == 1
            assert project_payload["rooms"][0]["id"] == "manual-room-001"
            assert project_payload["geometry"][0]["id"] == "manual-wall-002"
            project_schema = json.loads(
                (Path(__file__).resolve().parents[2] / "schemas" / "planline-project-v1.schema.json").read_text()
            )
            from jsonschema import Draft202012Validator
            Draft202012Validator(project_schema).validate(project_payload)

            page.locator("#projectInput").set_input_files({
                "name": "restored.planline",
                "mimeType": "application/vnd.planline.project+json",
                "buffer": json.dumps(project_payload).encode("utf-8"),
            })
            page.wait_for_function(
                "document.querySelector('#resultStatus').textContent === 'DETECTION COMPLETE'"
            )
            assert page.locator(".dimension-text-value").input_value() == "4200"
            assert page.locator(".dimension-text-style").input_value() == "handwritten"
            assert page.locator(".dimension-text-verified-input").is_checked()
            assert page.locator(".dimension-association-verified-input").is_checked()
            assert page.locator("#calibrationState").inner_text() == "Applied"
            assert page.locator("#fileName").inner_text() == "plan.png"
            assert page.locator("#brightnessControl").input_value() == "20"
            assert page.locator("#contrastControl").input_value() == "1.25"
            assert page.locator("#geometryCount").inner_text() == "1 manual wall"
            assert page.locator("#roomCount").inner_text() == "1 room"

            page.locator("#fitView").click()
            assert page.locator("#zoomLevel").inner_text() == "100%"
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.locator("#zoomIn").is_visible()
            assert page.locator("#checkChain").is_visible()
            assert page.locator(".dimension-text-value").input_value() == "4200"
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_pdf_page_selector_submits_selected_page() -> None:
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
                    json={"status": "ok", "detector_weights_present": True}
                ),
            )
            submitted: dict[str, str] = {}

            def analyse(route) -> None:
                submitted["body"] = route.request.post_data or ""
                preview = "data:image/png;base64," + base64.b64encode(make_png()).decode("ascii")
                route.fulfill(
                    json={
                        "source": {"source_type": "pdf", "page_index": 1, "page_count": 3},
                        "image": {"width": 2, "height": 2},
                        "counts": {},
                        "detections": [],
                        "dimension_regions": [],
                        "association_candidates": [],
                        "notes": [],
                        "preview_data_url": preview,
                        "confidence_threshold": 0.25,
                    }
                )

            page.route("**/api/analyze", analyse)
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.locator("#fileInput").set_input_files(
                {
                    "name": "multi-page-plan.pdf",
                    "mimeType": "application/pdf",
                    "buffer": b"%PDF-1.4 test placeholder",
                }
            )
            assert not page.locator("#pdfPageControl").evaluate(
                "(element) => element.classList.contains('hidden')"
            )
            page.locator("#pdfPageNumber").fill("2")
            page.locator("#analyzeButton").click()
            page.wait_for_function(
                "document.querySelector('#resultStatus').textContent === 'DETECTION COMPLETE'"
            )
            assert 'name="page_index"' in submitted["body"]
            assert "1" in submitted["body"]
            assert page.locator("#pdfPageCount").inner_text() == "Page 2 of 3"
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

# Planline web interface

The web interface is served by the local FastAPI application. It is not a
standalone file:// application.

## Start

From the repository root:

```bash
python -m pip install -r requirements-web.txt
python -m uvicorn planline.api:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 in a browser. The service binds to loopback by
default so it is not exposed to the LAN.

## Current behaviour

- Accepts PNG, JPG, WEBP, TIFF and PDF uploads up to 25 MB.
- Processes uploads in memory; source files are not written to disk.
- Rasterises and analyses only the first page of a PDF.
- Runs the repository's tracked `yolo_floorplan.pt` model.
- Displays candidate bounding boxes and detector confidence scores.
- Provides health status at `GET /api/health`.

## Deliberate limitations

The current model detects candidate regions only. It does **not** perform OCR,
read written dimensions, associate values with walls, infer a scale, reconstruct
geometry, or export a measured DXF. Detector confidence is not a probability
that a dimension was read correctly. All values must be checked against the
source drawing.

The model was trained on a small dataset of simplified floor plans. Expect
missed detections and false positives, especially on old, faded, skewed or
low-resolution scans. The UI must not be treated as a CAD deliverable.

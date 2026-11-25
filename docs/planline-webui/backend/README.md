# Planline local backend

Run from the project folder:

```powershell
python -m uvicorn backend.app:app --reload
```

Then open `http://127.0.0.1:8000`. Source drawings and project metadata remain in `runtime/projects/` on this computer.

## Implemented API

- `POST /api/projects` stores a supported scan locally and returns file metadata.
- `GET /api/projects/{id}` returns project state.
- `GET /api/projects/{id}/source` returns the local source file.
- `POST /api/projects/{id}/analyze` records that analysis is blocked until an OCR/geometry adapter is installed.
- `PATCH /api/projects/{id}/measurements/{id}` persists corrections once an analyser has supplied measurements.
- `GET /api/projects/{id}/export.dxf` refuses export until verified measurements and geometry exist.

The API intentionally does not fabricate detections, confidence scores, geometry, or DXF output for uploaded drawings. Add a local model adapter to the `analyze` endpoint to connect a detector, handwriting/printed OCR, dimension-to-wall matching, and geometry constraints.

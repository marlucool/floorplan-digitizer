# Planline local API

Run these commands from the repository root:

```bash
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The API serves the frontend from `web/` and stores project files under `runtime/projects/` on this computer. The runtime directory is ignored by Git.

## Implemented API

- `GET /api/health` reports whether the local service is running.
- `POST /api/projects` stores a supported source file locally and returns project metadata.
- `GET /api/projects/{id}` returns project state.
- `GET /api/projects/{id}/source` returns the stored source file.
- `POST /api/projects/{id}/analyze` runs deterministic source preflight (file hash, available image dimensions and basic quality findings). It then marks model stages as blocked because no analyser is configured.
- `PATCH /api/projects/{id}/measurements/{id}` persists a correction when an analyser has created that measurement.
- `GET /api/projects/{id}/export.dxf` exports only explicit wall segments from geometry marked verified and passing validation. It does not create geometry from measurement values.

## Deliberate boundary

The API does **not** run OCR, wall detection, dimension association or reconstruction yet. It does not fabricate confidence scores, candidate dimensions or geometry. The browser's sample DXF is a separate illustrative example; it is not the output for an uploaded scan.

The next integration point is a local analysis adapter that returns dimension candidates with source regions and provenance, followed by constraint checks and verified 2D geometry. See [the architecture plan](../docs/ARCHITECTURE.md).

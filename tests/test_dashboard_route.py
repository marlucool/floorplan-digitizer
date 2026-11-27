from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planline.api import app
from planline.documentation import safe_document_path


def test_application_root_and_dashboard_route_open_dashboard() -> None:
    client = TestClient(app)
    for path in ("/", "/dashboard"):
        response = client.get(path)
        assert response.status_code == 200
        assert "Planline — Dashboard" in response.text
        assert 'href="/drawing"' in response.text
        assert 'href="/ocr"' in response.text
        assert 'href="/settings"' in response.text


def test_drawing_has_its_own_route() -> None:
    response = TestClient(app).get("/drawing")
    assert response.status_code == 200
    assert "Turn a scanned plan" in response.text
    assert 'href="/" aria-label="Planline dashboard"' in response.text


def test_all_workspaces_use_shared_theme_control_and_navigation() -> None:
    client = TestClient(app)
    for path in ("/", "/dashboard", "/drawing", "/ocr", "/settings", "/architecture", "/documentation"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'id="themeToggle"' in response.text
        assert 'src="/theme.js" defer' in response.text
        assert 'href="/" aria-label="Planline dashboard"' in response.text
        assert 'href="/styles.css"' in response.text
        assert "dashboard.css" not in response.text
        assert "settings.css" not in response.text
        assert "ocr-studio.css" not in response.text


def test_architecture_route_renders_html_instead_of_raw_markdown() -> None:
    response = TestClient(app).get("/architecture")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Planline — Architecture &amp; roadmap</title>" in response.text
    assert '<article class="architecture-prose">' in response.text
    assert '<nav class="architecture-toc"' in response.text
    assert "Implemented application state" in response.text



def test_documentation_hub_lists_multiple_formats_and_files() -> None:
    client = TestClient(app)
    response = client.get("/documentation")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Documentation — Planline</title>" in response.text
    assert "PLANLINE_ARCHITECTURE.md" in response.text
    assert "OCR_DATASET_QUALITY.md" in response.text
    assert "ARCHITECTURE.md" in response.text
    assert "Images and examples" in response.text
    assert "Archived references" in response.text


def test_documentation_renders_markdown_source_and_image_files() -> None:
    client = TestClient(app)
    architecture = client.get("/documentation/ARCHITECTURE.md")
    assert architecture.status_code == 200
    assert architecture.headers["content-type"].startswith("text/html")
    assert '<article class="documentation-article">' in architecture.text
    assert 'href="/documentation/PLANLINE_ARCHITECTURE.md"' in architecture.text

    image_page = client.get("/documentation/rysunek.png")
    assert image_page.status_code == 200
    assert '<img src="/docs/rysunek.png"' in image_page.text

    image = client.get("/docs/rysunek.png")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.content[:8] == b"\x89PNG\r
\x1a
"


def test_documentation_renders_archived_source_as_readable_code() -> None:
    response = TestClient(app).get("/documentation/archive/planline-webui-prototype/backend/app.py")
    assert response.status_code == 200
    assert '<pre class="documentation-code"><code>' in response.text
    assert "from fastapi" in response.text


def test_documentation_path_resolver_rejects_paths_outside_docs_directory() -> None:
    docs_root = Path(__file__).resolve().parents[1] / "docs"
    with pytest.raises(FileNotFoundError):
        safe_document_path(docs_root, "../README.md")
    with pytest.raises(FileNotFoundError):
        safe_document_path(docs_root, "..\\README.md")


def test_documentation_and_architecture_share_primary_navigation() -> None:
    client = TestClient(app)
    for path in ("/documentation", "/documentation/ARCHITECTURE.md", "/architecture"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'href="/drawing">Drawing workspace</a>' in response.text
        assert 'href="/architecture">Architecture</a>' in response.text

import pytest
from fastapi.testclient import TestClient

from planline.api import app
from planline.documentation import discover_documents


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


def test_local_documentation_hub_and_markdown_routes_work() -> None:
    client = TestClient(app)
    index = client.get("/documentation")
    assert index.status_code == 200
    assert index.headers["content-type"].startswith("text/html")
    assert "Documentation" in index.text
    assert "PLANLINE_ARCHITECTURE.md" in index.text
    assert 'href="/architecture"' in index.text

    article = client.get("/documentation/PLANLINE_ARCHITECTURE.md")
    assert article.status_code == 200
    assert article.headers["content-type"].startswith("text/html")
    assert '<article class="documentation-article">' in article.text


def test_local_documentation_serves_images_and_rejects_traversal() -> None:
    client = TestClient(app)
    image = client.get("/docs/rysunek.png")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.content.startswith(bytes((137, 80, 78, 71, 13, 10, 26, 10)))

    assert client.get("/documentation/%252e%252e/README.md").status_code in {404, 422}
    assert client.get("/docs/%252e%252e/README.md").status_code in {404, 422}


def test_architecture_and_documentation_have_mobile_navigation_controls() -> None:
    client = TestClient(app)
    architecture = client.get("/architecture")
    documentation = client.get("/documentation")
    for response in (architecture, documentation):
        assert response.status_code == 200
        assert 'class="nav-menu-toggle"' in response.text
        assert 'id="primaryNavigation"' in response.text
        assert 'href="#mainContent"' in response.text
        assert 'href="/architecture"' in response.text
        assert 'href="/documentation"' in response.text


def test_document_catalog_does_not_follow_symlinks_outside_docs(tmp_path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    private_file = tmp_path / "private.md"
    private_file.write_text("# Private title", encoding="utf-8")
    try:
        (docs_root / "external.md").symlink_to(private_file)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not available in this environment")

    assert discover_documents(docs_root) == []

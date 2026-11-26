from fastapi.testclient import TestClient

from planline.api import app


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
    for path in ("/", "/dashboard", "/drawing", "/ocr", "/settings", "/architecture"):
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

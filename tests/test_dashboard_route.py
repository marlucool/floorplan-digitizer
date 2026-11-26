from fastapi.testclient import TestClient

from planline.api import app


def test_dashboard_route_serves_workspace_dashboard() -> None:
    response = TestClient(app).get("/dashboard")
    assert response.status_code == 200
    assert "Planline — Dashboard" in response.text
    assert 'href="/ocr"' in response.text
    assert 'href="/settings"' in response.text


def test_all_workspaces_use_icon_theme_controls_and_navigation() -> None:
    client = TestClient(app)
    for path in ("/dashboard", "/", "/ocr", "/settings"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'id="themeToggle"' in response.text
        assert "<svg" in response.text
        assert "Dark mode" not in response.text
        assert 'href="/dashboard"' in response.text

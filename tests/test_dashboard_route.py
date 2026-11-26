from fastapi.testclient import TestClient

from planline.api import app


def test_dashboard_route_serves_workspace_dashboard() -> None:
    response = TestClient(app).get("/dashboard")
    assert response.status_code == 200
    assert "Planline — Dashboard" in response.text
    assert 'href="/ocr"' in response.text
    assert 'href="/settings"' in response.text

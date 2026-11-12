"""GET /api/health and the internal database check behind X-Internal-Key."""

from conftest import INTERNAL_KEY, build_app
from fastapi.testclient import TestClient

from app.db.session import get_session

KEY = {"X-Internal-Key": INTERNAL_KEY}


class FakeSession:
    """Stands in for the database session; `fails` makes every query raise."""

    def __init__(self, fails: bool = False):
        self.fails = fails

    async def execute(self, statement):
        if self.fails:
            raise ConnectionRefusedError("database is down")


def test_health_returns_200(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "broken"}


def test_internal_route_without_key_is_404(client):
    assert client.get("/_internal/health/db").status_code == 404
    wrong = client.get("/_internal/health/db", headers={"X-Internal-Key": "guess"})
    assert wrong.status_code == 404
    assert wrong.json() == {"error": {"code": "404", "detail": "Not Found"}}


def test_internal_routes_closed_when_no_key_is_configured():
    with TestClient(build_app(internal_api_key="")) as client:
        response = client.get("/_internal/health/db", headers={"X-Internal-Key": ""})
    assert response.status_code == 404


def test_internal_database_check_with_key(client):
    client.app.dependency_overrides[get_session] = lambda: FakeSession()
    response = client.get("/_internal/health/db", headers=KEY)
    assert response.status_code == 200
    assert response.json() == {"database": "ok"}


def test_internal_database_check_reports_a_down_database(client):
    client.app.dependency_overrides[get_session] = lambda: FakeSession(fails=True)
    response = client.get("/_internal/health/db", headers=KEY)
    assert response.status_code == 503
    assert response.json() == {"database": "unreachable"}

"""Where routes live: /api for the public API, /_internal hidden, docs only in dev."""

from conftest import build_app
from fastapi.testclient import TestClient


def test_openapi_is_served_at_api_openapi_json(client):
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]


def test_every_public_route_is_under_api(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    assert paths
    assert all(path.startswith("/api/") for path in paths)


def test_routes_left_out_of_the_spec_are_under_api_too():
    # FastAPI adds the spec and Swagger's pages by itself, outside our /api router, and leaves
    # them out of the spec; setup_metrics also mounts Prometheus /metrics at root (blocked by
    # nginx). They are the routes in app.routes that have a path of their own; our routers
    # (/api, /_internal) are listed there as one entry each, without one.
    app = build_app(env="dev")  # dev adds the Swagger pages
    paths = sorted(route.path for route in app.routes if hasattr(route, "path"))
    assert paths == ["/api/docs", "/api/docs/oauth2-redirect", "/api/openapi.json", "/metrics"]


def test_nothing_answers_at_the_default_root_paths():
    with TestClient(build_app(env="dev")) as client:
        for path in ("/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404, path


def test_internal_routes_are_not_in_the_openapi_spec(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    assert not any(path.startswith("/_internal") for path in paths)


def test_swagger_docs_only_in_dev():
    with TestClient(build_app(env="dev")) as client:
        assert client.get("/api/docs").status_code == 200
        assert client.get("/api/docs/oauth2-redirect").status_code == 200
    with TestClient(build_app(env="prod")) as client:
        assert client.get("/api/docs").status_code == 404
        assert client.get("/api/docs/oauth2-redirect").status_code == 404

import pytest
from fastapi.testclient import TestClient

from mg_api.app import create_app

from .conftest import make_settings

TOKEN = "s3cret-token"
BEARER = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path):
    settings = make_settings(tmp_path, api_token=TOKEN, scheduler_enabled=False, login_attempts_per_minute=3)
    with TestClient(create_app(settings)) as c:
        yield c


def test_public_endpoints_need_no_auth(client):
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/meta").json()["auth_required"] is True


def test_protected_endpoints_require_auth(client):
    response = client.get("/api/v1/runs")
    assert response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"


def test_bearer_token_grants_access(client):
    assert client.get("/api/v1/runs", headers=BEARER).status_code == 200


def test_api_schema_needs_auth_and_interactive_docs_are_off(client):
    assert client.get("/api/v1/openapi.json").status_code == 401
    schema = client.get("/api/v1/openapi.json", headers=BEARER)
    assert schema.status_code == 200 and "/api/v1/runs" in schema.json()["paths"]
    assert client.get("/api/v1/docs", headers=BEARER).status_code == 404
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_upload_without_credentials_is_refused_before_parsing(client):
    response = client.post(
        "/api/v1/runs", content=b"not multipart", headers={"content-type": "multipart/form-data; boundary=x"}
    )
    assert response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"


def test_session_cookie_login_and_logout(client):
    assert client.post("/api/v1/session", json={"token": "wrong"}).status_code == 401
    login = client.post("/api/v1/session", json={"token": TOKEN})
    assert login.status_code == 204
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert client.get("/api/v1/session").json()["authenticated"] is True
    assert client.get("/api/v1/runs").status_code == 200
    client.delete("/api/v1/session")
    client.cookies.clear()
    assert client.get("/api/v1/runs").status_code == 401


def test_tampered_cookie_is_rejected(client):
    client.cookies.set("mg_session", "v1.9999999999.deadbeef", path="/api")
    assert client.get("/api/v1/runs").status_code == 401


def test_login_attempts_are_rate_limited(client):
    codes = [client.post("/api/v1/session", json={"token": "wrong"}).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]

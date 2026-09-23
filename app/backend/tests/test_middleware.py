import asyncio
import json

from fastapi.testclient import TestClient

from mg_api.app import create_app
from mg_api.middleware import UploadGuardMiddleware

from .conftest import make_settings

LIMIT = 10


class _RecordingApp:
    def __init__(self):
        self.bytes_read = 0

    async def __call__(self, scope, receive, send):
        while True:
            message = await receive()
            self.bytes_read += len(message.get("body", b""))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 202, "headers": []})
        await send({"type": "http.response.body", "body": b"accepted"})


def _post(chunks: list[bytes], authorized: bool = True, headers: tuple = ()):
    inner = _RecordingApp()
    guard = UploadGuardMiddleware(inner, "/upload", LIMIT, authorize=lambda request: authorized)
    scope = {"type": "http", "method": "POST", "path": "/upload", "headers": list(headers), "query_string": b""}
    pending = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)]
    sent = []

    async def receive():
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(guard(scope, receive, send))
    statuses = [m["status"] for m in sent if m["type"] == "http.response.start"]
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return statuses, body, inner


def test_upload_within_the_budget_reaches_the_app():
    statuses, body, inner = _post([b"12345", b"67890"])
    assert statuses == [202] and body == b"accepted" and inner.bytes_read == LIMIT


def test_chunked_upload_over_the_budget_gets_only_a_413():
    statuses, body, inner = _post([b"123456", b"789012", b"345"])
    assert statuses == [413] and json.loads(body)["error"]["code"] == "payload_too_large"
    assert inner.bytes_read < 2 * LIMIT


def test_declared_oversize_is_rejected_without_reading():
    statuses, _, inner = _post([b"1"], headers=((b"content-length", b"999"),))
    assert statuses == [413] and inner.bytes_read == 0


def test_unauthenticated_upload_is_rejected_without_reading():
    statuses, body, inner = _post([b"1"], authorized=False)
    assert statuses == [401] and json.loads(body)["error"]["code"] == "unauthorized" and inner.bytes_read == 0


def test_unhandled_errors_keep_the_request_id(tmp_path):
    app = create_app(make_settings(tmp_path, scheduler_enabled=False))

    @app.get("/api/v1/explode")
    def explode():
        raise RuntimeError("boom")

    with TestClient(app) as client:
        response = client.get("/api/v1/explode", headers={"X-Request-ID": "trace-500"})
    assert response.status_code == 500 and response.headers["x-request-id"] == "trace-500"
    assert response.json()["error"]["request_id"] == "trace-500" and response.json()["error"]["retryable"] is True


def test_unsafe_request_ids_are_replaced(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, scheduler_enabled=False))) as client:
        response = client.get("/api/v1/health", headers={"X-Request-ID": "evil\r\nvalue"})
    assert response.headers["x-request-id"] not in ("evil\r\nvalue", "")

import logging
import re
import time
import uuid
from collections.abc import Callable

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .logging_setup import request_id_var

log = logging.getLogger(__name__)
access_log = logging.getLogger("mg_api.access")

_CLIENT_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def error_body(code: str, message: str, details=None, retryable: bool = False) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id_var.get(),
            "details": details,
            "retryable": retryable,
        }
    }


class RequestContextMiddleware:
    # Outermost application middleware: it owns the request id for the whole exchange, including 500s that
    # Starlette's error middleware would otherwise render after the context is gone.
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = Headers(scope=scope).get("x-request-id", "")
        request_id = supplied if _CLIENT_REQUEST_ID.match(supplied) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.monotonic()
        state = {"status": 500, "started": False}

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["status"], state["started"] = message["status"], True
                message = {**message, "headers": [*message.get("headers", []), (b"x-request-id", request_id.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            log.exception("unhandled error on %s %s", scope["method"], scope["path"])
            if state["started"]:
                raise
            body = error_body("internal_error", "Внутренняя ошибка сервера", retryable=True)
            await JSONResponse(body, status_code=500)(scope, receive, send_with_id)
        finally:
            access_log.info(
                "%s %s %s",
                scope["method"],
                scope["path"],
                state["status"],
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": state["status"],
                    "client": scope["client"][0] if scope.get("client") else None,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)


class _BodyTooLarge(Exception):
    pass


class UploadGuardMiddleware:
    # FastAPI parses multipart bodies before route dependencies run, so authentication and the byte budget for
    # uploads are enforced here, on the raw ASGI stream (chunked bodies included).
    def __init__(self, app: ASGIApp, path: str, limit_bytes: int, authorize: Callable[[Request], bool]):
        self.app = app
        self.path = path
        self.limit_bytes = limit_bytes
        self.authorize = authorize

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != self.path:
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if not self.authorize(request):
            await JSONResponse(error_body("unauthorized", "Требуется вход"), status_code=401)(scope, receive, send)
            return
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self.limit_bytes:
            await self._too_large(scope, receive, send)
            return
        received = 0
        exceeded = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit_bytes:
                    exceeded = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            if not exceeded:
                await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            exceeded = True
        if exceeded:
            await self._too_large(scope, receive, send)

    @staticmethod
    async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
        body = error_body("payload_too_large", "Загрузка превышает допустимый размер")
        await JSONResponse(body, status_code=413)(scope, receive, send)

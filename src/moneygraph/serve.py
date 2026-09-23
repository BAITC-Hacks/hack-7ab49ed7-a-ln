"""Локальный сервер: экран просмотра (out/viewer.html) + API AI-ассистента. Только стандартная библиотека."""

from __future__ import annotations

import json
import mimetypes
import sys
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

MAX_BODY = 64 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "moneygraph/0.1"

    def __init__(self, *args, out_dir: Path, **kwargs):
        self.out_dir = out_dir
        super().__init__(*args, **kwargs)

    def log_message(self, fmt, *args):  # тихий режим: пишем только ошибки
        pass

    def log_error(self, fmt, *args):
        sys.stderr.write("serve: " + (fmt % args) + "\n")

    # ------------------------------------------------------------ helpers
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _file(self, name: str) -> None:
        root = self.out_dir.resolve()
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            if name == "viewer.html":
                msg = "Нет out/viewer.html — сначала запустите `uv run moneygraph`."
                return self._send(503, msg.encode("utf-8"), "text/plain; charset=utf-8")
            return self._json(404, {"error": f"нет файла {name}"})
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json", "application/javascript"):
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)

    # ------------------------------------------------------------ routes
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html", "/viewer.html"):
            return self._file("viewer.html")
        if path == "/api/health":
            from moneygraph.assistant.llm import llm_status

            return self._json(200, {"ok": True, **llm_status()})
        if path.startswith("/api/"):
            return self._json(404, {"error": "нет такого метода"})
        return self._file(path.lstrip("/"))

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/ask":
            return self._json(404, {"error": "нет такого метода"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json(413, {"error": "слишком большой запрос"})
            payload = json.loads(self.rfile.read(length) or b"{}")
            question = str(payload.get("question") or "")
            focus = payload.get("focus_gid")
            focus = str(focus) if focus not in (None, "") else None
        except (ValueError, TypeError) as exc:
            return self._json(400, {"error": f"неверный JSON: {exc}"})
        from moneygraph.assistant.agent import ask

        try:
            result = ask(question, focus_gid=focus, out_dir=self.out_dir)
        except Exception as exc:  # ask сам ловит ошибки; это последняя страховка
            result = {"answer": f"Внутренняя ошибка: {type(exc).__name__}: {exc}", "gids": [], "trace": [],
                      "mode": "error"}
        self._json(200, result)


def serve(out_dir: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    from moneygraph.assistant.llm import llm_status

    out_dir = Path(out_dir)
    httpd = ThreadingHTTPServer((host, port), partial(Handler, out_dir=out_dir))
    shown = "127.0.0.1" if host in ("0.0.0.0", "") else host
    st = llm_status()
    print(f"Экран просмотра: http://{shown}:{port}/   (Ctrl+C — остановить)")
    print(f"Данные: {out_dir.resolve()}")
    print("AI-ассистент: " + (f"{st['provider']} ({st['model'] or 'модель выберется при первом вопросе'})"
                              if st["llm"] else "без LLM (нет OPENAI_API_KEY в .env) — детерминированный режим"))
    if not (out_dir / "viewer.html").exists():
        print("Внимание: нет out/viewer.html — сначала запустите `uv run moneygraph`.")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        httpd.server_close()

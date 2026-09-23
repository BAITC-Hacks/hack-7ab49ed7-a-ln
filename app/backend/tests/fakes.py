import threading
from types import SimpleNamespace

from mg_api.runs.worker import JobSpec, execute_run


class _ThreadHandle:
    def __init__(self, thread: threading.Thread):
        self._thread = thread

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def exit_code(self) -> int | None:
        return None if self._thread.is_alive() else 0

    def resident_bytes(self) -> int | None:
        return None

    def kill(self) -> None:
        self._thread.join(timeout=30)


class InlineLauncher:
    def start(self, job: JobSpec) -> _ThreadHandle:
        thread = threading.Thread(target=execute_run, args=(job,), daemon=True)
        thread.start()
        return _ThreadHandle(thread)


class _BlockedHandle:
    def __init__(self, exit_code: int | None):
        self._alive = exit_code is None
        self._exit_code = exit_code
        self.killed = False
        self.resident: int | None = None

    def is_alive(self) -> bool:
        return self._alive

    def exit_code(self) -> int | None:
        return self._exit_code

    def resident_bytes(self) -> int | None:
        return self.resident

    def kill(self) -> None:
        self.killed = True
        self._alive = False

    def exit(self, code: int = 0) -> None:
        self._alive = False
        self._exit_code = code


class BlockingLauncher:
    def __init__(self, crash_with: int | None = None):
        self.crash_with = crash_with
        self.started: list[JobSpec] = []
        self.handles: list[_BlockedHandle] = []

    def start(self, job: JobSpec) -> _BlockedHandle:
        self.started.append(job)
        self.handles.append(_BlockedHandle(self.crash_with))
        return self.handles[-1]


def text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def tool_block(tool_id: str, name: str, tool_input: dict):
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


class FakeLLM:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.requests: list[dict] = []

    def create(self, *, system: str, tools: list[dict], messages: list[dict]):
        self.requests.append({"system": system, "tools": tools, "messages": list(messages)})
        return self._responses.pop(0)


def response(stop_reason: str, *blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))

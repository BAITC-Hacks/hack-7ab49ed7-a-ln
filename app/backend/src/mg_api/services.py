from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from .analytics.store import RunCache, RunData
from .assistant.llm import LLMClient
from .errors import NotFound, RunNotReady, Unauthorized
from .runs.repository import RunRepository
from .runs.scheduler import Scheduler
from .security import SESSION_COOKIE, LoginRateLimiter, SessionSigner, token_matches
from .settings import Settings


@dataclass
class Services:
    settings: Settings
    runs: RunRepository
    cache: RunCache
    signer: SessionSigner
    login_limiter: LoginRateLimiter
    llm: LLMClient | None
    scheduler: Scheduler | None

    def run_dir(self, run_id: str) -> Path:
        return self.settings.runs_dir / run_id

    def require_run(self, run_id: str) -> dict:
        row = self.runs.get(run_id)
        if row is None:
            raise NotFound("Прогон не найден")
        return row

    def run_data(self, run_id: str) -> RunData:
        row = self.require_run(run_id)
        current = self.run_dir(run_id) / "current"
        if row["status"] != "succeeded" or not current.exists():
            raise RunNotReady("Прогон ещё не завершён")
        return self.cache.get(run_id, current)


def get_services(request: Request) -> Services:
    return request.app.state.services


def is_authenticated(request: Request) -> bool:
    services = get_services(request)
    if not services.settings.auth_required:
        return True
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer ") and token_matches(services.settings.api_token, header[7:].strip()):
        return True
    return services.signer.verify(request.cookies.get(SESSION_COOKIE))


def require_auth(request: Request) -> None:
    if not is_authenticated(request):
        raise Unauthorized("Требуется вход")


def node_id(data: RunData, gid: str) -> int:
    if not gid.isdigit() or int(gid) not in data.G:
        raise NotFound("Узел не найден в этом прогоне")
    return int(gid)

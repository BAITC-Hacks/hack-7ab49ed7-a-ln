import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque

from .errors import RateLimited

SESSION_COOKIE = "mg_session"
_VERSION = "v1"


class SessionSigner:
    def __init__(self, key: bytes, ttl_s: int):
        self._key = key
        self.ttl_s = ttl_s

    def _signature(self, issued: str) -> str:
        return hmac.new(self._key, f"{_VERSION}.{issued}".encode(), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        issued = str(int(time.time()))
        return f"{_VERSION}.{issued}.{self._signature(issued)}"

    def verify(self, value: str | None) -> bool:
        parts = (value or "").split(".")
        if len(parts) != 3 or parts[0] != _VERSION or not parts[1].isdigit():
            return False
        if time.time() - int(parts[1]) > self.ttl_s:
            return False
        return hmac.compare_digest(parts[2], self._signature(parts[1]))


def token_matches(expected: str, provided: str | None) -> bool:
    return provided is not None and hmac.compare_digest(expected.encode(), provided.encode())


_WINDOW_S = 60
_PRUNE_EVERY = 256


class LoginRateLimiter:
    def __init__(self, per_minute: int):
        self._per_minute = per_minute
        self._attempts: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._checks = 0

    def _prune(self, now: float) -> None:
        for client in [c for c, a in self._attempts.items() if not a or now - a[-1] > _WINDOW_S]:
            del self._attempts[client]

    def check(self, client: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._checks += 1
            if self._checks % _PRUNE_EVERY == 0:
                self._prune(now)
            attempts = self._attempts[client]
            while attempts and now - attempts[0] > _WINDOW_S:
                attempts.popleft()
            if len(attempts) >= self._per_minute:
                raise RateLimited("Слишком много попыток входа, попробуйте через минуту")
            attempts.append(now)

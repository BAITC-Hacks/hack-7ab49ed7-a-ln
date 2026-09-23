import json
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Append-only and additive: an older server version must keep working against a newer schema.
MIGRATIONS = (
    """
    CREATE TABLE runs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        source TEXT NOT NULL,
        status TEXT NOT NULL,
        stage_code TEXT, stage_label TEXT, progress REAL,
        error_code TEXT, error_message TEXT, error_retryable INTEGER,
        attempts INTEGER NOT NULL DEFAULT 0,
        owner TEXT, lease_until REAL,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        params TEXT NOT NULL DEFAULT '{}',
        warnings TEXT NOT NULL DEFAULT '[]',
        summary TEXT,
        engine_version TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL,
        started_at REAL, finished_at REAL, duration_s REAL
    );
    CREATE INDEX runs_status ON runs(status, created_at);
    """,
    """
    ALTER TABLE runs ADD COLUMN claim_id TEXT;
    ALTER TABLE runs ADD COLUMN error_details TEXT;
    """,
)


@dataclass(frozen=True)
class RunFailure:
    code: str
    message: str
    retryable: bool
    details: list[dict] | None = None


@dataclass(frozen=True)
class RunOutcome:
    summary: dict
    params: dict
    warnings: list[str]
    engine_version: str


CANCELLED = RunFailure("cancelled", "Прогон отменён пользователем", True)


class RunRepository(Protocol):
    def get(self, run_id: str) -> dict | None: ...
    def page(self, limit: int, offset: int) -> tuple[list[dict], int]: ...
    def count(self) -> int: ...
    def create(self, run_id: str, name: str, source: str, params: dict) -> dict: ...
    def cancel(self, run_id: str) -> str: ...
    def retry(self, run_id: str) -> str: ...
    def delete(self, run_id: str) -> str: ...
    def claim_next(self, owner: str, lease_s: float) -> dict | None: ...
    def heartbeat(self, claims: list[str], lease_s: float) -> None: ...
    def recover_expired(self, max_attempts: int) -> list[str]: ...
    def release_crashed(self, run_id: str, claim: str, max_attempts: int, message: str) -> None: ...
    def progress(self, run_id: str, claim: str, code: str, label: str, fraction: float) -> None: ...
    def publish_and_succeed(
        self, run_id: str, claim: str, outcome: RunOutcome, publish: Callable[[], None]
    ) -> bool: ...
    def finish_failed(self, run_id: str, claim: str, failure: RunFailure, status: str = "failed") -> bool: ...
    def ping(self) -> None: ...


class SqliteRunRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self):
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
        with self._transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            current = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
            for version, script in enumerate(MIGRATIONS[current:], start=current + 1):
                for statement in filter(str.strip, script.split(";")):
                    conn.execute(statement)
                conn.execute("INSERT INTO schema_version(version) VALUES (?)", (version,))

    def ping(self) -> None:
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()

    def get(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def page(self, limit: int, offset: int) -> tuple[list[dict], int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC, id LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        return [dict(r) for r in rows], total

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    def create(self, run_id: str, name: str, source: str, params: dict) -> dict:
        now = time.time()
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO runs(id, name, source, status, stage_code, stage_label, progress, params, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, name, source, "queued", "queued", "В очереди", 0.0, json.dumps(params), now, now),
            )
            return dict(conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def cancel(self, run_id: str) -> str:
        now = time.time()
        with self._transaction() as conn:
            row = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return "not_found"
            if row["status"] == "queued":
                self._mark_final(conn, run_id, CANCELLED, "cancelled", now)
                return "cancelled"
            if row["status"] == "running":
                conn.execute(
                    "UPDATE runs SET cancel_requested=1, stage_label='Отмена…', updated_at=? WHERE id=?", (now, run_id)
                )
                return "cancelling"
            return "final"

    def retry(self, run_id: str) -> str:
        now = time.time()
        with self._transaction() as conn:
            row = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return "not_found"
            if row["status"] not in ("failed", "cancelled"):
                return "conflict"
            conn.execute(
                "UPDATE runs SET status='queued', stage_code='queued', stage_label='В очереди', progress=0, "
                "error_code=NULL, error_message=NULL, error_retryable=NULL, error_details=NULL, attempts=0, "
                "owner=NULL, claim_id=NULL, lease_until=NULL, cancel_requested=0, started_at=NULL, "
                "finished_at=NULL, duration_s=NULL, updated_at=? WHERE id=?",
                (now, run_id),
            )
            return "queued"

    def delete(self, run_id: str) -> str:
        with self._transaction() as conn:
            row = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return "not_found"
            if row["status"] == "running":
                return "conflict"
            conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
            return "deleted"

    def claim_next(self, owner: str, lease_s: float) -> dict | None:
        now = time.time()
        claim = uuid.uuid4().hex
        with self._transaction() as conn:
            row = conn.execute("SELECT id FROM runs WHERE status='queued' ORDER BY created_at, id LIMIT 1").fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE runs SET status='running', owner=?, claim_id=?, lease_until=?, attempts=attempts+1, "
                "stage_code='validating', stage_label='Запуск', progress=0.01, "
                "started_at=COALESCE(started_at, ?), updated_at=? WHERE id=? AND status='queued'",
                (owner, claim, now + lease_s, now, now, row["id"]),
            )
            claimed = conn.execute("SELECT * FROM runs WHERE id=?", (row["id"],)).fetchone()
        return dict(claimed)

    def heartbeat(self, claims: list[str], lease_s: float) -> None:
        if not claims:
            return
        now = time.time()
        with self._transaction() as conn:
            conn.executemany(
                "UPDATE runs SET lease_until=? WHERE claim_id=? AND status='running'",
                [(now + lease_s, claim) for claim in claims],
            )

    def recover_expired(self, max_attempts: int) -> list[str]:
        now = time.time()
        with self._transaction() as conn:
            rows = conn.execute(
                "SELECT id, attempts, cancel_requested FROM runs WHERE status='running' AND lease_until < ?", (now,)
            ).fetchall()
            for r in rows:
                if r["cancel_requested"]:
                    self._mark_final(conn, r["id"], CANCELLED, "cancelled", now)
                else:
                    self._requeue_or_fail(
                        conn,
                        r["id"],
                        r["attempts"],
                        max_attempts,
                        now,
                        "Обработчик прогона остановился (истекла аренда)",
                    )
        return [r["id"] for r in rows]

    def release_crashed(self, run_id: str, claim: str, max_attempts: int, message: str) -> None:
        now = time.time()
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT attempts, cancel_requested FROM runs WHERE id=? AND claim_id=? AND status='running'",
                (run_id, claim),
            ).fetchone()
            if row is None:
                return
            if row["cancel_requested"]:
                self._mark_final(conn, run_id, CANCELLED, "cancelled", now)
            else:
                self._requeue_or_fail(conn, run_id, row["attempts"], max_attempts, now, message)

    def _requeue_or_fail(self, conn, run_id: str, attempts: int, max_attempts: int, now: float, message: str) -> None:
        if attempts < max_attempts:
            conn.execute(
                "UPDATE runs SET status='queued', stage_code='queued', stage_label='Повторная попытка', progress=0, "
                "owner=NULL, claim_id=NULL, lease_until=NULL, updated_at=? WHERE id=?",
                (now, run_id),
            )
        else:
            self._mark_final(conn, run_id, RunFailure("worker_crashed", message, True), "failed", now)

    @staticmethod
    def _mark_final(conn, run_id: str, failure: RunFailure, status: str, now: float) -> None:
        conn.execute(
            "UPDATE runs SET status=?, error_code=?, error_message=?, error_retryable=?, error_details=?, owner=NULL, "
            "claim_id=NULL, lease_until=NULL, finished_at=?, duration_s=? - COALESCE(started_at, ?), updated_at=?, "
            "stage_code=NULL, stage_label=NULL WHERE id=?",
            (
                status,
                failure.code,
                failure.message,
                int(failure.retryable),
                json.dumps(failure.details, ensure_ascii=False) if failure.details else None,
                now,
                now,
                now,
                now,
                run_id,
            ),
        )

    def progress(self, run_id: str, claim: str, code: str, label: str, fraction: float) -> None:
        with self._transaction() as conn:
            conn.execute(
                "UPDATE runs SET stage_code=?, stage_label=?, progress=?, updated_at=? "
                "WHERE id=? AND claim_id=? AND status='running' AND cancel_requested=0",
                (code, label, fraction, time.time(), run_id, claim),
            )

    def publish_and_succeed(self, run_id: str, claim: str, outcome: RunOutcome, publish: Callable[[], None]) -> bool:
        # The write lock is held while publishing, so recovery and cancellation (which also take it) can never
        # interleave: a worker whose claim was lost or cancelled never touches the published result. The claim
        # stays on the row to record which attempt the published result belongs to.
        now = time.time()
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM runs WHERE id=? AND claim_id=? AND status='running'", (run_id, claim)
            ).fetchone()
            if row is None:
                return False
            if row["cancel_requested"]:
                self._mark_final(conn, run_id, CANCELLED, "cancelled", now)
                return False
            publish()
            conn.execute(
                "UPDATE runs SET status='succeeded', stage_code='done', stage_label='Готово', progress=1, summary=?, "
                "params=?, warnings=?, engine_version=?, owner=NULL, lease_until=NULL, "
                "finished_at=?, duration_s=? - started_at, updated_at=? WHERE id=?",
                (
                    json.dumps(outcome.summary, ensure_ascii=False),
                    json.dumps(outcome.params),
                    json.dumps(outcome.warnings, ensure_ascii=False),
                    outcome.engine_version,
                    now,
                    now,
                    now,
                    run_id,
                ),
            )
            return True

    def finish_failed(self, run_id: str, claim: str, failure: RunFailure, status: str = "failed") -> bool:
        now = time.time()
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM runs WHERE id=? AND claim_id=? AND status='running'", (run_id, claim)
            ).fetchone()
            if row is None:
                return False
            if row["cancel_requested"]:
                failure, status = CANCELLED, "cancelled"
            self._mark_final(conn, run_id, failure, status, now)
            return True

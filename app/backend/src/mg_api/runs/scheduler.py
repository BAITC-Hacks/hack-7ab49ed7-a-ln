import json
import logging
import multiprocessing as mp
import os
import signal
import socket
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from moneygraph.pipeline import CollectionOverrides, InputLimits

from ..settings import Settings
from .bootstrap import run_isolated
from .repository import CANCELLED, RunFailure, RunRepository
from .worker import JobSpec

log = logging.getLogger(__name__)

TICK_S = 0.5
_TRANSIENT_SQLITE_ERRORS = ("SQLITE_BUSY", "SQLITE_LOCKED")


class WorkerHandle(Protocol):
    def is_alive(self) -> bool: ...
    def exit_code(self) -> int | None: ...
    def resident_bytes(self) -> int | None: ...
    def kill(self) -> None: ...


class WorkerLauncher(Protocol):
    def start(self, job: JobSpec) -> WorkerHandle: ...


class _ProcessHandle:
    def __init__(self, process: mp.process.BaseProcess):
        self._process = process

    def is_alive(self) -> bool:
        return self._process.is_alive()

    def exit_code(self) -> int | None:
        return self._process.exitcode

    def resident_bytes(self) -> int | None:
        # Linux /proc only; elsewhere, or once the process is gone, memory is unknown and not enforced.
        try:
            status = Path(f"/proc/{self._process.pid}/status").read_text()
        except OSError:
            return None
        return next((int(line.split()[1]) * 1024 for line in status.splitlines() if line.startswith("VmRSS:")), None)

    def kill(self) -> None:
        self._process.kill()
        self._process.join(timeout=10)


class ProcessLauncher:
    # spawn, not fork: the API process runs threads, and forking a threaded process can deadlock the child.
    def __init__(self):
        self._context = mp.get_context("spawn")

    def start(self, job: JobSpec) -> WorkerHandle:
        process = self._context.Process(
            target=run_isolated, args=(asdict(job),), name=f"mg-run-{job.run_id[:8]}", daemon=True
        )
        process.start()
        return _ProcessHandle(process)


@dataclass
class _Active:
    run_id: str
    handle: WorkerHandle
    started: float


def crash_message(exit_code: int | None) -> str:
    if exit_code == -signal.SIGKILL:
        return "Процесс расчёта остановлен системой — вероятно, не хватило памяти (MG_BACKEND_MEMORY)"
    return f"Процесс расчёта завершился аварийно (код {exit_code})"


def is_transient(error: sqlite3.OperationalError) -> bool:
    return getattr(error, "sqlite_errorname", "") in _TRANSIENT_SQLITE_ERRORS


def input_limits(settings: Settings) -> InputLimits:
    return InputLimits(
        settings.max_nodes,
        settings.max_transactions,
        settings.max_trace_cells,
        settings.max_decoded_mb * 1024 * 1024,
    )


def job_spec(run: dict, settings: Settings) -> JobSpec:
    params = {k: v for k, v in json.loads(run["params"]).items() if v is not None}
    overrides = CollectionOverrides(
        **{
            k: params[k]
            for k in ("max_depth", "observation_start", "observation_end", "min_transfer_kzt")
            if k in params
        }
    )
    return JobSpec(
        run_id=run["id"],
        claim=run["claim_id"],
        attempt=run["attempts"],
        db_path=str(settings.db_path),
        runs_dir=str(settings.runs_dir),
        overrides=overrides,
        limits=input_limits(settings),
        log_level=settings.log_level,
        log_json=settings.log_json,
    )


class Scheduler:
    def __init__(self, settings: Settings, runs: RunRepository, launcher: WorkerLauncher):
        self._settings = settings
        self._runs = runs
        self._launcher = launcher
        self.owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._active: dict[str, _Active] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.failure: BaseException | None = None

    @property
    def healthy(self) -> bool:
        return self.failure is None and (self._thread is None or self._thread.is_alive())

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="mg-scheduler", daemon=True)
        self._thread.start()
        log.info("scheduler %s started with %d workers", self.owner, self._settings.workers)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        for claim, active in list(self._active.items()):
            active.handle.kill()
            self._runs.release_crashed(
                active.run_id, claim, self._settings.max_attempts + 1, "Сервер остановлен во время расчёта"
            )
        self._active.clear()

    def _loop(self) -> None:
        last_heartbeat = 0.0
        while not self._stop.is_set():
            try:
                self.tick()
                if time.monotonic() - last_heartbeat > self._settings.lease_s / 3:
                    self._runs.heartbeat(list(self._active), self._settings.lease_s)
                    last_heartbeat = time.monotonic()
            except sqlite3.OperationalError as e:
                if not is_transient(e):
                    self._fail(e)
                    return
                log.warning("scheduler tick hit a busy database; retrying")
            except Exception as e:
                self._fail(e)
                return
            self._stop.wait(TICK_S)

    def _fail(self, error: BaseException) -> None:
        self.failure = error
        log.error("scheduler stopped; readiness now reports failure", exc_info=error)

    def tick(self) -> None:
        for run_id in self._runs.recover_expired(self._settings.max_attempts):
            log.warning("run %s: lease expired; requeued or finished", run_id)
        for claim, active in list(self._active.items()):
            self._supervise(claim, active)
        while len(self._active) < self._settings.workers:
            run = self._runs.claim_next(self.owner, self._settings.lease_s)
            if run is None:
                break
            handle = self._launcher.start(job_spec(run, self._settings))
            self._active[run["claim_id"]] = _Active(run["id"], handle, time.monotonic())
            log.info("run %s: attempt %d started", run["id"], run["attempts"])

    def _supervise(self, claim: str, active: _Active) -> None:
        # Liveness is sampled before the row is read: a worker that published and then exited is seen as succeeded.
        alive = active.handle.is_alive()
        row = self._runs.get(active.run_id)
        timed_out = time.monotonic() - active.started > self._settings.job_timeout_s
        if row is None or row["claim_id"] != claim:
            self._drop(claim, active, kill=alive)
        elif row["status"] == "succeeded":
            if not alive or timed_out:
                self._drop(claim, active, kill=alive)
        elif not alive:
            exit_code = active.handle.exit_code()
            self._drop(claim, active, kill=False)
            log.error("run %s: worker exited with code %s without a result", active.run_id, exit_code)
            self._runs.release_crashed(active.run_id, claim, self._settings.max_attempts, crash_message(exit_code))
        elif row["cancel_requested"]:
            self._drop(claim, active, kill=True)
            self._runs.finish_failed(active.run_id, claim, CANCELLED, status="cancelled")
        elif timed_out:
            self._drop(claim, active, kill=True)
            timeout = RunFailure("timeout", f"Расчёт превысил лимит {self._settings.job_timeout_s} с", True)
            self._runs.finish_failed(active.run_id, claim, timeout)
        elif self._over_memory_budget(active):
            self._drop(claim, active, kill=True)
            budget = self._settings.run_memory_mb
            failure = RunFailure("engine_error", f"Прогон превысил лимит памяти {budget} МБ (MG_RUN_MEMORY_MB)", False)
            self._runs.finish_failed(active.run_id, claim, failure)

    def _over_memory_budget(self, active: _Active) -> bool:
        resident = active.handle.resident_bytes()
        if resident is None or resident <= self._settings.run_memory_mb * 1024 * 1024:
            return False
        log.warning("run %s: %d MB resident exceeds the run budget; stopping it", active.run_id, resident >> 20)
        return True

    def _drop(self, claim: str, active: _Active, kill: bool) -> None:
        if kill:
            active.handle.kill()
        self._active.pop(claim, None)

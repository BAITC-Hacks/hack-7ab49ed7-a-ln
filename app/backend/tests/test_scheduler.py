import signal
import sqlite3
import threading
from dataclasses import asdict

from mg_api.runs.bootstrap import prefer_as_oom_victim
from mg_api.runs.repository import RunOutcome, SqliteRunRepository
from mg_api.runs.scheduler import Scheduler, crash_message
from mg_api.runs.worker import JobSpec

from .conftest import make_settings
from .fakes import BlockingLauncher

OUTCOME = RunOutcome(summary={}, params={}, warnings=[], engine_version="test")
MB = 1024 * 1024


def _expire_all_leases(repo: SqliteRunRepository) -> None:
    with sqlite3.connect(repo.path) as conn:
        conn.execute("UPDATE runs SET lease_until=0")


def test_worker_whose_claim_was_lost_is_killed(tmp_path):
    settings = make_settings(tmp_path, workers=2, max_attempts=3)
    repo = SqliteRunRepository(settings.db_path)
    repo.create("r1", "run", "demo", {})
    launcher = BlockingLauncher()
    scheduler = Scheduler(settings, repo, launcher)
    scheduler.tick()
    first_handle_claim = launcher.started[0].claim
    _expire_all_leases(repo)
    scheduler.tick()
    scheduler.tick()
    assert len(launcher.started) == 2 and launcher.started[1].claim != first_handle_claim
    assert launcher.handles[0].killed and not launcher.handles[1].killed


def _scheduler_with_one_run(tmp_path) -> tuple[Scheduler, SqliteRunRepository, BlockingLauncher]:
    settings = make_settings(tmp_path, workers=2, max_attempts=3)
    repo = SqliteRunRepository(settings.db_path)
    repo.create("r1", "run", "demo", {})
    launcher = BlockingLauncher()
    scheduler = Scheduler(settings, repo, launcher)
    scheduler.tick()
    return scheduler, repo, launcher


def test_stale_worker_is_killed_when_another_attempt_publishes(tmp_path):
    scheduler, repo, launcher = _scheduler_with_one_run(tmp_path)
    _expire_all_leases(repo)
    repo.recover_expired(max_attempts=3)
    other_claim = repo.claim_next("another-host", lease_s=60)["claim_id"]
    assert repo.publish_and_succeed("r1", other_claim, OUTCOME, lambda: None)
    scheduler.tick()
    assert launcher.handles[0].killed and len(launcher.started) == 1


def test_worker_that_published_is_supervised_until_it_exits(tmp_path):
    settings = make_settings(tmp_path, workers=1)
    repo = SqliteRunRepository(settings.db_path)
    repo.create("r1", "first", "demo", {})
    launcher = BlockingLauncher()
    scheduler = Scheduler(settings, repo, launcher)
    scheduler.tick()
    assert repo.publish_and_succeed("r1", launcher.started[0].claim, OUTCOME, lambda: None)
    repo.create("r2", "second", "demo", {})
    scheduler.tick()
    assert len(launcher.started) == 1 and not launcher.handles[0].killed
    launcher.handles[0].exit()
    scheduler.tick()
    assert [job.run_id for job in launcher.started] == ["r1", "r2"] and repo.get("r1")["status"] == "succeeded"


def test_only_the_run_over_its_memory_budget_is_stopped(tmp_path):
    settings = make_settings(tmp_path, workers=2, run_memory_mb=256)
    repo = SqliteRunRepository(settings.db_path)
    repo.create("r1", "within budget", "demo", {})
    repo.create("r2", "over budget", "demo", {})
    launcher = BlockingLauncher()
    scheduler = Scheduler(settings, repo, launcher)
    scheduler.tick()
    by_run = {job.run_id: handle for job, handle in zip(launcher.started, launcher.handles, strict=True)}
    by_run["r1"].resident, by_run["r2"].resident = 200 * MB, 300 * MB
    scheduler.tick()
    failed = repo.get("r2")
    assert failed["status"] == "failed" and "MG_RUN_MEMORY_MB" in failed["error_message"]
    assert by_run["r2"].killed and not by_run["r1"].killed and repo.get("r1")["status"] == "running"


def test_job_spec_survives_the_plain_data_hand_off(tmp_path):
    settings = make_settings(tmp_path)
    repo = SqliteRunRepository(settings.db_path)
    repo.create("r1", "run", "upload", {"max_depth": 4, "min_transfer_kzt": 5000.0})
    launcher = BlockingLauncher()
    Scheduler(settings, repo, launcher).tick()
    job = launcher.started[0]
    assert JobSpec.from_dict(asdict(job)) == job


def test_killed_worker_is_reported_as_probably_out_of_memory():
    assert "памяти" in crash_message(-signal.SIGKILL) and "код 1" in crash_message(1)


def test_run_processes_volunteer_for_the_oom_killer(tmp_path):
    score_file = tmp_path / "oom_score_adj"
    score_file.write_text("0")
    prefer_as_oom_victim(score_file)
    prefer_as_oom_victim(tmp_path / "absent")
    assert score_file.read_text() == "1000" and not (tmp_path / "absent").exists()


class _FailingRepository:
    def __init__(self, error: sqlite3.OperationalError):
        self._error = error
        self._calls = 0
        self.retried = threading.Event()

    def recover_expired(self, max_attempts: int):
        self._calls += 1
        if self._calls > 1:
            self.retried.set()
        raise self._error


def _error(message: str, name: str | None) -> sqlite3.OperationalError:
    error = sqlite3.OperationalError(message)
    if name:
        error.sqlite_errorname = name
    return error


def test_busy_database_is_retried(tmp_path):
    repo = _FailingRepository(_error("database is locked", "SQLITE_BUSY"))
    scheduler = Scheduler(make_settings(tmp_path), repo, BlockingLauncher())
    scheduler.start()
    assert repo.retried.wait(timeout=5) and scheduler.healthy
    scheduler.stop()


def test_other_database_errors_stop_the_scheduler(tmp_path):
    repo = _FailingRepository(_error("disk I/O error", "SQLITE_IOERR"))
    scheduler = Scheduler(make_settings(tmp_path), repo, BlockingLauncher())
    scheduler.start()
    scheduler.stop()
    assert not scheduler.healthy and not repo.retried.is_set()
    assert isinstance(scheduler.failure, sqlite3.OperationalError)

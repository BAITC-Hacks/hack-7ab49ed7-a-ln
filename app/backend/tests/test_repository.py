import sqlite3
import time

from mg_api.runs.repository import MIGRATIONS, RunFailure, RunOutcome, SqliteRunRepository

OUTCOME = RunOutcome(summary={}, params={}, warnings=[], engine_version="test")


def _repo(tmp_path) -> SqliteRunRepository:
    repo = SqliteRunRepository(tmp_path / "db.sqlite3")
    repo.create("r1", "run", "demo", {})
    return repo


def _expire_lease(repo: SqliteRunRepository, run_id: str) -> None:
    with sqlite3.connect(repo.path) as conn:
        conn.execute("UPDATE runs SET lease_until=0 WHERE id=?", (run_id,))


def test_migrations_are_idempotent(tmp_path):
    SqliteRunRepository(tmp_path / "db.sqlite3")
    repo = SqliteRunRepository(tmp_path / "db.sqlite3")
    with repo._connect() as conn:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()]
    assert versions == list(range(1, len(MIGRATIONS) + 1))


def test_a_queued_run_is_claimed_once_with_a_unique_claim(tmp_path):
    repo = _repo(tmp_path)
    first = repo.claim_next("owner-a", lease_s=60)
    assert first["id"] == "r1" and first["attempts"] == 1 and first["claim_id"]
    assert repo.claim_next("owner-b", lease_s=60) is None


def test_only_the_claim_holder_can_finish(tmp_path):
    repo = _repo(tmp_path)
    claim = repo.claim_next("owner", lease_s=60)["claim_id"]
    assert not repo.finish_failed("r1", "someone-else", RunFailure("engine_error", "x", True))
    assert repo.finish_failed("r1", claim, RunFailure("engine_error", "x", True))


def test_stale_claim_cannot_publish_over_a_newer_attempt(tmp_path):
    repo = _repo(tmp_path)
    stale = repo.claim_next("owner", lease_s=60)["claim_id"]
    _expire_lease(repo, "r1")
    repo.recover_expired(max_attempts=3)
    fresh = repo.claim_next("owner", lease_s=60)["claim_id"]
    published = []
    assert not repo.publish_and_succeed("r1", stale, OUTCOME, lambda: published.append("stale"))
    assert published == []
    assert repo.publish_and_succeed("r1", fresh, OUTCOME, lambda: published.append("fresh"))
    assert published == ["fresh"] and repo.get("r1")["status"] == "succeeded"


def test_cancellation_wins_over_a_finishing_worker(tmp_path):
    repo = _repo(tmp_path)
    claim = repo.claim_next("owner", lease_s=60)["claim_id"]
    assert repo.cancel("r1") == "cancelling"
    published = []
    assert not repo.publish_and_succeed("r1", claim, OUTCOME, lambda: published.append(True))
    row = repo.get("r1")
    assert published == [] and row["status"] == "cancelled" and row["error_code"] == "cancelled"
    assert row["stage_code"] is None and row["stage_label"] is None


def test_cancellation_wins_over_a_failing_worker(tmp_path):
    repo = _repo(tmp_path)
    claim = repo.claim_next("owner", lease_s=60)["claim_id"]
    repo.cancel("r1")
    assert repo.finish_failed("r1", claim, RunFailure("validation_error", "bad", False))
    row = repo.get("r1")
    assert row["status"] == "cancelled" and row["error_code"] == "cancelled"


def test_recovery_honours_a_pending_cancel(tmp_path):
    repo = _repo(tmp_path)
    repo.claim_next("owner", lease_s=60)
    repo.cancel("r1")
    _expire_lease(repo, "r1")
    repo.recover_expired(max_attempts=3)
    assert repo.get("r1")["status"] == "cancelled"


def test_expired_lease_requeues_until_attempts_run_out(tmp_path):
    repo = _repo(tmp_path)
    repo.claim_next("dead-owner", lease_s=60)
    _expire_lease(repo, "r1")
    assert repo.recover_expired(max_attempts=2) == ["r1"]
    assert repo.get("r1")["status"] == "queued" and repo.get("r1")["claim_id"] is None
    repo.claim_next("dead-owner", lease_s=60)
    _expire_lease(repo, "r1")
    repo.recover_expired(max_attempts=2)
    row = repo.get("r1")
    assert row["status"] == "failed" and row["error_code"] == "worker_crashed"


def test_validation_details_are_stored_with_the_failure(tmp_path):
    repo = _repo(tmp_path)
    claim = repo.claim_next("owner", lease_s=60)["claim_id"]
    details = [{"field": "transactions", "message": "не совпадают"}]
    repo.finish_failed("r1", claim, RunFailure("validation_error", "bad", False, details))
    assert repo.get("r1")["error_details"] == '[{"field": "transactions", "message": "не совпадают"}]'


def test_running_runs_cannot_be_deleted(tmp_path):
    repo = _repo(tmp_path)
    repo.claim_next("owner", lease_s=60)
    assert repo.delete("r1") == "conflict"


def test_page_is_newest_first(tmp_path):
    repo = SqliteRunRepository(tmp_path / "db.sqlite3")
    repo.create("old", "a", "demo", {})
    time.sleep(0.01)
    repo.create("new", "b", "demo", {})
    rows, total = repo.page(limit=1, offset=0)
    assert total == 2 and rows[0]["id"] == "new"

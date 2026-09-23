import pytest
from fastapi.testclient import TestClient

from mg_api.app import create_app

from .conftest import make_settings, wait_for_status
from .fakes import BlockingLauncher


@pytest.fixture
def blocked(tmp_path):
    launcher = BlockingLauncher()
    with TestClient(create_app(make_settings(tmp_path), launcher=launcher)) as client:
        yield client, launcher


def test_queued_run_is_not_ready_for_analytics(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, scheduler_enabled=False))) as client:
        run = client.post("/api/v1/runs/demo").json()
        error = client.get(f"/api/v1/runs/{run['id']}/overview").json()["error"]
        assert error["code"] == "run_not_ready" and error["retryable"] is True


def test_cancel_running_run_then_retry(blocked):
    client, launcher = blocked
    run = client.post("/api/v1/runs/demo").json()
    wait_for_status(client, run["id"], ("running",))
    assert client.delete(f"/api/v1/runs/{run['id']}").status_code == 409
    client.post(f"/api/v1/runs/{run['id']}/cancel")
    cancelled = wait_for_status(client, run["id"], ("cancelled",))
    assert cancelled["error"]["code"] == "cancelled"
    retried = client.post(f"/api/v1/runs/{run['id']}/retry").json()
    assert retried["status"] in ("queued", "running") and retried["error"] is None
    assert len(launcher.started) >= 1


def test_cancel_finished_run_conflicts(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, scheduler_enabled=False))) as client:
        run = client.post("/api/v1/runs/demo").json()
        client.post(f"/api/v1/runs/{run['id']}/cancel")
        assert client.post(f"/api/v1/runs/{run['id']}/cancel").status_code == 409
        assert client.delete(f"/api/v1/runs/{run['id']}").status_code == 204
        assert client.get(f"/api/v1/runs/{run['id']}").status_code == 404


def test_crashed_worker_is_retried_then_failed(tmp_path):
    launcher = BlockingLauncher(crash_with=137)
    with TestClient(create_app(make_settings(tmp_path, max_attempts=2), launcher=launcher)) as client:
        run = client.post("/api/v1/runs/demo").json()
        failed = wait_for_status(client, run["id"], ("failed",))
        assert failed["error"]["code"] == "worker_crashed" and failed["attempts"] == 2
        assert len(launcher.started) == 2


def test_timeout_fails_the_run(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, job_timeout_s=0), launcher=BlockingLauncher())) as client:
        run = client.post("/api/v1/runs/demo").json()
        assert wait_for_status(client, run["id"], ("failed",))["error"]["code"] == "timeout"

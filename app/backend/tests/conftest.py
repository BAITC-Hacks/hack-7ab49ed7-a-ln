import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mg_api.app import create_app
from mg_api.settings import Settings

from .fakes import InlineLauncher

SAMPLE_DATA = Path(__file__).resolve().parents[1] / "sample_data"


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "data_dir": tmp_path / "var",
        "seed_demo": False,
        "log_json": False,
        "workers": 1,
        "demo_data_dir": SAMPLE_DATA,
        **overrides,
    }
    return Settings(**values)


def wait_for_status(client: TestClient, run_id: str, statuses: tuple[str, ...], timeout_s: float = 120) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not reach {statuses}")


@pytest.fixture(scope="session")
def demo_client(tmp_path_factory):
    app = create_app(make_settings(tmp_path_factory.mktemp("demo")), launcher=InlineLauncher())
    with TestClient(app) as client:
        run = client.post("/api/v1/runs/demo").json()
        wait_for_status(client, run["id"], ("succeeded",))
        client.run_id = run["id"]
        yield client

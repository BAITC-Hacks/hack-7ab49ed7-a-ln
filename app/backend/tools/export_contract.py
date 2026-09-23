import argparse
import io
import json
import re
import tempfile
import time
import zipfile
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from mg_api.app import create_app
from mg_api.settings import Settings

RUN_ID = "11111111-1111-4111-8111-111111111111"
TIMESTAMP = "2026-09-23T10:00:00Z"
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_REQUEST_ID_RE = re.compile(r'"request_id": "[0-9a-f]+"')
_DURATION_RE = re.compile(r'"duration_s": [0-9.]+')


def _normalize(payload, run_id: str):
    text = json.dumps(payload, ensure_ascii=False).replace(run_id, RUN_ID)
    text = _REQUEST_ID_RE.sub('"request_id": "req-fixture"', _TIMESTAMP_RE.sub(TIMESTAMP, text))
    text = _DURATION_RE.sub('"duration_s": 7.0', text)
    return json.loads(text)


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _wait_for(client: TestClient, run_id: str, status: str, timeout_s: float = 300) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] == status:
            return run
        if run["status"] in ("succeeded", "failed", "cancelled"):
            raise RuntimeError(f"run {run_id} ended with status {run['status']}, expected {status}")
        time.sleep(0.5)
    raise TimeoutError(f"run {run_id} did not reach {status}")


def _inconsistent_upload(sample_dir: Path) -> bytes:
    edges = pd.read_parquet(sample_dir / "edges.parquet")
    edges.loc[0, "sum_kzt"] += 1_000
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        with archive.open("edges.parquet", "w") as member:
            edges.to_parquet(member, index=False)
        for name in ("nodes.parquet", "transactions.parquet"):
            archive.write(sample_dir / name, name)
    return buffer.getvalue()


def _captures(client: TestClient, run_id: str) -> dict[str, tuple[str, str, dict | None]]:
    top = client.get(f"/api/v1/runs/{run_id}/top", params={"limit": 3}).json()["items"]
    first, second = top[0]["id"], top[1]["id"]
    base = f"/api/v1/runs/{run_id}"
    return {
        "meta": ("GET", "/api/v1/meta", None),
        "methodology": ("GET", f"/api/v1/methodology?run_id={run_id}", None),
        "session": ("GET", "/api/v1/session", None),
        "runs_list": ("GET", "/api/v1/runs", None),
        "run_succeeded": ("GET", base, None),
        "overview": ("GET", f"{base}/overview", None),
        "graph": ("GET", f"{base}/graph?max_nodes=300&max_edges=900", None),
        "graph_hydrate": ("POST", f"{base}/graph/nodes", {"ids": [first, second], "include_edges": True}),
        "nodes_page": ("GET", f"{base}/nodes?limit=20", None),
        "search": ("GET", f"{base}/search?q={first[-7:]}", None),
        "node_detail": ("GET", f"{base}/nodes/{first}", None),
        "counterparties_in": ("GET", f"{base}/nodes/{first}/counterparties?direction=in", None),
        "counterparties_out": ("GET", f"{base}/nodes/{first}/counterparties?direction=out", None),
        "transactions": ("GET", f"{base}/nodes/{first}/transactions?limit=20", None),
        "neighborhood": ("GET", f"{base}/nodes/{first}/neighborhood?depth=1", None),
        "trace_up": ("GET", f"{base}/nodes/{first}/trace?direction=up&max_nodes=200", None),
        "trace_down": ("GET", f"{base}/nodes/{first}/trace?direction=down&max_nodes=200", None),
        "path": ("GET", f"{base}/path?source={second}&target={first}", None),
        "top": ("GET", f"{base}/top", None),
        "clusters": ("GET", f"{base}/clusters?limit=20", None),
        "cluster_detail": ("GET", f"{base}/clusters/1", None),
        "data_requests": ("GET", f"{base}/data-requests?limit=20", None),
        "exports": ("GET", f"{base}/exports", None),
        "assistant_collectors": (
            "POST",
            f"{base}/assistant",
            {"question": f"кто собирает деньги с {first}, {second}", "mode": "offline"},
        ),
        "assistant_explain": ("POST", f"{base}/assistant", {"question": f"почему {first[-9:]}", "mode": "offline"}),
        "assistant_ambiguous": ("POST", f"{base}/assistant", {"question": "почему 100000", "mode": "offline"}),
        "assistant_help": ("POST", f"{base}/assistant", {"question": "привет", "mode": "offline"}),
        "error_not_found": ("GET", f"{base}/nodes/123", None),
        "error_validation": ("GET", f"{base}/search?q=ab", None),
    }


def _failed_validation_fixture(client: TestClient, sample_dir: Path) -> tuple[dict, str]:
    upload = _inconsistent_upload(sample_dir)
    created = client.post("/api/v1/runs", files=[("files", ("data.zip", upload, "application/zip"))]).json()
    return _wait_for(client, created["id"], "failed"), created["id"]


def _lifecycle_fixtures(data_dir: Path) -> dict[str, tuple[dict, str]]:
    # No scheduler here, so each run stays in exactly the state the fixture needs; the claim stands in for a worker.
    app = create_app(Settings(data_dir=data_dir, log_json=False, seed_demo=False, scheduler_enabled=False))
    with TestClient(app) as client:
        queued = client.post("/api/v1/runs/demo").json()
        cancelled = client.post(f"/api/v1/runs/{queued['id']}/cancel").json()
        running = client.post("/api/v1/runs/demo").json()
        app.state.services.runs.claim_next("fixture-worker", lease_s=3600)
        cancelling = client.post(f"/api/v1/runs/{running['id']}/cancel").json()
        upload_error = client.post(
            "/api/v1/runs", files=[("files", ("broken.zip", b"not a zip", "application/zip"))]
        ).json()
    return {
        "run_queued": (queued, queued["id"]),
        "run_cancelled": (cancelled, queued["id"]),
        "run_cancelling": (cancelling, running["id"]),
        "error_upload": (upload_error, queued["id"]),
    }


def export(frontend_dir: Path) -> None:
    fixtures_dir = frontend_dir / "src" / "mocks" / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as data_dir:
        settings = Settings(data_dir=Path(data_dir) / "served", log_json=False, workers=1)
        app = create_app(settings)
        with TestClient(app) as client:
            run_id = client.get("/api/v1/runs").json()["items"][0]["id"]
            _wait_for(client, run_id, "succeeded")
            _write(frontend_dir / "src" / "api" / "openapi.json", app.openapi())
            for name, (method, path, body) in _captures(client, run_id).items():
                _write(
                    fixtures_dir / f"{name}.json", _normalize(client.request(method, path, json=body).json(), run_id)
                )
            failed, failed_id = _failed_validation_fixture(client, settings.demo_data_dir)
            _write(fixtures_dir / "run_failed_validation.json", _normalize(failed, failed_id))
        for name, (payload, own_id) in _lifecycle_fixtures(Path(data_dir) / "lifecycle").items():
            _write(fixtures_dir / f"{name}.json", _normalize(payload, own_id))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write openapi.json and real API fixtures for the frontend")
    parser.add_argument("--frontend", type=Path, default=Path(__file__).resolve().parents[2] / "frontend")
    export(parser.parse_args().frontend)

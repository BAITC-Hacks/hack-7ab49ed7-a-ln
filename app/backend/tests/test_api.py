import io
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from mg_api.app import create_app

from .conftest import make_settings, wait_for_status
from .datasets import CONSOLIDATOR, crafted_frames, write_dataset


@pytest.fixture(scope="module")
def run_path(demo_client):
    return f"/api/v1/runs/{demo_client.run_id}"


@pytest.fixture(scope="module")
def top_ids(demo_client, run_path):
    return [item["id"] for item in demo_client.get(f"{run_path}/top", params={"limit": 3}).json()["items"]]


def test_health_and_meta_are_public(demo_client):
    assert demo_client.get("/api/v1/health").json()["status"] == "ok"
    meta = demo_client.get("/api/v1/meta").json()
    assert meta["auth_required"] is False and meta["llm_enabled"] is False


def test_succeeded_run_carries_summary_and_params(demo_client, run_path):
    run = demo_client.get(run_path).json()
    assert run["status"] == "succeeded" and run["poll_after_ms"] is None
    assert run["summary"]["n_nodes"] == 2248
    assert run["params"]["max_depth"] == 4 and run["warnings"] == []


def test_gids_are_strings_everywhere(demo_client, run_path):
    graph = demo_client.get(f"{run_path}/graph", params={"max_nodes": 50}).json()
    assert all(isinstance(n["id"], str) and len(n["id"]) == 18 for n in graph["nodes"])
    assert all(isinstance(e["source"], str) for e in graph["edges"])


def test_graph_reports_truncation(demo_client, run_path):
    graph = demo_client.get(f"{run_path}/graph", params={"max_nodes": 10}).json()
    assert len(graph["nodes"]) == 10 and graph["total_nodes"] == 2248
    assert graph["truncated"] and graph["truncation_reason"] == "max_nodes"


def test_graph_nodes_are_ordered_by_priority(demo_client, run_path):
    nodes = demo_client.get(f"{run_path}/graph", params={"max_nodes": 30}).json()["nodes"]
    scores = [n["priority_score"] for n in nodes]
    assert scores == sorted(scores, reverse=True)


def test_hydration_returns_exactly_requested_nodes(demo_client, run_path, top_ids):
    sub = demo_client.post(f"{run_path}/graph/nodes", json={"ids": top_ids[:2], "include_edges": True}).json()
    assert sorted(n["id"] for n in sub["nodes"]) == sorted(top_ids[:2])


def test_node_table_filters_and_sorts(demo_client, run_path):
    page = demo_client.get(
        f"{run_path}/nodes", params={"role": "consolidator", "sort_by": "in_kzt", "sort_order": "asc", "limit": 5}
    ).json()
    assert page["total"] == 38
    assert all(r["role"] == "consolidator" for r in page["items"])
    values = [r["in_kzt"] for r in page["items"]]
    assert values == sorted(values)


def test_node_detail_explains_priority(demo_client, run_path, top_ids):
    detail = demo_client.get(f"{run_path}/nodes/{top_ids[0]}").json()
    assert detail["top_rank"] == 1 and detail["why"]
    total = sum(c["contribution"] for c in detail["priority_components"]) * detail["priority_reliability"]
    assert total == pytest.approx(detail["priority_score"], abs=1e-3)


def test_counterparties_and_transactions_paginate(demo_client, run_path, top_ids):
    page = demo_client.get(
        f"{run_path}/nodes/{top_ids[0]}/counterparties", params={"direction": "in", "limit": 2}
    ).json()
    assert len(page["items"]) == 2 and page["total"] > 2
    txs = demo_client.get(f"{run_path}/nodes/{top_ids[0]}/transactions", params={"limit": 3, "offset": 1}).json()
    assert len(txs["items"]) == 3 and txs["total"] > 4


def test_trace_up_contains_the_center_and_seeds(demo_client, run_path, top_ids):
    sub = demo_client.get(f"{run_path}/nodes/{top_ids[0]}/trace", params={"direction": "up"}).json()
    assert sub["center"] == top_ids[0] and sub["nodes"][0]["id"] == top_ids[0]
    assert any(n["is_seed"] for n in sub["nodes"])


def test_path_connects_source_to_target(demo_client, run_path, top_ids):
    result = demo_client.get(f"{run_path}/path", params={"source": top_ids[1], "target": top_ids[0]}).json()
    assert result["found"]
    assert result["nodes"][0] == top_ids[1] and result["nodes"][-1] == top_ids[0]
    assert len(result["edges"]) == len(result["nodes"]) - 1


def test_directed_path_edges_chain_in_order(demo_client, run_path, top_ids):
    result = demo_client.get(f"{run_path}/path", params={"source": top_ids[1], "target": top_ids[0]}).json()
    if result["directed"]:
        assert [e["source"] for e in result["edges"]] == result["nodes"][:-1]


def test_search_by_fragment(demo_client, run_path, top_ids):
    hits = demo_client.get(f"{run_path}/search", params={"q": top_ids[0][-7:]}).json()
    assert top_ids[0] in [h["id"] for h in hits["items"]]


def test_exports_download(demo_client, run_path):
    names = [e["name"] for e in demo_client.get(f"{run_path}/exports").json()["items"]]
    assert "bundle" in names and "nodes_roles" in names
    bundle = demo_client.get(f"{run_path}/exports/bundle")
    assert bundle.headers["content-type"] == "application/zip"
    assert "nodes_roles.csv" in zipfile.ZipFile(io.BytesIO(bundle.content)).namelist()


def test_error_envelope_has_request_id(demo_client, run_path):
    response = demo_client.get(f"{run_path}/nodes/123", headers={"X-Request-ID": "abc123"})
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Узел не найден в этом прогоне",
        "request_id": "abc123",
        "details": None,
        "retryable": False,
    }
    assert response.headers["x-request-id"] == "abc123"


def test_validation_details_are_localized(demo_client, run_path):
    error = demo_client.get(f"{run_path}/search", params={"q": "12"}).json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"] == [{"field": "query.q", "message": "не короче 3 символов"}]


def _zip_bytes(directory) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name in ("edges.parquet", "nodes.parquet", "transactions.parquet"):
            z.write(directory / name, f"data/{name}")
        z.writestr("../evil.parquet", b"ignored")
        z.writestr("__MACOSX/data/._edges.parquet", b"ignored")
    return buffer.getvalue()


def test_zip_upload_runs_to_completion(demo_client, tmp_path):
    archive = _zip_bytes(write_dataset(tmp_path / "in", *crafted_frames()))
    response = demo_client.post(
        "/api/v1/runs",
        files=[("files", ("data.zip", archive, "application/zip"))],
        data={
            "name": "crafted",
            "max_depth": "4",
            "observation_start": "2026-07-01",
            "observation_end": "2026-07-31",
            "min_transfer_kzt": "5000",
        },
    )
    assert response.status_code == 202, response.text
    run = wait_for_status(demo_client, response.json()["id"], ("succeeded", "failed"))
    assert run["status"] == "succeeded" and run["warnings"] == []
    node = demo_client.get(f"/api/v1/runs/{run['id']}/nodes/{CONSOLIDATOR}").json()
    assert node["role"] == "consolidator"


def test_three_parquet_upload_is_accepted(demo_client, tmp_path):
    directory = write_dataset(tmp_path / "in", *crafted_frames())
    files = [
        ("files", (f"{name} (1).parquet", (directory / f"{name}.parquet").read_bytes(), "application/octet-stream"))
        for name in ("edges", "nodes", "transactions")
    ]
    assert demo_client.post("/api/v1/runs", files=files).status_code == 202


@pytest.mark.parametrize(
    "files, code",
    [
        ([("files", ("x.zip", b"not a zip", "application/zip"))], "validation_error"),
        ([("files", ("a.parquet", b"1", "x")), ("files", ("b.parquet", b"2", "x"))], "validation_error"),
        (
            [
                ("files", ("edges.parquet", b"1", "x")),
                ("files", ("nodes.parquet", b"2", "x")),
                ("files", ("other.parquet", b"3", "x")),
            ],
            "validation_error",
        ),
    ],
)
def test_bad_uploads_are_rejected(demo_client, files, code):
    response = demo_client.post("/api/v1/runs", files=files)
    assert response.status_code == 400 and response.json()["error"]["code"] == code


def test_inconsistent_data_fails_the_run_with_field_details(demo_client, tmp_path):
    edges, nodes, tx = crafted_frames()
    archive = _zip_bytes(write_dataset(tmp_path / "in", edges.assign(sum_kzt=edges.sum_kzt + 50), nodes, tx))
    response = demo_client.post("/api/v1/runs", files=[("files", ("d.zip", archive, "application/zip"))])
    assert response.status_code == 202
    run = wait_for_status(demo_client, response.json()["id"], ("failed",))
    assert run["error"]["code"] == "validation_error" and run["error"]["retryable"] is False
    assert [d["field"] for d in run["error"]["details"]] == ["transactions"]


def test_wrongly_typed_columns_are_rejected_at_upload(demo_client, tmp_path):
    edges, nodes, tx = crafted_frames()
    archive = _zip_bytes(write_dataset(tmp_path / "in", edges, nodes, tx.assign(sum_kzt=tx.sum_kzt.astype(str))))
    error = demo_client.post("/api/v1/runs", files=[("files", ("d.zip", archive, "application/zip"))]).json()["error"]
    assert error["code"] == "validation_error"
    assert [d["field"] for d in error["details"]] == ["transactions.sum_kzt"]


@pytest.mark.parametrize(
    "form, status, field",
    [
        ({"min_transfer_kzt": "inf"}, 422, "min_transfer_kzt"),
        ({"min_transfer_kzt": "nan"}, 422, "min_transfer_kzt"),
        ({"max_depth": "0"}, 422, "max_depth"),
        ({"observation_start": "2026-07-10", "observation_end": "2026-07-01"}, 400, "observation_end"),
    ],
)
def test_invalid_collection_params_are_rejected(demo_client, tmp_path, form, status, field):
    archive = _zip_bytes(write_dataset(tmp_path / "in", *crafted_frames()))
    response = demo_client.post("/api/v1/runs", files=[("files", ("d.zip", archive, "application/zip"))], data=form)
    assert response.status_code == status
    assert [d["field"] for d in response.json()["error"]["details"]] == [field]


def test_row_limits_are_enforced_at_upload(tmp_path):
    archive = _zip_bytes(write_dataset(tmp_path / "in", *crafted_frames()))
    with TestClient(create_app(make_settings(tmp_path, max_nodes=5, scheduler_enabled=False))) as client:
        response = client.post("/api/v1/runs", files=[("files", ("d.zip", archive, "application/zip"))])
        assert client.get("/api/v1/runs").json()["total"] == 0
    assert response.status_code == 400 and response.json()["error"]["details"][0]["field"] == "nodes.parquet"


def _failing_insert(*args, **kwargs):
    raise sqlite3.OperationalError("disk I/O error")


def test_failed_insert_leaves_no_staged_upload(tmp_path, monkeypatch):
    archive = _zip_bytes(write_dataset(tmp_path / "in", *crafted_frames()))
    app = create_app(make_settings(tmp_path, scheduler_enabled=False))
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.services.runs, "create", _failing_insert)
        response = client.post("/api/v1/runs", files=[("files", ("d.zip", archive, "application/zip"))])
    assert response.status_code == 500 and response.json()["error"]["code"] == "internal_error"
    assert list(app.state.services.settings.runs_dir.iterdir()) == []


def test_protocol_errors_use_the_russian_envelope(demo_client):
    garbage = demo_client.post(
        "/api/v1/runs", content=b"\0" * 1000, headers={"content-type": "multipart/form-data; boundary=x"}
    ).json()["error"]
    unknown = demo_client.get("/api/v1/no-such-route").json()["error"]
    assert (garbage["code"], garbage["message"]) == ("validation_error", "Некорректное тело запроса")
    assert (unknown["code"], unknown["message"]) == ("not_found", "Ресурс не найден")


def test_oversized_upload_is_rejected_before_reading(demo_client):
    response = demo_client.post(
        "/api/v1/runs",
        content=b"x",
        headers={"content-length": str(10**12), "content-type": "multipart/form-data; boundary=b"},
    )
    assert response.status_code == 413 and response.json()["error"]["code"] == "payload_too_large"

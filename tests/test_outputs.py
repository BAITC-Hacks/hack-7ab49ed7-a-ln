"""Проверки выгрузок по схеме ТЗ + запрет на захардкоженные gid. Запуск: `uv run pytest`."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from moneygraph.pipeline import run
from moneygraph.validate import check

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


@pytest.fixture(scope="session")
def out_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("out")
    run(DATA, out)
    return out


def test_schema_checks_pass(out_dir):
    assert check(out_dir, DATA) == []


def test_every_node_has_role_and_evidence(out_dir):
    nr = pd.read_csv(out_dir / "nodes_roles.csv", dtype={"gid": str})
    nodes = pd.read_parquet(DATA / "nodes.parquet")
    assert len(nr) == len(nodes) == 2248
    assert set(nr.gid) == set(nodes.gid.astype(str))  # gid без потери точности
    assert nr.evidence.str.contains(r"\d").all()


def test_truncated_nodes_are_never_confirmed_sinks(out_dir):
    nr = pd.read_csv(out_dir / "nodes_roles.csv", dtype={"gid": str})
    d4 = nr[nr.depth == 4]
    assert len(d4) == 444
    assert (d4.sink_status == "truncated_depth").all()
    assert d4.evidence.str.contains("4-е колено").all()


def test_seed_roles_do_not_use_incoming_balance(out_dir):
    nr = pd.read_csv(out_dir / "nodes_roles.csv", dtype={"gid": str})
    seeds = nr[nr.is_seed]
    assert (seeds[seeds.role == "transit"].role_score <= 0.6 + 1e-9).all()


def test_typology_names(out_dir):
    nr = pd.read_csv(out_dir / "nodes_roles.csv", dtype={"gid": str})
    expected = {"consolidator": "funnel account (воронка)", "transit": "pass-through / money mule layering",
                "distributor": "fan-out payouts"}
    for role, name in expected.items():
        assert nr[nr.role == role].typology.str.startswith(name).all()
    fast = nr["flags"].str.contains("fast_transit")
    assert nr[fast].typology.str.contains("rapid movement of funds").all()


def test_top_nodes(out_dir):
    tp = pd.read_csv(out_dir / "top_nodes.csv", dtype={"gid": str})
    assert len(tp) >= 20
    assert list(tp["rank"]) == list(range(1, len(tp) + 1))
    assert tp.priority_score.is_monotonic_decreasing
    assert tp.why.str.len().min() > 50


def test_no_hardcoded_gids_in_source():
    pat = re.compile(r"\b1\d{17}\b")
    offenders = [p.name for p in (ROOT / "src").rglob("*.py") if pat.search(p.read_text(encoding="utf-8"))]
    assert offenders == [], f"gid-литералы в коде: {offenders}"

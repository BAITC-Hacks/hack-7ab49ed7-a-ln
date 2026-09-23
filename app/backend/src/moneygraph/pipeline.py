import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import pandas as pd

from . import config as C
from .artifacts import write_api_artifacts
from .clusters import cluster_table, louvain
from .collection import Collection
from .data import (
    InspectionLimits,
    build_graph,
    infer_collection,
    inspect_inputs,
    normalize,
    read_inputs,
    sanity_check,
    validate_inputs,
)
from .exports import validate_outputs, write_csv_exports
from .features import (
    ContinuationModel,
    continuation_model,
    cycle_features,
    dominator_control,
    flow_features,
    hop_anomaly,
    structure_features,
    temporal_features,
    trace_seed_money,
)
from .priority import priority, why
from .report import data_requests, role_rules_text, write_run_report
from .resilience import resilience
from .roles import assign_all
from .stats import RunStats

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, str, float], None]


@dataclass(frozen=True)
class CollectionOverrides:
    max_depth: int | None = None
    observation_start: str | None = None
    observation_end: str | None = None
    min_transfer_kzt: float | None = None


@dataclass(frozen=True)
class InputLimits:
    max_nodes: int | None = None
    max_transactions: int | None = None
    max_trace_cells: int | None = None
    max_decoded_bytes: int | None = None


def _ignore_progress(code: str, label: str, fraction: float) -> None:
    return None


def _node_features(
    G: nx.DiGraph, nodes, edges, tx, collection: Collection, progress: ProgressCallback
) -> tuple[pd.DataFrame, dict, ContinuationModel]:
    f = flow_features(G, nodes, edges, collection)
    f = f.join(trace_seed_money(nodes, tx, edges, collection))
    f = f.join(dominator_control(G, nodes))
    cluster_of = louvain(G)
    f["cluster_id"] = pd.Series(cluster_of)
    f = f.join(structure_features(G, f, cluster_of))
    progress("features", "Временные паттерны и циклы", 0.35)
    temporal, edge_days = temporal_features(f, tx, collection)
    f = f.join(temporal)
    cycles, cycle_stats = cycle_features(G, f, edge_days)
    f = f.join(cycles).join(hop_anomaly(f))
    f["p_continue"], model = continuation_model(f, tx, collection)
    return f, cycle_stats, model


def _ranked(f: pd.DataFrame, collection: Collection) -> pd.DataFrame:
    f = f.join(assign_all(f, collection))
    f = f.join(priority(f, collection))
    f = f.sort_values(["priority_score", "role_score"], ascending=False, kind="mergesort")
    f["rank"] = range(1, len(f) + 1)
    return f


def _top_list(f: pd.DataFrame) -> pd.DataFrame:
    top = f.head(C.TOP_N)
    return pd.DataFrame(
        {
            "rank": range(1, len(top) + 1),
            "gid": top.index,
            "role": top.role.values,
            "priority_score": top.priority_score.values,
            "why": [why(g, r) for g, r in top.iterrows()],
            "role_score": top.role_score.values,
            "cluster_id": top.cluster_id.values,
            "is_seed": top.is_seed.values,
            "evidence": top.evidence.values,
            "flags": top["flags"].apply(";".join).values,
        }
    )


def _summary(f: pd.DataFrame, edges, tx, n_clusters: int, flags: dict) -> dict:
    roles = f.role.value_counts()
    return {
        "n_nodes": int(len(f)),
        "n_edges": int(len(edges)),
        "n_tx": int(len(tx)),
        "n_seeds": int(f.is_seed.sum()),
        "total_kzt": round(float(edges.sum_kzt.sum()), 2),
        "period": [str(tx.date.min().date()), str(tx.date.max().date())],
        "n_clusters": n_clusters,
        "roles": {r: int(roles.get(r, 0)) for r in C.ROLES},
        "flags": flags,
    }


def run(
    data_dir: Path,
    out_dir: Path,
    api_dir: Path,
    overrides: CollectionOverrides = CollectionOverrides(),
    limits: InputLimits = InputLimits(),
    progress: ProgressCallback = _ignore_progress,
) -> RunStats:
    started = time.monotonic()
    out_dir.mkdir(parents=True, exist_ok=True)
    progress("validating", "Проверка входных данных", 0.02)
    inspect_inputs(
        data_dir,
        InspectionLimits(limits.max_nodes, limits.max_transactions, limits.max_decoded_bytes, limits.max_trace_cells),
    )
    raw_edges, raw_nodes, raw_tx = read_inputs(data_dir)
    validate_inputs(raw_edges, raw_nodes, raw_tx, limits.max_nodes, limits.max_transactions)
    collection, warnings = infer_collection(
        raw_nodes,
        raw_tx,
        overrides.max_depth,
        overrides.observation_start,
        overrides.observation_end,
        overrides.min_transfer_kzt,
    )
    edges, nodes, tx = normalize(raw_edges, raw_nodes, raw_tx, collection)
    counts = sanity_check(edges, nodes, tx)
    progress("features", f"Признаки: {counts['nodes']} узлов, {counts['edges']} рёбер", 0.10)

    G = build_graph(edges, nodes)
    f, cycle_stats, model = _node_features(G, nodes, edges, tx, collection, progress)
    progress("roles", "Роли и приоритеты", 0.55)
    f = _ranked(f, collection)

    progress("clusters", "Кластеры и выгрузки", 0.65)
    clusters = cluster_table(G, f, collection)
    top = _top_list(f)

    progress("exports", "Устойчивость сети и запросы данных", 0.80)
    resilience_base, resilience_rows = resilience(G, f)
    requests = data_requests(f, collection)
    flags = pd.Series([x for fl in f["flags"] for x in fl]).value_counts().to_dict()
    stats = RunStats(
        summary=_summary(f, edges, tx, len(clusters), flags),
        collection=collection,
        warnings=warnings,
        engine_version=C.ENGINE_VERSION,
        roles=f.role.value_counts().to_dict(),
        n_clusters=len(clusters),
        model=model,
        cycles=cycle_stats,
        flags=flags,
        resilience_base=resilience_base,
        resilience_rows=resilience_rows.to_dict("records"),
        data_requests=requests.request.value_counts().to_dict(),
    )
    write_csv_exports(out_dir, f, clusters, top, resilience_rows, requests)
    validate_outputs(out_dir, nodes)

    progress("publishing", "Запись результатов", 0.95)
    write_api_artifacts(api_dir, G, f, clusters, top, edges, tx, stats, role_rules_text(collection))
    stats.runtime_s = round(time.monotonic() - started, 1)
    write_run_report(out_dir, stats, resilience_rows, clusters)
    (out_dir / "run_stats.json").write_text(json.dumps(stats.as_dict(), ensure_ascii=False, indent=2, default=str))
    logger.info("run finished in %.1fs: %s", stats.runtime_s, stats.roles)
    progress("done", "Готово", 1.0)
    return stats

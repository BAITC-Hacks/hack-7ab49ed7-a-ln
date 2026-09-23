"""Оркестрация: parquet → признаки → роли → кластеры → приоритет → выгрузки + экран просмотра."""
import json
import time
from pathlib import Path

import pandas as pd

from . import config as C
from .clusters import cluster_table, louvain
from .data import build_graph, load, sanity_check
from .features import (base_features, cycle_features, dominator_control, hop_anomaly, structure_features,
                       temporal_features, trace_seed_money, truncation_model)
from .priority import priority, why
from .report import data_requests, role_rules_text, validate, write_run_report
from .resilience import resilience
from .roles import assign_all
from .viewer import export_viewer


def log(msg, t0):
    print(f"[{time.time() - t0:5.1f}s] {msg}", flush=True)


def run(data_dir: Path, out_dir: Path, viewer_dir: Path | None) -> dict:
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    edges, nodes, tx = load(data_dir)
    summary = sanity_check(edges, nodes, tx)
    log(f"данные: {summary['nodes']} узлов, {summary['edges']} рёбер, {summary['transactions']} транзакций", t0)

    G = build_graph(edges, nodes)
    f = base_features(G, nodes, edges)
    f = f.join(trace_seed_money(nodes, tx, edges))
    f = f.join(dominator_control(G, nodes))
    cluster_of = louvain(G)
    f["cluster_id"] = pd.Series(cluster_of)
    f = f.join(structure_features(G, f, cluster_of))
    temporal, edge_days = temporal_features(f, tx)
    f = f.join(temporal)
    cyc, cyc_stats = cycle_features(G, f, edge_days)
    f = f.join(cyc).join(hop_anomaly(f))
    f["p_continue"], trunc_info = truncation_model(f, tx)
    log("признаки посчитаны", t0)

    f = f.join(assign_all(f))
    f = f.join(priority(f))
    f = f.sort_values(["priority_score", "role_score"], ascending=False, kind="mergesort")
    f["rank"] = range(1, len(f) + 1)
    log("роли и приоритеты назначены", t0)

    # ---- выгрузки (обязательные колонки первыми, в порядке ТЗ)
    flags_str = f["flags"].apply(";".join)
    roles_df = pd.DataFrame({"gid": f.index, "role": f.role.values, "role_score": f.role_score.values,
                             "cluster_id": f.cluster_id.values, "priority_score": f.priority_score.values,
                             "evidence": f.evidence.values, "flags": flags_str.values, "depth": f.depth.values,
                             "is_seed": f.is_seed.values, "priority_rank": f["rank"].values})
    roles_df.to_csv(out_dir / "nodes_roles.csv", index=False)

    clusters = cluster_table(G, f)
    clusters.to_csv(out_dir / "clusters.csv", index=False)

    top = f.head(C.TOP_N)
    top_df = pd.DataFrame({"rank": range(1, len(top) + 1), "gid": top.index, "role": top.role.values,
                           "priority_score": top.priority_score.values,
                           "why": [why(g, r) for g, r in top.iterrows()],
                           "role_score": top.role_score.values, "cluster_id": top.cluster_id.values,
                           "is_seed": top.is_seed.values, "evidence": top.evidence.values,
                           "flags": flags_str.loc[top.index].values})
    top_df.to_csv(out_dir / "top_nodes.csv", index=False)

    feat = f.drop(columns=["evidence"]).copy()
    feat["flags"] = flags_str
    feat.index.name = "gid"
    feat.reset_index().to_csv(out_dir / "features.csv", index=False)

    base, res = resilience(G, f)
    res.to_csv(out_dir / "resilience.csv", index=False)
    requests = data_requests(f)
    requests.to_csv(out_dir / "data_requests.csv", index=False)
    log("CSV записаны", t0)

    stats = {"data": summary, "runtime_s": None, "roles": f.role.value_counts().to_dict(),
             "n_clusters": int(len(clusters)), "truncation_model": trunc_info, "cycles": cyc_stats,
             "flags": pd.Series([x for fl in f["flags"] for x in fl]).value_counts().to_dict(),
             "resilience_base": base, "resilience": res.to_dict("records"),
             "data_requests": requests.request.value_counts().to_dict()}
    if viewer_dir is not None:
        p = export_viewer(G, f, clusters, top_df, edges, tx, viewer_dir,
                          meta_extra={"role_rules": role_rules_text(), "run": {
                              "truncation_auc": trunc_info["auc_cv"], "resilience": res.to_dict("records"),
                              "resilience_base": base}})
        log(f"экран просмотра: {p} ({p.stat().st_size // 1024} КБ)", t0)
    stats["runtime_s"] = round(time.time() - t0, 1)
    write_run_report(out_dir, stats, res, clusters)
    (out_dir / "run_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
    validate(out_dir, nodes)
    log("проверка схемы пройдена", t0)
    return stats

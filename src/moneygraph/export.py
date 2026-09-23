"""Выгрузки: три обязательных CSV (схема ТЗ + доп. колонки), дополнительные CSV и out/graph.json."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

from moneygraph.config import FLAG_RU, ROLE_META, ROLES

REQUIRED_NODE_COLS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
EXTRA_NODE_COLS = [
    "rank", "rule_fired", "alt_role", "typology", "sink_status", "truncated", "p_forward", "is_seed", "depth",
    "in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx", "out_in_ratio", "fast_share",
    "unseen_inflow_kzt", "seed_in", "seed_out", "pagerank", "betweenness", "flags",
    "prio_role", "prio_flow", "prio_centrality", "prio_seed", "prio_flags",
]


def _csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def nodes_roles(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # без NaN: −1 = «не применимо» (нет входящих в выборке / нет пар вход-выход)
    out["out_in_ratio"] = np.where(out.in_kzt > 0, (out.out_kzt / out.in_kzt.where(out.in_kzt > 0)).round(4), -1.0)
    out["fast_share"] = out.fast_share.fillna(-1.0).round(4)
    out["flags"] = out["flags"].map(lambda f: ";".join(f) if f else "-")
    out["typology"] = out["typology"].map(lambda t: t or "-")
    out["pagerank"] = out.pagerank.round(8)
    out["betweenness"] = out.betweenness.round(8)
    out = out.sort_values("rank")[REQUIRED_NODE_COLS + EXTRA_NODE_COLS]
    return out


def write_all(out_dir: Path, df: pd.DataFrame, clusters: pd.DataFrame, top: pd.DataFrame, extra: dict[str, pd.DataFrame]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _csv(nodes_roles(df), out_dir / "nodes_roles.csv")
    _csv(clusters, out_dir / "clusters.csv")
    _csv(top, out_dir / "top_nodes.csv")
    for name, t in extra.items():
        _csv(t, out_dir / f"{name}.csv")


def graph_json(G: nx.DiGraph, df: pd.DataFrame, clusters: pd.DataFrame, top: pd.DataFrame,
               pos: dict[int, tuple[float, float]], tx_lists: dict, meta_extra: dict) -> dict:
    def num(v, nd=4):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return round(float(v), nd)

    nodes = []
    for r in df.sort_values("rank").itertuples(index=False):
        x, y = pos.get(r.gid, (0.0, 0.0))
        nodes.append({
            "id": str(r.gid), "role": r.role, "role_score": num(r.role_score, 3), "rule_fired": r.rule_fired,
            "alt_role": "" if r.alt_role == "-" else r.alt_role, "typology": r.typology, "evidence": r.evidence,
            "priority": num(r.priority_score), "rank": int(r.rank), "cluster": int(r.cluster_id),
            "is_seed": bool(r.is_seed), "depth": int(r.depth), "truncated": bool(r.truncated),
            "p_forward": num(r.p_forward, 3) if r.truncated else None, "sink_status": r.sink_status,
            "in_deg": int(r.in_deg), "out_deg": int(r.out_deg), "in_kzt": num(r.in_kzt, 2), "out_kzt": num(r.out_kzt, 2),
            "in_tx": int(r.in_tx), "out_tx": int(r.out_tx), "pagerank": num(r.pagerank, 6),
            "betweenness": num(r.betweenness, 6), "fast_share": num(r.fast_share, 3), "flags": list(r.flags),
            "prio_parts": {"role": num(r.prio_role), "flow": num(r.prio_flow), "centrality": num(r.prio_centrality),
                           "seed": num(r.prio_seed), "flags": num(r.prio_flags)},
            "x": x, "y": y,
        })
    edges = [{"from": str(u), "to": str(v), "sum": round(d["sum_kzt"], 2), "n_tx": d["n_tx"],
              "tx": tx_lists.get((u, v), [])} for u, v, d in G.edges(data=True)]
    cl = [{"id": int(r.cluster_id), "n_nodes": int(r.n_nodes), "n_seed": int(r.n_seed),
           "sum_internal": float(r.sum_kzt_internal), "hypothesis": r.hypothesis,
           "top_gids": [g for g in str(r.top_gids).split(";") if g],
           "roles": {k: int(v) for k, v in df[df.cluster_id == r.cluster_id].role.value_counts().items()},
           "stability": float(r.stability), "isolated_fragment": bool(r.isolated_fragment)}
          for r in clusters.itertuples(index=False)]
    tp = [{"rank": int(r.rank), "gid": str(r.gid), "role": r.role, "priority": float(r.priority_score),
           "why": r.why, "is_seed": bool(r.is_seed)} for r in top.itertuples(index=False)]
    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "period": ["2026-07-01", "2026-07-31"],
        "n_nodes": len(df), "n_edges": G.number_of_edges(), "n_tx": int(sum(d["n_tx"] for *_, d in G.edges(data=True))),
        "n_seed": int(df.is_seed.sum()), "total_kzt": round(sum(d["sum_kzt"] for *_, d in G.edges(data=True)), 2),
        "roles": {r: ROLE_META[r] for r in ROLES},
        "role_counts": {r: int((df.role == r).sum()) for r in ROLES},
        "flags": FLAG_RU,
        **meta_extra,
    }
    return {"meta": meta, "nodes": nodes, "edges": edges, "clusters": cl, "top": tp}


def write_graph_json(graph: dict, path: Path) -> None:
    path.write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

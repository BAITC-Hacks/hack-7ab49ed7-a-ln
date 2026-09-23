import json
from pathlib import Path

import pandas as pd

from . import config as C
from .layout import layout, node_card
from .stats import RunStats
from .texts import FLAG_RU, ROLE_COLORS, ROLE_RU

ARTIFACT_VERSION = 1


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if hasattr(obj, "item"):
        return obj.item()
    return obj


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False))


def _nodes_table(G, f: pd.DataFrame, top: pd.DataFrame) -> pd.DataFrame:
    positions = layout(G, f.cluster_id)
    top_rank = {g: i + 1 for i, g in enumerate(top.gid)}
    nodes = f.copy()
    nodes["card"] = [node_card(g, r, G, f.role) for g, r in f.iterrows()]
    nodes["flags"] = nodes["flags"].apply(";".join)
    nodes = nodes.rename(columns={"rank": "priority_rank"})
    nodes["top_rank"] = [top_rank.get(g) for g in nodes.index]
    nodes["x"] = [positions[g][0] for g in nodes.index]
    nodes["y"] = [positions[g][1] for g in nodes.index]
    nodes["why"] = pd.Series(dict(zip(top.gid, top.why, strict=True))).reindex(nodes.index)
    nodes.index.name = "gid"
    return nodes.reset_index()


def _edges_table(edges: pd.DataFrame, tx: pd.DataFrame) -> pd.DataFrame:
    day = tx.date.dt.strftime("%Y-%m-%d")
    span = tx.assign(d=day).groupby(["src", "dst"]).d.agg(first_date="min", last_date="max").reset_index()
    return edges.merge(span, on=["src", "dst"], how="left")


def _meta(stats: RunStats, role_rules: dict) -> dict:
    return {
        "artifact_version": ARTIFACT_VERSION,
        "engine_version": stats.engine_version,
        "params": stats.collection.as_dict(),
        "warnings": stats.warnings,
        "summary": stats.summary,
        "model": stats.model.as_dict(),
        "resilience": {"base": stats.resilience_base, "rows": stats.resilience_rows},
        "cycles": stats.cycles,
        "data_requests": stats.data_requests,
        "roles": {k: {"label": ROLE_RU[k], "color": ROLE_COLORS[k], "rule": role_rules.get(k, "")} for k in C.ROLES},
        "flags": FLAG_RU,
    }


def _clusters_payload(clusters: pd.DataFrame) -> list[dict]:
    return [
        {
            "cluster_id": int(r.cluster_id),
            "n_nodes": int(r.n_nodes),
            "n_seed": int(r.n_seed),
            "sum_kzt_internal": float(r.sum_kzt_internal),
            "top_gids": [x for x in str(r.top_gids).split(";") if x],
            "hypothesis": r.hypothesis,
            "max_priority": float(r.max_priority),
            "roles": {k: int(getattr(r, f"n_{k}")) for k in C.ROLES},
            "n_truncated": int(r.n_truncated),
        }
        for r in clusters.itertuples(index=False)
    ]


def _top_payload(top: pd.DataFrame) -> list[dict]:
    return [
        {
            "top_rank": int(r.rank),
            "id": str(r.gid),
            "role": r.role,
            "priority_score": float(r.priority_score),
            "role_score": float(r.role_score),
            "is_seed": bool(r.is_seed),
            "cluster_id": int(r.cluster_id),
            "evidence": r.evidence,
            "why": r.why,
            "flags": [x for x in str(r.flags).split(";") if x],
        }
        for r in top.itertuples(index=False)
    ]


def write_api_artifacts(
    api_dir: Path,
    G,
    f: pd.DataFrame,
    clusters: pd.DataFrame,
    top: pd.DataFrame,
    edges: pd.DataFrame,
    tx: pd.DataFrame,
    stats: RunStats,
    role_rules: dict,
) -> None:
    api_dir.mkdir(parents=True, exist_ok=True)
    _nodes_table(G, f, top).to_parquet(api_dir / "nodes.parquet", index=False)
    _edges_table(edges, tx).to_parquet(api_dir / "edges.parquet", index=False)
    tx.assign(date=tx.date.dt.strftime("%Y-%m-%d"))[["src", "dst", "date", "sum_kzt"]].to_parquet(
        api_dir / "tx.parquet", index=False
    )
    _write_json(api_dir / "meta.json", _meta(stats, role_rules))
    _write_json(api_dir / "clusters.json", _clusters_payload(clusters))
    _write_json(api_dir / "top.json", _top_payload(top))

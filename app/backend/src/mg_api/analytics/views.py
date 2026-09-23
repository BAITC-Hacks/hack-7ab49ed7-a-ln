from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from moneygraph import config as engine_config
from moneygraph.priority import COMPONENT_RU

from .graphops import optional_int
from .store import RunData

METRICS = (
    ("traced_in_kzt", "Вход, связанный с seed (трассировка по датам)", "kzt"),
    ("traced_share", "Доля входа, связанная с seed", "share"),
    ("seed_sources", "Seed, чьи деньги дошли до узла", "count"),
    ("main_seed", "Основной seed-источник", "gid"),
    ("control_nodes", "Узлов, отрезаемых от seed при блокировке", "count"),
    ("control_kzt", "Вход отрезаемых узлов", "kzt"),
    ("betweenness_pct", "Посредничество (перцентиль в компоненте)", "share"),
    ("partner_clusters", "Кластеров среди контрагентов", "count"),
    ("fast_2d_share", "Переслано за 0–2 дня (FIFO)", "share"),
    ("strict_fast_2d_share", "Переслано строго через 1–2 дня", "share"),
    ("sync_max_payers", "Максимум плательщиков в один день", "count"),
    ("repeated_routes", "Повторяющихся маршрутов A→узел→C", "count"),
    ("dated_returns", "Датированных возвратов (циклы ≤7 дн.)", "count"),
    ("p_continue", "Оценка дальнейших переводов (обрыв обхода)", "share"),
    ("pass_ratio", "Отдал / получил", "ratio"),
    ("followup_days", "Дней наблюдения после последнего входа", "days"),
    ("hop_z", "Отклонение от узлов своего колена (z)", "z"),
    ("reachable_seeds", "Seed, от которых узел достижим", "count"),
)
RULE_KEYS = ("coordinator", "consolidator", "distributor", "transit", "terminal")
SORTABLE = ("priority_score", "role_score", "in_kzt", "out_kzt", "in_deg", "out_deg", "traced_in_kzt", "control_nodes")


def _number(value):
    if value is None or pd.isna(value):
        return None
    as_float = float(value)
    return int(as_float) if as_float.is_integer() and abs(as_float) < 1e15 else round(as_float, 4)


def _flags(value) -> list[str]:
    return [x for x in str(value or "").split(";") if x]


def node_row(r) -> dict:
    return {
        "id": str(int(r.gid)),
        "role": r.role,
        "role_score": float(r.role_score),
        "priority_score": float(r.priority_score),
        "priority_rank": int(r.priority_rank),
        "top_rank": optional_int(r.top_rank),
        "cluster_id": int(r.cluster_id),
        "depth": int(r.depth),
        "is_seed": bool(r.is_seed),
        "truncated": bool(r.truncated),
        "flags": _flags(r.flags),
        "in_deg": int(r.in_deg),
        "out_deg": int(r.out_deg),
        "in_kzt": round(float(r.in_kzt), 2),
        "out_kzt": round(float(r.out_kzt), 2),
        "in_tx": int(r.in_tx),
        "out_tx": int(r.out_tx),
        "evidence": r.evidence,
    }


def _metric_value(r, key: str):
    if key == "main_seed":
        seed = r[key]
        return str(int(seed)) if seed and not pd.isna(seed) else None
    return _number(r[key])


def _metrics(r) -> list[dict]:
    # The continuation estimate only means something for nodes whose outflow was never collected.
    return [
        {"key": key, "label": label, "value": _metric_value(r, key), "unit": unit}
        for key, label, unit in METRICS
        if key != "p_continue" or bool(r.truncated)
    ]


def _priority_components(r) -> list[dict]:
    components = []
    for key, weight in engine_config.PRIORITY_WEIGHTS.items():
        value = float(r[f"p_{key}"])
        components.append(
            {
                "key": key,
                "label": COMPONENT_RU[key],
                "weight": weight,
                "value": round(value, 4),
                "contribution": round(weight * value, 4),
            }
        )
    return components


def node_detail(data: RunData, gid: int) -> dict:
    r = data.nodes.loc[gid]
    return node_row(r) | {
        "card": r.card,
        "why": None if pd.isna(r.why) else r.why,
        "metrics": _metrics(r),
        "priority_components": _priority_components(r),
        "priority_reliability": float(r.priority_reliability),
        "rules": {k: bool(r[f"rule_{k}"]) for k in RULE_KEYS},
        "n_payers": int(r.in_deg),
        "n_recipients": int(r.out_deg),
    }


@dataclass(frozen=True)
class NodeQuery:
    q: str | None = None
    roles: list[str] | None = None
    cluster_id: int | None = None
    is_seed: bool | None = None
    flag: str | None = None
    sort_by: str = "priority_score"
    descending: bool = True
    limit: int = 50
    offset: int = 0


def node_page(data: RunData, query: NodeQuery) -> dict:
    df = data.nodes
    mask = pd.Series(True, index=df.index)
    if query.q:
        mask &= data.gid_text.str.contains(query.q, regex=False)
    if query.roles:
        mask &= df.role.isin(query.roles)
    if query.cluster_id is not None:
        mask &= df.cluster_id == query.cluster_id
    if query.is_seed is not None:
        mask &= df.is_seed == query.is_seed
    if query.flag:
        mask &= df.flags.str.split(";").apply(lambda flags: query.flag in flags)
    selected = df[mask].sort_values([query.sort_by, "gid"], ascending=[not query.descending, True])
    page = selected.iloc[query.offset : query.offset + query.limit]
    return {"items": [node_row(r) for r in page.itertuples(index=False)], "total": int(len(selected))}


def search(data: RunData, q: str, limit: int) -> dict:
    hits = data.nodes[data.gid_text.str.contains(q, regex=False)]
    hits = hits.sort_values(["priority_score", "gid"], ascending=[False, True])
    return {
        "items": [
            {
                "id": str(r.gid),
                "role": r.role,
                "priority_score": float(r.priority_score),
                "priority_rank": int(r.priority_rank),
            }
            for r in hits.head(limit).itertuples(index=False)
        ],
        "total": int(len(hits)),
    }


def counterparties(data: RunData, gid: int, direction: str, limit: int, offset: int) -> dict:
    adjacency = data.G.pred[gid] if direction == "in" else data.G.succ[gid]
    ordered = sorted(adjacency.items(), key=lambda kv: (-kv[1]["sum_kzt"], kv[0]))
    page = ordered[offset : offset + limit]
    roles = data.nodes.role.loc[[o for o, _ in page]].to_dict() if page else {}
    return {
        "items": [
            {
                "id": str(o),
                "role": roles[o],
                "sum_kzt": round(d["sum_kzt"], 2),
                "n_tx": int(d["n_tx"]),
                "first_date": d["first_date"],
                "last_date": d["last_date"],
            }
            for o, d in page
        ],
        "total": len(ordered),
    }


def _transaction_mask(tx: pd.DataFrame, gid: int, counterparty: int | None, direction: str) -> pd.Series:
    incoming = (tx.dst == gid) & ((tx.src == counterparty) if counterparty is not None else True)
    outgoing = (tx.src == gid) & ((tx.dst == counterparty) if counterparty is not None else True)
    return {"in": incoming, "out": outgoing}.get(direction, incoming | outgoing)


def transactions(data: RunData, gid: int, counterparty: int | None, direction: str, limit: int, offset: int) -> dict:
    selected = data.tx[_transaction_mask(data.tx, gid, counterparty, direction)]
    selected = selected.sort_values(["date", "src", "dst", "sum_kzt"])
    page = selected.iloc[offset : offset + limit]
    return {
        "items": [
            {"date": r.date, "source": str(r.src), "target": str(r.dst), "sum_kzt": round(float(r.sum_kzt), 2)}
            for r in page.itertuples(index=False)
        ],
        "total": int(len(selected)),
    }


def data_requests(csv_path: Path, limit: int, offset: int) -> dict:
    table = pd.read_csv(csv_path, dtype={"gid": "int64"})
    page = table.iloc[offset : offset + limit]
    return {
        "items": [
            {"id": str(r.gid), "request": r.request, "value_kzt": float(r.value_kzt), "reason": r.reason}
            for r in page.itertuples(index=False)
        ],
        "total": int(len(table)),
    }

"""Инструменты AI-ассистента: только чтение предрасчитанного out/graph.json (gid — строки)."""

from __future__ import annotations

import json
from collections import deque

from moneygraph.cards import index, resolve, role_ru

MAX_RESULT_CHARS = 12000


def _compact(n: dict, graph: dict) -> dict:
    return {
        "gid": n["id"], "role": n["role"], "role_ru": role_ru(graph, n["role"]),
        "role_score": n.get("role_score"), "priority": n.get("priority"), "rank": n.get("rank"),
        "cluster": n.get("cluster"), "is_seed": n.get("is_seed"), "depth": n.get("depth"),
        "in_deg": n.get("in_deg"), "out_deg": n.get("out_deg"),
        "in_kzt": round(n.get("in_kzt") or 0), "out_kzt": round(n.get("out_kzt") or 0),
        "in_tx": n.get("in_tx"), "out_tx": n.get("out_tx"),
        "evidence": n.get("evidence"),
    }


def _edge_view(e: dict, other: str, direction: str, graph: dict) -> dict:
    n = index(graph)["by_id"].get(other, {})
    days = sorted({d for d, _ in e.get("tx", [])})
    return {"gid": other, "direction": direction, "role": n.get("role"), "is_seed": n.get("is_seed"),
            "priority": n.get("priority"), "sum_kzt": round(e["sum"]), "n_tx": e["n_tx"],
            "first_date": days[0] if days else None, "last_date": days[-1] if days else None}


def _one(gid_or_suffix: str, graph: dict) -> tuple[str | None, dict | None]:
    hits = resolve(gid_or_suffix, graph)
    if len(hits) == 1:
        return hits[0], None
    if not hits:
        return None, {"error": f"узел «{gid_or_suffix}» не найден"}
    by_id = index(graph)["by_id"]
    return None, {"error": "неоднозначно, уточните gid", "n_matches": len(hits),
                  "matches": [_compact(by_id[g], graph) for g in hits[:10]]}


# ---------------------------------------------------------------- инструменты

def overview(graph: dict) -> dict:
    meta = graph.get("meta", {})
    idx = index(graph)
    return {
        "period": meta.get("period"), "n_nodes": meta.get("n_nodes"), "n_edges": meta.get("n_edges"),
        "n_tx": meta.get("n_tx"), "n_seed": meta.get("n_seed"), "total_kzt": meta.get("total_kzt"),
        "role_counts": meta.get("role_counts"),
        "roles": {k: {"ru": v.get("ru"), "description": v.get("description")}
                  for k, v in meta.get("roles", {}).items()},
        "n_clusters": len(idx["clusters"]),
        "top5": [_compact(n, graph) for n in idx["by_rank"][:5]],
        "data_limits": "обход 4 колена только по исходящим; у 4-го колена исходящие не выгружены; "
                       "входящие частичны у всех узлов; порог 5 000 ₸; только июль 2026; только внутри банка",
    }


def get_node(graph: dict, gid_or_suffix: str) -> dict:
    gid, err = _one(gid_or_suffix, graph)
    if err:
        return err
    idx = index(graph)
    n = idx["by_id"][gid]
    out = _compact(n, graph)
    out.update({
        "rule_fired": n.get("rule_fired"), "alt_role": n.get("alt_role") or None,
        "typology": n.get("typology") or None,
        "sink_status": n.get("sink_status"), "truncated": n.get("truncated"), "p_forward": n.get("p_forward"),
        "fast_share": n.get("fast_share"), "flags": n.get("flags"), "prio_parts": n.get("prio_parts"),
        "pagerank": n.get("pagerank"), "betweenness": n.get("betweenness"),
    })
    c = idx["clusters"].get(n.get("cluster"))
    if c:
        out["cluster_info"] = {"n_nodes": c["n_nodes"], "n_seed": c["n_seed"], "hypothesis": c.get("hypothesis")}
    top = idx["top"].get(gid)
    if top:
        out["why_top"] = top.get("why")
    out["top_payers"] = [_edge_view(e, e["from"], "in", graph) for e in idx["in"].get(gid, [])[:5]]
    out["top_receivers"] = [_edge_view(e, e["to"], "out", graph) for e in idx["out"].get(gid, [])[:5]]
    return out


def neighbors(graph: dict, gid: str, direction: str = "both", limit: int = 15) -> dict:
    g, err = _one(gid, graph)
    if err:
        return err
    idx = index(graph)
    rows = []
    if direction in ("in", "both"):
        rows += [_edge_view(e, e["from"], "in", graph) for e in idx["in"].get(g, [])]
    if direction in ("out", "both"):
        rows += [_edge_view(e, e["to"], "out", graph) for e in idx["out"].get(g, [])]
    rows.sort(key=lambda r: -r["sum_kzt"])
    return {"gid": g, "direction": direction, "total": len(rows), "neighbors": rows[: max(1, int(limit))]}


def top_nodes(graph: dict, role: str | None = None, cluster: int | None = None, n: int = 10) -> dict:
    idx = index(graph)
    rows = [x for x in idx["by_rank"]
            if (role is None or x["role"] == role) and (cluster is None or x.get("cluster") == int(cluster))]
    res = []
    for x in rows[: max(1, int(n))]:
        d = _compact(x, graph)
        if x["id"] in idx["top"]:
            d["why"] = idx["top"][x["id"]].get("why")
        res.append(d)
    return {"role": role, "cluster": cluster, "total": len(rows), "nodes": res}


def cluster_summary(graph: dict, cluster_id: int) -> dict:
    idx = index(graph)
    c = idx["clusters"].get(int(cluster_id))
    if c is None:
        return {"error": f"кластер {cluster_id} не найден", "n_clusters": len(idx["clusters"])}
    members = [x for x in idx["by_rank"] if x.get("cluster") == int(cluster_id)]
    return {"cluster_id": c["id"], "n_nodes": c["n_nodes"], "n_seed": c["n_seed"],
            "sum_internal_kzt": round(c.get("sum_internal") or 0), "hypothesis": c.get("hypothesis"),
            "roles": c.get("roles"), "top_nodes": [_compact(x, graph) for x in members[:8]]}


def find_paths(graph: dict, src: str, dst: str, max_len: int = 4, limit: int = 10) -> dict:
    """Направленные простые пути src → dst длиной ≤ max_len (ребёр); с отсечением по BFS от dst."""
    a, err = _one(src, graph)
    if err:
        return {"src_error": err}
    b, err = _one(dst, graph)
    if err:
        return {"dst_error": err}
    if a == b:
        return {"src": a, "dst": b, "n_found": 0, "paths": [], "note": "src и dst совпадают"}
    max_len = max(1, min(int(max_len), 6))
    idx = index(graph)
    # расстояние до b по обратным рёбрам
    dist = {b: 0}
    q = deque([b])
    while q:
        v = q.popleft()
        if dist[v] >= max_len:
            continue
        for e in idx["in"].get(v, []):
            u = e["from"]
            if u not in dist:
                dist[u] = dist[v] + 1
                q.append(u)
    paths: list[list[dict]] = []

    def dfs(v: str, path: list[str], hops: list[dict]):
        if len(paths) >= 200:
            return
        if v == b:
            paths.append(list(hops))
            return
        left = max_len - len(hops)
        for e in idx["out"].get(v, []):
            w = e["to"]
            if w in path or dist.get(w, 99) > left - 1:
                continue
            path.append(w)
            hops.append({"from": v, "to": w, "sum_kzt": round(e["sum"]), "n_tx": e["n_tx"]})
            dfs(w, path, hops)
            path.pop()
            hops.pop()

    if a in dist:
        dfs(a, [a], [])
    paths.sort(key=lambda p: (-min(h["sum_kzt"] for h in p), len(p)))
    res = [{"nodes": [p[0]["from"], *(h["to"] for h in p)], "hops": p,
            "bottleneck_kzt": min(h["sum_kzt"] for h in p)} for p in paths[: max(1, int(limit))]]
    out = {"src": a, "dst": b, "max_len": max_len, "n_found": len(paths), "paths": res}
    if not paths:
        out["note"] = "направленных путей нет; проверьте обратное направление (dst → src)"
    return out


def search_nodes(graph: dict, role: str | None = None, cluster: int | None = None, is_seed: bool | None = None,
                 min_in_deg: int | None = None, min_out_deg: int | None = None,
                 min_priority: float | None = None, limit: int = 20) -> dict:
    idx = index(graph)
    rows = [x for x in idx["by_rank"]
            if (role is None or x["role"] == role)
            and (cluster is None or x.get("cluster") == int(cluster))
            and (is_seed is None or bool(x.get("is_seed")) == bool(is_seed))
            and (min_in_deg is None or (x.get("in_deg") or 0) >= min_in_deg)
            and (min_out_deg is None or (x.get("out_deg") or 0) >= min_out_deg)
            and (min_priority is None or (x.get("priority") or 0) >= min_priority)]
    return {"total": len(rows), "nodes": [_compact(x, graph) for x in rows[: max(1, int(limit))]]}


def common_counterparties(graph: dict, gids: list[str], direction: str = "out", max_hops: int = 2,
                          limit: int = 15) -> dict:
    """Кто связан сразу с несколькими из заданных узлов: direction=out — куда уходят их деньги
    (напр. «кто собирает деньги с этих пятерых»), in — откуда приходят. Пути ≤ max_hops."""
    idx = index(graph)
    max_hops = max(1, min(int(max_hops), 4))
    resolved, errors = [], []
    for q in gids:
        g, err = _one(str(q), graph)
        (resolved.append(g) if g else errors.append({"query": q, **err}))
    adj = idx["out"] if direction == "out" else idx["in"]
    key = "to" if direction == "out" else "from"
    reach: dict[str, dict[str, int]] = {}
    for g in resolved:
        seen = {g: 0}
        q = deque([g])
        while q:
            v = q.popleft()
            if seen[v] >= max_hops:
                continue
            for e in adj.get(v, []):
                w = e[key]
                if w not in seen:
                    seen[w] = seen[v] + 1
                    q.append(w)
        for w, h in seen.items():
            if w != g:
                reach.setdefault(w, {})[g] = h
    rows = []
    for w, srcs in reach.items():
        if len(srcs) >= 2 and w not in resolved:
            d = _compact(idx["by_id"][w], graph)
            d.update({"n_linked": len(srcs), "linked": [{"gid": s, "hops": h} for s, h in srcs.items()]})
            rows.append(d)
    rows.sort(key=lambda d: (-d["n_linked"], -(d.get("priority") or 0)))
    return {"direction": direction, "max_hops": max_hops, "inputs": resolved, "errors": errors,
            "total": len(rows), "nodes": rows[: max(1, int(limit))]}


# ---------------------------------------------------------------- схемы и диспетчер

_ROLE_ENUM = ["coordinator", "consolidator", "distributor", "transit", "terminal", "peripheral"]

TOOLS: list[dict] = [
    {"name": "overview", "description": "Сводка по графу: период, объёмы, число узлов по ролям, словарь ролей, "
     "топ-5 по приоритету, ограничения данных.", "parameters": {"type": "object", "properties": {}}},
    {"name": "get_node", "description": "Полная карточка узла: роль, уверенность, сработавшее правило, "
     "обоснование, приоритет, кластер, флаги, крупнейшие плательщики и получатели. Принимает полный gid "
     "или его последние цифры.",
     "parameters": {"type": "object", "properties": {"gid_or_suffix": {"type": "string"}},
                    "required": ["gid_or_suffix"]}},
    {"name": "neighbors", "description": "Контрагенты узла: входящие (кто платил), исходящие (кому платил) "
     "или оба направления, с суммами, числом переводов и датами.",
     "parameters": {"type": "object", "properties": {
         "gid": {"type": "string"}, "direction": {"type": "string", "enum": ["in", "out", "both"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, "required": ["gid"]}},
    {"name": "top_nodes", "description": "Узлы по убыванию приоритета проверки, с фильтром по роли и кластеру.",
     "parameters": {"type": "object", "properties": {
         "role": {"type": "string", "enum": _ROLE_ENUM}, "cluster": {"type": "integer"},
         "n": {"type": "integer", "minimum": 1, "maximum": 50}}}},
    {"name": "cluster_summary", "description": "Кластер: размер, число seed, внутренний оборот, гипотеза "
     "о назначении, состав ролей и главные узлы.",
     "parameters": {"type": "object", "properties": {"cluster_id": {"type": "integer"}},
                    "required": ["cluster_id"]}},
    {"name": "find_paths", "description": "Направленные цепочки переводов от src к dst (не длиннее max_len "
     "рёбер) с суммами на каждом шаге.",
     "parameters": {"type": "object", "properties": {
         "src": {"type": "string"}, "dst": {"type": "string"},
         "max_len": {"type": "integer", "minimum": 1, "maximum": 6}}, "required": ["src", "dst"]}},
    {"name": "search_nodes", "description": "Поиск узлов по фильтрам (роль, кластер, seed, минимальные "
     "степени, минимальный приоритет); результат отсортирован по приоритету.",
     "parameters": {"type": "object", "properties": {
         "role": {"type": "string", "enum": _ROLE_ENUM}, "cluster": {"type": "integer"},
         "is_seed": {"type": "boolean"}, "min_in_deg": {"type": "integer"}, "min_out_deg": {"type": "integer"},
         "min_priority": {"type": "number"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}}},
    {"name": "common_counterparties", "description": "Кто связан сразу с несколькими заданными узлами: "
     "direction=out — куда (напрямую или через посредников) уходят их деньги, например «кто собирает деньги "
     "с этих пятерых»; direction=in — кто платит нескольким из них.",
     "parameters": {"type": "object", "properties": {
         "gids": {"type": "array", "items": {"type": "string"}},
         "direction": {"type": "string", "enum": ["out", "in"]},
         "max_hops": {"type": "integer", "minimum": 1, "maximum": 4}}, "required": ["gids"]}},
]

_FUNCS = {"overview": overview, "get_node": get_node, "neighbors": neighbors, "top_nodes": top_nodes,
          "cluster_summary": cluster_summary, "find_paths": find_paths, "search_nodes": search_nodes,
          "common_counterparties": common_counterparties}


def execute(name: str, args: dict, graph: dict) -> dict:
    fn = _FUNCS.get(name)
    if fn is None:
        return {"error": f"нет инструмента {name}"}
    try:
        return fn(graph, **(args or {}))
    except TypeError as exc:
        return {"error": f"неверные аргументы {name}: {exc}"}
    except Exception as exc:  # инструмент не должен ронять диалог
        return {"error": f"{type(exc).__name__}: {exc}"}


def to_json(result: dict) -> str:
    s = json.dumps(result, ensure_ascii=False, default=str)
    if len(s) > MAX_RESULT_CHARS:
        s = s[:MAX_RESULT_CHARS] + '…"(обрезано)"'
    return s

from collections import Counter, deque
from dataclasses import dataclass
from itertools import pairwise

import networkx as nx
import pandas as pd

from .store import RunData

_GRAPH_NODE_COLUMNS = [
    "gid",
    "x",
    "y",
    "role",
    "cluster_id",
    "priority_score",
    "priority_rank",
    "top_rank",
    "is_seed",
    "truncated",
    "in_kzt",
    "out_kzt",
]


def optional_int(value) -> int | None:
    return None if value is None or pd.isna(value) else int(value)


def graph_nodes(data: RunData, ids: list[int]) -> list[dict]:
    rows = data.nodes.loc[ids, _GRAPH_NODE_COLUMNS]
    return [
        {
            "id": str(r.gid),
            "x": float(r.x),
            "y": float(r.y),
            "role": r.role,
            "cluster_id": int(r.cluster_id),
            "priority_score": float(r.priority_score),
            "priority_rank": int(r.priority_rank),
            "top_rank": optional_int(r.top_rank),
            "is_seed": bool(r.is_seed),
            "truncated": bool(r.truncated),
            "in_kzt": round(float(r.in_kzt), 2),
            "out_kzt": round(float(r.out_kzt), 2),
        }
        for r in rows.itertuples(index=False)
    ]


def edge_payload(u: int, v: int, attrs: dict) -> dict:
    return {
        "source": str(u),
        "target": str(v),
        "sum_kzt": round(attrs["sum_kzt"], 2),
        "n_tx": int(attrs["n_tx"]),
        "first_date": attrs["first_date"],
        "last_date": attrs["last_date"],
    }


def _edges_among(data: RunData, keep: set[int], max_edges: int) -> tuple[list[dict], int]:
    edges = [(u, v, d) for u in keep for v, d in data.G.succ[u].items() if v in keep]
    edges.sort(key=lambda e: (-e[2]["sum_kzt"], e[0], e[1]))
    return [edge_payload(u, v, d) for u, v, d in edges[:max_edges]], len(edges)


def by_priority(data: RunData, ids) -> list[int]:
    rows = data.nodes.loc[list(ids), ["gid", "priority_score"]]
    return list(rows.sort_values(["priority_score", "gid"], ascending=[False, True]).gid)


def subgraph(data: RunData, ordered_ids: list[int], center: int | None, max_nodes: int, max_edges: int) -> dict:
    total_nodes = len(ordered_ids)
    kept = ordered_ids[:max_nodes]
    edges, total_edges = _edges_among(data, set(kept), max_edges)
    reason = "max_nodes" if total_nodes > max_nodes else "max_edges" if total_edges > max_edges else None
    return {
        "center": None if center is None else str(center),
        "nodes": graph_nodes(data, kept),
        "edges": edges,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "truncated": reason is not None,
        "truncation_reason": reason,
    }


@dataclass(frozen=True)
class OverviewFilter:
    roles: list[str] | None = None
    cluster_id: int | None = None
    min_priority: float | None = None
    hide_peripheral: bool = False


def overview(data: RunData, flt: OverviewFilter, max_nodes: int, max_edges: int) -> dict:
    df = data.nodes
    mask = pd.Series(True, index=df.index)
    if flt.roles:
        mask &= df.role.isin(flt.roles)
    if flt.cluster_id is not None:
        mask &= df.cluster_id == flt.cluster_id
    if flt.min_priority is not None:
        mask &= df.priority_score >= flt.min_priority
    if flt.hide_peripheral:
        mask &= df.role != "peripheral"
    selected = df[mask].sort_values(["priority_score", "gid"], ascending=[False, True])
    return subgraph(data, list(selected.gid), None, max_nodes, max_edges)


def hydrate(data: RunData, ids: list[int], include_edges: bool) -> dict:
    known = [g for g in dict.fromkeys(ids) if g in data.G]
    return subgraph(data, known, None, len(known), 50_000 if include_edges else 0)


def bfs(data: RunData, start: int, direction: str, max_depth: int) -> dict[int, int]:
    distance = {start: 0}
    queue = deque([start])
    while queue:
        u = queue.popleft()
        if distance[u] >= max_depth:
            continue
        neighbours = []
        if direction in ("out", "both"):
            neighbours += list(data.G.successors(u))
        if direction in ("in", "both"):
            neighbours += list(data.G.predecessors(u))
        for v in neighbours:
            if v not in distance:
                distance[v] = distance[u] + 1
                queue.append(v)
    return distance


def _closest_first(data: RunData, distance: dict[int, int]) -> list[int]:
    priority = data.nodes.priority_score.loc[list(distance)].to_dict()
    return sorted(distance, key=lambda g: (distance[g], -priority[g], g))


def neighborhood(data: RunData, gid: int, depth: int, direction: str, max_nodes: int, max_edges: int) -> dict:
    return subgraph(data, _closest_first(data, bfs(data, gid, direction, depth)), gid, max_nodes, max_edges)


def trace(data: RunData, gid: int, direction: str, max_hops: int, max_nodes: int) -> dict:
    distance = bfs(data, gid, "in" if direction == "up" else "out", max_hops)
    return subgraph(data, _closest_first(data, distance), gid, max_nodes, 4 * max_nodes)


def shortest_path(data: RunData, source: int, target: int) -> dict:
    for directed, graph in ((True, data.G), (False, data.G.to_undirected(as_view=True))):
        try:
            nodes = nx.shortest_path(graph, source, target)
        except nx.NetworkXNoPath:
            continue
        edges = []
        for a, b in pairwise(nodes):
            u, v = (a, b) if data.G.has_edge(a, b) else (b, a)
            edges.append(edge_payload(u, v, data.G[u][v]))
        return {"found": True, "directed": directed, "nodes": [str(n) for n in nodes], "edges": edges}
    return {"found": False, "directed": True, "nodes": [], "edges": []}


@dataclass(frozen=True)
class Collector:
    gid: int
    coverage: int
    paths: list[list[str]]


def _downstream_tree(data: RunData, source: int, max_hops: int) -> dict[int, int]:
    parent, distance = {source: source}, {source: 0}
    queue = deque([source])
    while queue:
        u = queue.popleft()
        if distance[u] >= max_hops:
            continue
        for v in data.G.successors(u):
            if v not in distance:
                distance[v], parent[v] = distance[u] + 1, u
                queue.append(v)
    return parent


def _path_to(parent: dict[int, int], source: int, node: int) -> list[str]:
    path = [node]
    while path[-1] != source:
        path.append(parent[path[-1]])
    return [str(n) for n in reversed(path)]


def collectors(data: RunData, sources: list[int], max_hops: int = 4, limit: int = 20) -> list[Collector]:
    trees = {s: _downstream_tree(data, s, max_hops) for s in sources}
    coverage = Counter(v for s, tree in trees.items() for v in tree if v != s)
    needed = 2 if len(sources) > 1 else 1
    candidates = [v for v, c in coverage.items() if c >= needed and v not in sources]
    priority = data.nodes.priority_score.loc[candidates].to_dict() if candidates else {}
    candidates.sort(key=lambda v: (-coverage[v], -priority[v], v))
    return [
        Collector(v, coverage[v], [_path_to(trees[s], s, v) for s in sources if v in trees[s]])
        for v in candidates[:limit]
    ]


def resolve(data: RunData, fragment: str, min_len: int = 6) -> list[int]:
    digits = "".join(ch for ch in fragment if ch.isdigit())
    if len(digits) >= 15 and int(digits) in data.G:
        return [int(digits)]
    if len(digits) < min_len:
        return []
    hits = data.gid_text[data.gid_text.str.contains(digits, regex=False)]
    return by_priority(data, hits.index)[:10] if len(hits) else []

"""Кластеры: Louvain на НЕориентированной проекции (оговорено в README), устойчивость, гипотезы, раскладка."""

from __future__ import annotations

import math

import networkx as nx
import numpy as np
import pandas as pd

from moneygraph.config import CFG, ROLE_META, Config


def undirected(G: nx.DiGraph) -> nx.Graph:
    """Проекция без направления: вес пары = сумма переводов в обе стороны."""
    UG = nx.Graph()
    UG.add_nodes_from(G)
    for u, v, d in G.edges(data=True):
        w = d["sum_kzt"] + (UG[u][v]["weight"] if UG.has_edge(u, v) else 0.0)
        UG.add_edge(u, v, weight=w)
    return UG


def _louvain(UG: nx.Graph, seed: int, cfg: Config) -> list[set]:
    core = UG.subgraph([n for n in UG if UG.degree(n) > 0])
    return nx.community.louvain_communities(core, weight="weight", seed=seed, resolution=cfg.louvain_resolution)


def detect(G: nx.DiGraph, cfg: Config = CFG) -> tuple[dict[int, int], dict[int, float], float]:
    """gid → cluster_id. 0 = узлы без единого ребра (изолированные seed). Остальные нумеруются 1..K
    по убыванию внутреннего оборота. Устойчивость = средний лучший Jaccard по cfg.stability_runs прогонам."""
    UG = undirected(G)
    comms = _louvain(UG, cfg.louvain_seed, cfg)

    def internal(c: set) -> float:
        return sum(d["weight"] for _, _, d in UG.subgraph(c).edges(data=True))

    comms = sorted(comms, key=lambda c: (-internal(c), -len(c), min(c)))
    cid = {n: 0 for n in UG if UG.degree(n) == 0}
    for i, c in enumerate(comms, start=1):
        for n in c:
            cid[n] = i
    modularity = nx.community.modularity(UG.subgraph([n for n in UG if UG.degree(n) > 0]), comms, weight="weight")

    runs = [_louvain(UG, s, cfg) for s in range(cfg.stability_runs)]
    stability = {0: 1.0}
    for i, c in enumerate(comms, start=1):
        best = [max(len(c & o) / len(c | o) for o in run) for run in runs]
        stability[i] = round(float(np.mean(best)), 3)
    return cid, stability, float(modularity)


def _separate(xy: np.ndarray, r: np.ndarray, gap: float = 30.0, iters: int = 400) -> np.ndarray:
    """Раздвигает круги кластеров, пока они не перестанут перекрываться (векторизовано)."""
    xy = xy.copy()
    n = len(xy)
    if n < 2:
        return xy
    need = r[:, None] + r[None, :] + gap
    for _ in range(iters):
        d = xy[:, None, :] - xy[None, :, :]
        dist = np.sqrt((d ** 2).sum(-1)) + np.eye(n)
        over = np.clip(need - dist, 0, None) * (1 - np.eye(n))
        if over.max() < 1e-3:
            break
        push = (d / dist[..., None]) * (over[..., None] / 2)
        xy += push.sum(axis=1)
    return xy


def layout(G: nx.DiGraph, cid: dict[int, int], seed: int = 42) -> dict[int, tuple[float, float]]:
    """Раскладка «кластер в кластере». Центры кластеров одной связной части — spring layout графа
    кластеров с последующим раздвиганием кругов (радиус ~ sqrt(размера)); узлы внутри кластера —
    spring layout подграфа. Связные части сети укладываются рядами: крупнейшая сверху,
    изолированные фрагменты и seed без переводов — ниже."""
    UG = undirected(G)
    members: dict[int, list[int]] = {}
    for n, c in cid.items():
        members.setdefault(c, []).append(n)
    radius = {c: 22 * math.sqrt(len(m)) + 12 for c, m in members.items()}
    CG = nx.Graph()
    CG.add_nodes_from(c for c in members if c != 0)
    for u, v in UG.edges():
        a, b = cid[u], cid[v]
        if a != b:
            CG.add_edge(a, b, weight=(CG[a][b]["weight"] + 1) if CG.has_edge(a, b) else 1)

    # 1) центры кластеров внутри каждой связной части
    parts = sorted(nx.connected_components(CG), key=lambda cc: -sum(len(members[c]) for c in cc))
    blocks = []  # (clusters, local centers array, bbox)
    for cc in parts:
        cl = sorted(cc)
        r = np.array([radius[c] for c in cl])
        if len(cl) == 1:
            xy = np.zeros((1, 2))
        else:
            p = nx.spring_layout(CG.subgraph(cl), seed=seed, weight="weight", iterations=300)
            scale = r.sum() / 2
            xy = _separate(np.array([p[c] for c in cl]) * scale, r)
        lo = (xy - r[:, None]).min(0)
        hi = (xy + r[:, None]).max(0)
        blocks.append((cl, xy - lo, hi - lo))

    # 2) раскладываем части рядами (крупнейшая — первой строкой)
    centers: dict[int, np.ndarray] = {}
    row_w = max(blocks[0][2][0], 2400) if blocks else 2400
    x = y = row_h = 0.0
    for cl, xy, (w, h) in blocks:
        if x > 0 and x + w > row_w:
            x, y, row_h = 0.0, y + row_h + 80, 0.0
        for c, pt in zip(cl, xy):
            centers[c] = pt + np.array([x, y])
        x += w + 80
        row_h = max(row_h, h)

    # 3) узлы внутри кластеров
    pos: dict[int, tuple[float, float]] = {}
    for c, m in members.items():
        if c == 0:
            continue
        cx, cy = centers[c]
        rr = radius[c] - 8
        if len(m) == 1:
            pos[m[0]] = (float(cx), float(cy))
            continue
        p = nx.spring_layout(UG.subgraph(m), seed=seed, iterations=80)
        arr = np.array(list(p.values()))
        arr = arr / max(np.abs(arr).max(), 1e-9)
        for n, (px, py) in zip(p.keys(), arr):
            pos[n] = (float(cx + px * rr), float(cy + py * rr))

    # 4) seed без переводов — сеткой внизу
    ymax = max((yy for _, yy in pos.values()), default=0.0)
    for i, n in enumerate(sorted(members.get(0, []))):
        pos[n] = (float((i % 10) * 70), float(ymax + 160 + (i // 10) * 70))
    return {n: (round(x_, 1), round(y_, 1)) for n, (x_, y_) in pos.items()}


def _suffix(g: int) -> str:
    """Короткая метка gid: последние 10 цифр уникальны (первые 8 у всех «10000000»)."""
    return f"…{str(g)[-10:]}"


def _kzt(x: float) -> str:
    from moneygraph.roles import fmt_kzt
    return fmt_kzt(x)


def cluster_table(G: nx.DiGraph, df: pd.DataFrame, stability: dict[int, float]) -> pd.DataFrame:
    """Строка на кластер: размер, seed, оборот внутри/вход/выход, состав ролей, топ-узлы, гипотеза."""
    cl = dict(zip(df.gid, df.cluster_id))
    internal, ext_in, ext_out = {}, {}, {}
    for u, v, d in G.edges(data=True):
        a, b = cl[u], cl[v]
        if a == b:
            internal[a] = internal.get(a, 0.0) + d["sum_kzt"]
        else:
            ext_out[a] = ext_out.get(a, 0.0) + d["sum_kzt"]
            ext_in[b] = ext_in.get(b, 0.0) + d["sum_kzt"]
    giant = max(nx.weakly_connected_components(G), key=len)
    rows = []
    for c, g in df.groupby("cluster_id"):
        g = g.sort_values("priority_score", ascending=False)
        roles = g.role.value_counts().to_dict()
        row = {
            "cluster_id": int(c), "n_nodes": len(g), "n_seed": int(g.is_seed.sum()),
            "sum_kzt_internal": round(internal.get(c, 0.0), 2),
            "top_gids": ";".join(str(x) for x in g.gid.head(5)),
            "sum_kzt_in_external": round(ext_in.get(c, 0.0), 2),
            "sum_kzt_out_external": round(ext_out.get(c, 0.0), 2),
            "roles_mix": ", ".join(f"{ROLE_META[r]['ru']}: {n}" for r, n in roles.items()),
            "stability": stability.get(int(c), 1.0),
            "isolated_fragment": bool(c != 0 and not (set(g.gid) & giant)),
            "max_priority": round(float(g.priority_score.max()), 4),
        }
        row["hypothesis"] = hypothesis(row, g, roles)
        rows.append(row)
    cols = ["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis",
            "roles_mix", "sum_kzt_in_external", "sum_kzt_out_external", "stability", "isolated_fragment", "max_priority"]
    return pd.DataFrame(rows)[cols].sort_values("cluster_id").reset_index(drop=True)


def hypothesis(row: dict, g: pd.DataFrame, roles: dict) -> str:
    """Шаблонная гипотеза о назначении кластера — формулируется как «признаки …», не как утверждение."""
    if row["cluster_id"] == 0:
        return (f"{row['n_nodes']} seed без внутрибанковских переводов ≥5 000 ₸ за июль: вероятны наличные, "
                f"другие банки или суммы ниже порога — запросить иные каналы.")
    parts = []
    coord = g[g.role == "coordinator"]
    cons = g[g.role == "consolidator"]
    distr = g[g.role == "distributor"]
    if len(coord):
        c = coord.iloc[0]
        parts.append(f"признаки управляющего ядра: координатор {_suffix(c.gid)} (от {c.in_deg} плательщиков, "
                     f"{c.out_deg} получателей, {_kzt(c.in_kzt + c.out_kzt)})")
    if len(cons) and (row["n_seed"] >= 2 or not parts):
        c = cons.sort_values("in_deg", ascending=False).iloc[0]
        parts.append(f"признаки консолидации: {_suffix(c.gid)} собирает от {c.in_deg} плательщиков "
                     f"({_kzt(c.in_kzt)}){', в кластере ' + str(row['n_seed']) + ' seed' if row['n_seed'] else ''}")
    if len(distr) and len(parts) < 2:
        d = distr.sort_values("out_deg", ascending=False).iloc[0]
        parts.append(f"веерная раздача: {_suffix(d.gid)} → {d.out_deg} получателей ({_kzt(d.out_kzt)}) — "
                     f"возможны выплаты участникам/обналичивание")
    transit_share = roles.get("transit", 0) / row["n_nodes"]
    if transit_share >= 0.3 and len(parts) < 2:
        parts.append(f"транзитная цепочка: {transit_share:.0%} узлов пропускают деньги дальше — возможен прогон для разрыва следа")
    if not parts:
        parts.append(f"периферия: {roles.get('terminal', 0)} конечных получателей и {roles.get('peripheral', 0)} "
                     f"разовых контактов без признаков дальнейшего движения")
    text = "; ".join(parts)
    text = text[0].upper() + text[1:]
    if row["isolated_fragment"]:
        text = "Изолированный фрагмент (нет связи с основной сетью). " + text
    return text + "."

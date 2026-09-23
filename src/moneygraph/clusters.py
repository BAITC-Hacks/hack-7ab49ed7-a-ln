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


def layout(G: nx.DiGraph, cid: dict[int, int], seed: int = 42) -> dict[int, tuple[float, float]]:
    """Раскладка для экрана: силовой алгоритм Фрухтермана–Рейнгольда (igraph) отдельно для каждой связной
    части сети; связи внутри одного кластера притягивают сильнее (вес 4), поэтому кластеры собираются
    в плотные группы. Крупнейшая часть — слева, остальные и сетка seed без переводов — колонками справа.
    Детерминирована: начальные позиции из генератора с фиксированным seed."""
    import random

    import igraph as ig

    random.seed(seed)  # igraph берёт случайные числа из модуля random
    UG = undirected(G)
    comps = sorted((c for c in nx.connected_components(UG) if len(c) > 1), key=lambda c: (-len(c), min(c)))
    blocks = []
    for k, comp in enumerate(comps):
        comp = sorted(comp)
        li = {v: i for i, v in enumerate(comp)}
        el = [(li[u], li[v]) for u, v in UG.subgraph(comp).edges()]
        w = [4.0 if cid[comp[a]] == cid[comp[b]] else 1.0 for a, b in el]
        rng = np.random.default_rng(seed + k)
        g = ig.Graph(n=len(comp), edges=el)
        p = np.array(g.layout_fruchterman_reingold(seed=rng.uniform(-1, 1, (len(comp), 2)).tolist(), weights=w,
                                                   niter=1500, grid="grid" if len(comp) > 200 else "nogrid").coords)
        p -= p.mean(0)
        p = p / (np.abs(p).max() or 1.0) * (30 * math.sqrt(len(comp)))
        blocks.append((comp, p - p.min(0), p.max(0) - p.min(0)))
    iso = sorted(n for n in UG if UG.degree(n) == 0)
    if iso:  # seed без переводов — отдельный блок-сетка
        grid = np.array([((i % 5) * 45.0, (i // 5) * 45.0) for i in range(len(iso))])
        blocks.append((iso, grid, grid.max(0)))
    # крупнейшая часть слева, остальные — колонками справа от неё (левый нижний угол занят легендой)
    pos: dict[int, tuple[float, float]] = {}
    (comp0, p0, (w0, h0)), rest = blocks[0], blocks[1:]
    for v, (px, py) in zip(comp0, p0):
        pos[v] = (float(px), float(py))
    x, y, col_w = w0 + 140.0, 0.0, 0.0
    for comp, p, (w_, h_) in rest:
        if y > 0 and y + h_ > max(h0, 600.0):
            x, y, col_w = x + col_w + 80.0, 0.0, 0.0
        for v, (px, py) in zip(comp, p):
            pos[v] = (float(x + px), float(y + py))
        y += h_ + 70.0
        col_w = max(col_w, w_)
    return {n: (round(px, 1), round(py, 1)) for n, (px, py) in pos.items()}


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
        parts.append(f"признаки {ROLE_META['consolidator']['typology']}: {_suffix(c.gid)} собирает от {c.in_deg} плательщиков "
                     f"({_kzt(c.in_kzt)}){', в кластере ' + str(row['n_seed']) + ' seed' if row['n_seed'] else ''}")
    if len(distr) and len(parts) < 2:
        d = distr.sort_values("out_deg", ascending=False).iloc[0]
        parts.append(f"признаки {ROLE_META['distributor']['typology']}: {_suffix(d.gid)} → {d.out_deg} получателей ({_kzt(d.out_kzt)}) — "
                     f"возможны выплаты участникам/обналичивание")
    transit_share = roles.get("transit", 0) / row["n_nodes"]
    if transit_share >= 0.3 and len(parts) < 2:
        parts.append(f"признаки {ROLE_META['transit']['typology']}: {transit_share:.0%} узлов пропускают деньги дальше — "
                     f"возможен прогон для разрыва следа")
    if not parts:
        parts.append(f"периферия: {roles.get('terminal', 0)} конечных получателей и {roles.get('peripheral', 0)} "
                     f"разовых контактов без признаков дальнейшего движения")
    text = "; ".join(parts)
    text = text[0].upper() + text[1:]
    if row["isolated_fragment"]:
        text = "Изолированный фрагмент (нет связи с основной сетью). " + text
    return text + "."

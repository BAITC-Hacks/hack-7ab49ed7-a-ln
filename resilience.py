"""Устойчивость сети: что остаётся достижимым от seed после блокировки топ-N узлов (vs случайные N)."""
import networkx as nx
import numpy as np
import pandas as pd

from . import config as C


def _stats(H: nx.DiGraph, seeds: set):
    reach = set()
    for s in seeds:
        if s in H:
            reach |= nx.descendants(H, s)
    reach -= seeds
    flow = sum(d["sum_kzt"] for u, v, d in H.edges(data=True) if v in reach)
    lcc = max((len(c) for c in nx.weakly_connected_components(H)), default=0)
    return len(reach), flow, lcc, nx.number_weakly_connected_components(H)


def resilience(G: nx.DiGraph, f: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    seeds = set(f.index[f.is_seed])
    order = list(f[~f.is_seed].sort_values("priority_score", ascending=False).index)
    base = _stats(G, seeds)
    rng = np.random.default_rng(C.RANDOM_SEED)
    pool = sorted(v for v in G if v not in seeds and G.degree(v) > 0)
    rows = []
    for n in C.RESILIENCE_N:
        H = G.copy()
        H.remove_nodes_from(order[:n])
        top = _stats(H, seeds)
        rnd = []
        for _ in range(C.RESILIENCE_RANDOM_TRIALS):
            H = G.copy()
            H.remove_nodes_from(rng.choice(pool, n, replace=False).tolist())
            rnd.append(_stats(H, seeds))
        rnd = np.mean(rnd, axis=0)
        rows.append(dict(removed_top_n=n,
                         reach_top=round(top[0] / base[0], 4), flow_top=round(top[1] / base[1], 4),
                         lcc_top=top[2], components_top=top[3],
                         reach_random=round(rnd[0] / base[0], 4), flow_random=round(rnd[1] / base[1], 4),
                         lcc_random=round(rnd[2]), components_random=round(rnd[3], 1)))
    return {"reach": base[0], "flow": round(base[1]), "lcc": base[2], "components": base[3]}, pd.DataFrame(rows)

"""Дополнительные выгрузки: циклы, устойчивость сети, запросы на недостающие данные."""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from moneygraph.roles import fmt_kzt


def cycles_table(G: nx.DiGraph, cyc: list[list[int]]) -> pd.DataFrame:
    rows = []
    for c in cyc:
        sums = [G[c[i]][c[(i + 1) % len(c)]]["sum_kzt"] for i in range(len(c))]
        rows.append({"length": len(c), "path": " → ".join(str(x) for x in c + [c[0]]),
                     "min_edge_kzt": round(min(sums), 2), "total_kzt": round(sum(sums), 2)})
    df = pd.DataFrame(rows, columns=["length", "path", "min_edge_kzt", "total_kzt"])
    return df.sort_values(["min_edge_kzt", "length"], ascending=[False, True]).reset_index(drop=True)


def _reach_volume(G: nx.DiGraph, seeds: set[int]) -> float:
    """Оборот на рёбрах, до которых деньги могут дойти от seed по направлению переводов."""
    reach = set()
    for s in seeds:
        if s in G:
            reach |= nx.descendants(G, s) | {s}
    return sum(d["sum_kzt"] for u, _, d in G.edges(data=True) if u in reach)


def resilience(G: nx.DiGraph, df: pd.DataFrame, ns=(5, 10, 20, 50), random_draws: int = 20, seed: int = 42) -> pd.DataFrame:
    """Изъятие топ-N по приоритету против изъятия N случайных узлов (среднее по random_draws)."""
    seeds = set(df.loc[df.is_seed, "gid"])
    base_vol = _reach_volume(G, seeds)
    base_giant = len(max(nx.weakly_connected_components(G), key=len))
    ranked = df.sort_values("rank").gid.tolist()
    rng = np.random.default_rng(seed)
    non_seed = df.loc[~df.is_seed, "gid"].to_numpy()

    def measure(removed: list[int]) -> tuple[float, float, int]:
        H = G.copy()
        H.remove_nodes_from(removed)
        giant = len(max(nx.weakly_connected_components(H), key=len))
        return giant / base_giant, _reach_volume(H, seeds - set(removed)) / base_vol, nx.number_weakly_connected_components(H)

    rows = []
    for n in ns:
        g_top, v_top, c_top = measure(ranked[:n])
        rnd = [measure(list(rng.choice(non_seed, n, replace=False))) for _ in range(random_draws)]
        rows.append({"removed_n": n,
                     "giant_share_top": round(g_top, 3), "giant_share_random": round(float(np.mean([r[0] for r in rnd])), 3),
                     "seed_reach_volume_top": round(v_top, 3),
                     "seed_reach_volume_random": round(float(np.mean([r[1] for r in rnd])), 3),
                     "n_components_top": c_top, "n_components_random": round(float(np.mean([r[2] for r in rnd])), 1)})
    return pd.DataFrame(rows)


def data_requests(df: pd.DataFrame) -> pd.DataFrame:
    """Оценка полноты: какие данные запросить, чтобы закрыть белые пятна, в порядке приоритета узла."""
    rows = []
    for r in df.itertuples(index=False):
        if r.sink_status == "no_data":
            rows.append((r.gid, "Наличные/межбанковские операции и переводы < 5 000 ₸",
                         "seed без внутрибанковских переводов ≥5 000 ₸ за июль", r.priority_score))
        if r.truncated and (r.role in ("consolidator", "transit") or r.in_kzt >= 300_000):
            rows.append((r.gid, "Выписка исходящих за июль–август",
                         f"4-е колено: исходящие не выгружены; получил {fmt_kzt(r.in_kzt)}, p_forward={r.p_forward:.2f}",
                         r.priority_score))
        if r.unseen_inflow_kzt >= 100_000 and not r.truncated:
            rows.append((r.gid, "Входящие переводы от клиентов вне выборки / других банков",
                         f"отправил на {fmt_kzt(r.unseen_inflow_kzt)} больше, чем получил в выборке", r.priority_score))
        if r.sink_status == "truncated_time":
            rows.append((r.gid, "Операции за август 2026",
                         f"основные поступления 30–31 июля ({fmt_kzt(r.in_kzt)}), продолжение не видно", r.priority_score))
    out = pd.DataFrame(rows, columns=["gid", "request", "reason", "node_priority"])
    return out.sort_values("node_priority", ascending=False).reset_index(drop=True)

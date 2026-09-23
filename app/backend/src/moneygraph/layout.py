import math

import networkx as nx
import pandas as pd

from . import config as C
from .texts import FLAG_RU, ROLE_HYPOTHESIS, ROLE_RU, kzt, pct

_GOLDEN_ANGLE = math.pi * (3 - math.sqrt(5))
_CLUSTER_GAP = 2.0


def _cluster_radius(size: int) -> float:
    return 1.2 * math.sqrt(size) + 1.0


def _local_positions(UG: nx.Graph, members: list, radius: float, spread: bool) -> dict:
    if spread:
        return {
            v: (
                math.cos(k * _GOLDEN_ANGLE) * math.sqrt(k + 1) * 0.6,
                math.sin(k * _GOLDEN_ANGLE) * math.sqrt(k + 1) * 0.6,
            )
            for k, v in enumerate(members)
        }
    positions = nx.spring_layout(
        UG.subgraph(members), seed=C.RANDOM_SEED, iterations=60, k=1.5 / math.sqrt(len(members))
    )
    return {v: (x * radius, y * radius) for v, (x, y) in positions.items()}


def _free_center(placed: list[tuple[float, float, float]], radius: float) -> tuple[float, float]:
    if not placed:
        return 0.0, 0.0
    step = 0
    while True:
        distance = 3.0 * math.sqrt(step + 1)
        cx, cy = distance * math.cos(step * _GOLDEN_ANGLE), distance * math.sin(step * _GOLDEN_ANGLE)
        if all(math.hypot(cx - px, cy - py) >= radius + pr + _CLUSTER_GAP for px, py, pr in placed):
            return cx, cy
        step += 1


def layout(G: nx.DiGraph, cluster_id: pd.Series) -> dict:
    # Each cluster is laid out on its own and clusters are packed on a spiral, largest first: a global force
    # layout is too slow for interactive re-runs and hides cluster boundaries.
    UG = G.to_undirected()
    groups = cluster_id.groupby(cluster_id).groups
    positions, placed = {}, []
    for c in sorted(groups, key=lambda c: (-len(groups[c]), c)):
        members = sorted(groups[c])
        radius = _cluster_radius(len(members))
        local = _local_positions(UG, members, radius, spread=(c == 0 or len(members) == 1))
        cx, cy = _free_center(placed, radius)
        placed.append((cx, cy, radius))
        positions.update({v: (round(cx + x, 3), round(cy + y, 3)) for v, (x, y) in local.items()})
    return positions


def _top_counterparties(title: str, edges, g, roles: pd.Series) -> str | None:
    top = sorted(edges, key=lambda e: -e[2]["sum_kzt"])[:3]
    if not top:
        return None
    others = [(e[0] if e[1] == g else e[1], e[2]["sum_kzt"]) for e in top]
    return f"{title}: " + ", ".join(f"…{str(o)[-9:]} ({ROLE_RU[roles[o]].lower()}, {kzt(s)})" for o, s in others)


def node_card(g, r, G: nx.DiGraph, roles: pd.Series) -> str:
    lines = [
        f"Гипотеза: {ROLE_HYPOTHESIS[r.role]} (уверенность {r.role_score:.2f}); "
        f"приоритет {r.priority_score:.2f}, место {int(r['rank'])} из {len(roles)}",
        f"Колено обхода {int(r.depth)}" + (", seed-клиент" if r.is_seed else "") + f"; кластер {int(r.cluster_id)}",
        f"Вход: {kzt(r.in_kzt)} от {int(r.in_deg)} плательщиков ({int(r.in_tx)} оп.); "
        f"выход: {kzt(r.out_kzt)} {int(r.out_deg)} получателям ({int(r.out_tx)} оп.)",
    ]
    if r.traced_in_kzt > 0:
        lines.append(
            f"Прослеживается до seed: {kzt(r.traced_in_kzt)} ({pct(r.traced_share)} входа), "
            f"деньги {int(r.seed_sources)} seed"
        )
    for title, edges in (
        ("Главные плательщики", G.in_edges(g, data=True)),
        ("Главные получатели", G.out_edges(g, data=True)),
    ):
        line = _top_counterparties(title, edges, g, roles)
        if line:
            lines.append(line)
    signals = [FLAG_RU[x] for x in r["flags"] if x in FLAG_RU and x != "seed"]
    if signals:
        lines.append("Сигналы: " + "; ".join(signals))
    lines.append(f"Обоснование роли: {r.evidence}")
    return "\n".join(lines)

import networkx as nx
import pandas as pd

from . import config as C
from .collection import Collection
from .texts import ROLE_HYPOTHESIS, kzt, pct, plural


def louvain(G: nx.DiGraph) -> dict:
    UG = nx.Graph()
    UG.add_nodes_from(G.nodes())
    for u, v, d in G.edges(data=True):
        old = UG.get_edge_data(u, v, {}).get("weight", 0.0)
        UG.add_edge(u, v, weight=old + d["sum_kzt"])
    connected = sorted(v for v in UG if UG.degree(v) > 0)
    comms = (
        nx.community.louvain_communities(
            UG.subgraph(connected), weight="weight", seed=C.RANDOM_SEED, resolution=C.LOUVAIN_RESOLUTION
        )
        if connected
        else []
    )
    comms = sorted(comms, key=lambda c: (-len(c), min(c)))
    cid = {v: 0 for v in UG if UG.degree(v) == 0}
    for i, c in enumerate(comms, start=1):
        for v in c:
            cid[v] = i
    return cid


def cluster_table(G: nx.DiGraph, f: pd.DataFrame, collection: Collection) -> pd.DataFrame:
    internal = {}
    for u, v, d in G.edges(data=True):
        cu, cv = f.at[u, "cluster_id"], f.at[v, "cluster_id"]
        if cu == cv:
            internal[cu] = internal.get(cu, 0.0) + d["sum_kzt"]
    rows = []
    for c, grp in f.groupby("cluster_id"):
        top = grp.sort_values(["priority_score", "in_kzt"], ascending=False)
        roles = grp.role.value_counts()
        rows.append(
            dict(
                cluster_id=int(c),
                n_nodes=len(grp),
                n_seed=int(grp.is_seed.sum()),
                sum_kzt_internal=round(internal.get(c, 0.0), 2),
                top_gids=";".join(str(g) for g in top.index[:5]),
                hypothesis=hypothesis(c, grp, top, internal.get(c, 0.0), collection),
                **{f"n_{r}": int(roles.get(r, 0)) for r in C.ROLES},
                n_truncated=int(grp.truncated.sum()),
                seed_sources_max=int(grp.seed_sources.max()),
                max_priority=round(float(top.priority_score.iloc[0]), 4),
            )
        )
    return pd.DataFrame(rows).sort_values("cluster_id").reset_index(drop=True)


def hypothesis(c, grp, top, internal, collection: Collection) -> str:
    if c == 0:
        return (
            f"{plural(len(grp), 'узел', 'узла', 'узлов')} без переводов ≥{kzt(collection.min_transfer_kzt)} в выгрузке "
            f"({int(grp.is_seed.sum())} из них seed): вероятно, наличные, другие банки или суммы ниже порога — "
            f"нужен запрос вне выгрузки"
        )
    n_seed = int(grp.is_seed.sum())
    hubs = grp[grp.role.isin(["coordinator", "consolidator"])].sort_values("priority_score", ascending=False)
    fans = grp[grp.role == "distributor"].sort_values("out_deg", ascending=False)
    lead = top.index[0]
    lead_txt = f"{ROLE_HYPOTHESIS[top.role.iloc[0]]} {lead}"
    if n_seed >= 2 and len(hubs):
        h = hubs.iloc[0]
        txt = (
            f"Контур сбора: {n_seed} seed; средства сходятся к узлу {hubs.index[0]} "
            f"({ROLE_HYPOTHESIS[h.role]}: {plural(h.in_deg, 'плательщик', 'плательщика', 'плательщиков')}, "
            f"деньги {plural(h.seed_sources, 'seed', 'разных seed', 'разных seed')}); внутр. оборот {kzt(internal)}"
        )
    elif len(fans) and fans.out_deg.iloc[0] >= 20:
        txt = (
            f"Контур распределения: веер от {fans.index[0]} на {int(fans.out_deg.iloc[0])} получателей "
            f"({kzt(fans.out_kzt.iloc[0])}) — возможны выплаты/обналичивание; seed в кластере: {n_seed}"
        )
    elif len(hubs):
        h = hubs.iloc[0]
        txt = (
            f"Локальный узел сбора {hubs.index[0]} ({ROLE_HYPOTHESIS[h.role]}, "
            f"{plural(h.in_deg, 'плательщик', 'плательщика', 'плательщиков')}); seed в кластере: {n_seed}; "
            f"внутр. оборот {kzt(internal)}"
        )
    elif n_seed == 1:
        txt = f"Ветка одного seed-клиента: {len(grp)} узлов, внутр. оборот {kzt(internal)}; ключевой — {lead_txt}"
    elif n_seed >= 2:
        txt = f"Связка {n_seed} seed без выраженного узла сбора; внутр. оборот {kzt(internal)}; ключевой — {lead_txt}"
    else:
        txt = (
            f"Окружение без seed ({len(grp)} узлов, колено {int(grp.depth.min())}–{int(grp.depth.max())}): "
            f"вероятно, бытовые/коммерческие получатели; ключевой — {lead_txt}"
        )
    trunc = grp.truncated.mean()
    if trunc >= 0.3:
        txt += f"; {pct(trunc)} узлов — обрыв {collection.max_depth}-го колена, нужна дозагрузка исходящих"
    return txt

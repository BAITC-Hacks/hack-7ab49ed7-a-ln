import networkx as nx
import pandas as pd

from .. import config as C


def structure_features(G: nx.DiGraph, f: pd.DataFrame, cluster_of: dict) -> pd.DataFrame:
    res = pd.DataFrame(index=f.index)
    comp_id, comp_size = {}, {}
    betweenness = pd.Series(0.0, index=f.index)
    percentile = pd.Series(0.0, index=f.index)
    for cid, members in enumerate(sorted(nx.weakly_connected_components(G), key=lambda c: (-len(c), min(c)))):
        ids = sorted(members)
        for g in ids:
            comp_id[g], comp_size[g] = cid, len(ids)
        if len(ids) > 2:
            # Edge length is 1/amount so that heavy money channels count as short paths.
            bc = pd.Series(
                nx.betweenness_centrality(
                    G.subgraph(ids),
                    k=min(C.BETWEENNESS_SAMPLES, len(ids)),
                    weight="distance",
                    normalized=True,
                    seed=C.RANDOM_SEED,
                )
            )
            betweenness.loc[bc.index] = bc
            percentile.loc[bc.index] = bc.rank(pct=True).where(bc > 0, 0.0)
    res["component_id"] = pd.Series(comp_id)
    res["component_size"] = pd.Series(comp_size)
    res["betweenness"] = betweenness
    res["betweenness_pct"] = percentile.round(4)
    res["partner_clusters"] = [
        len({cluster_of[p] for p in set(G.predecessors(g)) | set(G.successors(g))}) for g in f.index
    ]
    res["pagerank"] = pd.Series(nx.pagerank(G, weight="sum_kzt", max_iter=300, tol=1e-10)).round(6)
    return res

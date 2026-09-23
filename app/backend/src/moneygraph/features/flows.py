from collections import Counter

import networkx as nx
import pandas as pd

from ..collection import Collection


def flow_features(G: nx.DiGraph, nodes: pd.DataFrame, edges: pd.DataFrame, collection: Collection) -> pd.DataFrame:
    f = nodes.set_index("gid")[["depth", "is_seed"]].copy()
    f["in_deg"] = pd.Series(dict(G.in_degree()), dtype="int64")
    f["out_deg"] = pd.Series(dict(G.out_degree()), dtype="int64")
    for side, key in (("in", "dst"), ("out", "src")):
        g = edges.groupby(key)
        f[f"{side}_kzt"] = g.sum_kzt.sum().reindex(f.index, fill_value=0.0)
        f[f"{side}_tx"] = g.n_tx.sum().reindex(f.index, fill_value=0).astype(int)
        f[f"{side}_top_share"] = g.sum_kzt.max().reindex(f.index, fill_value=0.0) / f[f"{side}_kzt"].clip(lower=1)
    f["out_observed"] = f.depth <= collection.expanded_depth
    f["truncated"] = ~f.out_observed
    f["isolated"] = (f.in_deg + f.out_deg) == 0
    # Seeds' inflow is understated by construction and last-hop outflow was never collected,
    # so out/in is only meaningful for expanded non-seed nodes.
    f["ratio_valid"] = (~f.is_seed) & (f.in_kzt > 0) & f.out_observed
    f["pass_ratio"] = (f.out_kzt / f.in_kzt.where(f.in_kzt > 0)).where(f.ratio_valid).round(4)
    seeds = set(nodes.gid[nodes.is_seed])
    f["seed_payers"] = [sum(p in seeds for p in G.predecessors(g)) for g in f.index]
    f["pays_seeds"] = [sum(s in seeds for s in G.successors(g)) for g in f.index]
    reach = Counter()
    for s in sorted(seeds):
        reach.update(nx.descendants(G, s))
    f["reachable_seeds"] = pd.Series(reach).reindex(f.index, fill_value=0).astype(int)
    return f

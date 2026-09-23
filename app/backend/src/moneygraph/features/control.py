from collections import defaultdict

import networkx as nx
import pandas as pd

_ROOT = -1


def dominator_control(G: nx.DiGraph, nodes: pd.DataFrame) -> pd.DataFrame:
    # A virtual root feeding every seed turns "cut off from all seeds if v is blocked" into v's
    # dominator subtree (Lengauer–Tarjan, near-linear).
    H = G.copy()
    H.add_edges_from((_ROOT, int(s)) for s in nodes.gid[nodes.is_seed])
    children = defaultdict(list)
    for v, d in nx.immediate_dominators(H, _ROOT).items():
        if v != d:
            children[d].append(v)
    in_kzt = dict(G.in_degree(weight="sum_kzt"))
    tree = nx.DiGraph([(d, v) for d, vs in children.items() for v in vs])
    size, money = {}, {}
    for v in reversed(list(nx.dfs_preorder_nodes(tree, _ROOT))):
        size[v] = sum(size[c] + 1 for c in children.get(v, []))
        money[v] = sum(money[c] + in_kzt.get(c, 0.0) for c in children.get(v, []))
    res = pd.DataFrame(index=pd.Index(nodes.gid.values, name="gid"))
    res["control_nodes"] = [size.get(v, 0) for v in res.index]
    res["control_kzt"] = [round(money.get(v, 0.0)) for v in res.index]
    return res

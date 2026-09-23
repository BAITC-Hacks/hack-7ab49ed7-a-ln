from collections import Counter

import networkx as nx
import pandas as pd

from .. import config as C


def _chronological_return(cycle: list, edge_days: dict) -> bool:
    for shift in range(len(cycle)):
        route = cycle[shift:] + cycle[:shift]
        days = [sorted(edge_days[(route[i], route[(i + 1) % len(route)])]) for i in range(len(route))]
        for first in days[0]:
            prev = first
            for options in days[1:]:
                later = [d for d in options if prev < d <= first + C.CYCLE_RETURN_DAYS]
                if not later:
                    break
                prev = later[0]
            else:
                return True
    return False


def cycle_features(G: nx.DiGraph, f: pd.DataFrame, edge_days: dict) -> tuple[pd.DataFrame, dict]:
    res = pd.DataFrame(index=f.index)
    res["scc_size"] = pd.Series({g: len(members) for members in nx.strongly_connected_components(G) for g in members})
    short, dated = Counter(), Counter()
    n_short = n_dated = 0
    for cycle in nx.simple_cycles(G, length_bound=C.CYCLE_MAX_LENGTH):
        if len(cycle) < 2:
            continue
        n_short += 1
        short.update(cycle)
        if _chronological_return(cycle, edge_days):
            n_dated += 1
            dated.update(cycle)
    res["short_cycles"] = pd.Series(short).reindex(f.index, fill_value=0).astype(int)
    res["dated_returns"] = pd.Series(dated).reindex(f.index, fill_value=0).astype(int)
    res["cycle"] = res.scc_size > 1
    res["dated_return"] = res.dated_returns > 0
    return res, {"short_cycles": n_short, "dated_cycles": n_dated}

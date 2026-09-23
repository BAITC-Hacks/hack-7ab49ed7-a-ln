import numpy as np
import pandas as pd

from .. import config as C
from ..collection import Collection


def trace_seed_money(
    nodes: pd.DataFrame, tx: pd.DataFrame, edges: pd.DataFrame, collection: Collection
) -> pd.DataFrame:
    # Chronological pro-rata haircut: each transfer carries its share (amount / visible balance) of the
    # sender's seed-labelled pool; anything sent beyond the visible balance is unlabelled outside money.
    # A seed's unlabelled outflow is labelled with the seed itself because its inflow is outside the extract.
    # Same-day transfers are ordered by crawl hop, which follows the direction money moves.
    gids = nodes.gid.values
    index = {g: i for i, g in enumerate(gids)}
    n = len(gids)
    is_seed = nodes.is_seed.values
    seed_rows = np.where(is_seed)[0]
    label = {int(s): k for k, s in enumerate(seed_rows)}
    hop = {(r.src, r.dst): int(r.depth) for r in edges.itertuples(index=False)}
    ordered = tx.assign(edge_depth=[hop[(s, d)] for s, d in zip(tx.src, tx.dst, strict=True)]).sort_values(
        ["day", "edge_depth", "src", "dst", "sum_kzt"], kind="mergesort"
    )
    pool = np.zeros((n, len(seed_rows)))
    received = np.zeros((n, len(seed_rows)))
    balance = np.zeros(n)
    inflow = np.zeros(n)
    for s, d, amount in zip(
        ordered.src.map(index).values, ordered.dst.map(index).values, ordered.sum_kzt.values, strict=True
    ):
        moved = pool[s] * (amount / max(balance[s], amount))
        pool[s] -= moved
        if is_seed[s]:
            moved = moved.copy()
            moved[label[s]] += amount - moved.sum()
        pool[d] += moved
        received[d] += moved
        balance[s] = max(balance[s] - amount, 0.0)
        balance[d] += amount
        inflow[d] += amount
    return _summarize(gids, seed_rows, received, inflow, collection)


def _summarize(gids, seed_rows, received, inflow, collection: Collection) -> pd.DataFrame:
    n = len(gids)
    traced = received.sum(1)
    shares = np.divide(received, traced[:, None], out=np.zeros_like(received), where=traced[:, None] > 0)
    main = np.argmax(received, axis=1)
    res = pd.DataFrame(index=pd.Index(gids, name="gid"))
    res["traced_in_kzt"] = traced.round(0)
    res["traced_share"] = np.divide(traced, inflow, out=np.zeros(n), where=inflow > 0).clip(0, 1).round(4)
    res["seed_sources"] = (received >= collection.min_transfer_kzt).sum(1)
    res["seed_mix_eff"] = np.where(
        traced >= C.SEED_MIX_MIN_KZT, 1.0 / np.maximum((shares**2).sum(1), 1e-12), 0.0
    ).round(2)
    res["main_seed"] = np.where(traced > 0, gids[seed_rows[main]], 0)
    res["main_seed_share"] = np.where(traced > 0, shares[np.arange(n), main], 0.0).round(4)
    return res

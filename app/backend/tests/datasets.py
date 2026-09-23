from collections import deque
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

START = date(2026, 7, 1)


def build_frames(seeds: list[int], transfers: list[tuple[int, int, int, float]], extra_nodes: tuple[int, ...] = ()):
    tx = pd.DataFrame(transfers, columns=["src", "dst", "day", "sum_kzt"])
    depth = {s: 0 for s in seeds}
    queue = deque(seeds)
    successors = tx.groupby("src").dst.apply(list).to_dict()
    while queue:
        node = queue.popleft()
        for nxt in successors.get(node, []):
            if nxt not in depth:
                depth[nxt] = depth[node] + 1
                queue.append(nxt)
    for node in extra_nodes:
        depth.setdefault(node, 0)
    nodes = pd.DataFrame(
        {"gid": list(depth), "depth": list(depth.values()), "is_seed": [g in seeds or g in extra_nodes for g in depth]}
    )
    edges = tx.groupby(["src", "dst"]).agg(sum_kzt=("sum_kzt", "sum"), n_tx=("sum_kzt", "size")).reset_index()
    edges["depth"] = edges.src.map(depth) + 1
    tx = tx.assign(date=[START + timedelta(days=d) for d in tx.day])[["src", "dst", "date", "sum_kzt"]]
    for df, cols in ((nodes, ["gid", "depth"]), (edges, ["src", "dst", "n_tx", "depth"]), (tx, ["src", "dst"])):
        for c in cols:
            df[c] = df[c].astype("int64")
    return edges, nodes, tx


def write_dataset(directory: Path, edges: pd.DataFrame, nodes: pd.DataFrame, tx: pd.DataFrame) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    edges.to_parquet(directory / "edges.parquet", index=False)
    nodes.to_parquet(directory / "nodes.parquet", index=False)
    tx.to_parquet(directory / "transactions.parquet", index=False)
    return directory


SEEDS = [101, 102, 103, 104, 105, 106]
CONSOLIDATOR, DISTRIBUTOR, TRANSIT, TERMINAL, RELAY, LAST_HOP = 201, 202, 301, 401, 302, 402
FAN_OUT = list(range(310, 322))
ISOLATED_SEED = 999


def crafted_transfers() -> list[tuple[int, int, int, float]]:
    transfers = [(seed, CONSOLIDATOR, 2, 60_000.0) for seed in SEEDS[:5]]
    transfers += [(CONSOLIDATOR, TRANSIT, 3, 100_000.0)]
    transfers += [(TRANSIT, TERMINAL, 4, 95_000.0)]
    transfers += [(SEEDS[5], DISTRIBUTOR, 1, 400_000.0)]
    transfers += [(DISTRIBUTOR, target, 2, 25_000.0) for target in FAN_OUT]
    transfers += [(FAN_OUT[0], RELAY, 3, 20_000.0), (RELAY, LAST_HOP, 5, 18_000.0)]
    return transfers


def crafted_frames():
    return build_frames(SEEDS, crafted_transfers(), extra_nodes=(ISOLATED_SEED,))

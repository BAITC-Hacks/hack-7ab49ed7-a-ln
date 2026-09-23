import json
import logging
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import pandas as pd

log = logging.getLogger(__name__)

_BYTES_PER_EDGE = 600
_BYTES_PER_NODE = 300


@dataclass
class RunData:
    run_id: str
    nodes: pd.DataFrame
    edges: pd.DataFrame
    tx: pd.DataFrame
    meta: dict
    clusters: list[dict]
    top: list[dict]
    G: nx.DiGraph
    gid_text: pd.Series
    size_bytes: int


def load_run(run_id: str, current: Path) -> RunData:
    api = current.resolve() / "api"
    nodes = pd.read_parquet(api / "nodes.parquet").set_index("gid", drop=False)
    nodes.index.name = None
    edges = pd.read_parquet(api / "edges.parquet")
    tx = pd.read_parquet(api / "tx.parquet")
    G = nx.DiGraph()
    G.add_nodes_from(int(g) for g in nodes.index)
    for e in edges.itertuples(index=False):
        G.add_edge(
            int(e.src),
            int(e.dst),
            sum_kzt=float(e.sum_kzt),
            n_tx=int(e.n_tx),
            first_date=e.first_date,
            last_date=e.last_date,
        )
    size = (
        int(
            nodes.memory_usage(deep=True).sum() + edges.memory_usage(deep=True).sum() + tx.memory_usage(deep=True).sum()
        )
        + _BYTES_PER_EDGE * G.number_of_edges()
        + _BYTES_PER_NODE * G.number_of_nodes()
    )
    return RunData(
        run_id=run_id,
        nodes=nodes,
        edges=edges,
        tx=tx,
        meta=json.loads((api / "meta.json").read_text()),
        clusters=json.loads((api / "clusters.json").read_text()),
        top=json.loads((api / "top.json").read_text()),
        G=G,
        gid_text=pd.Series(nodes.index.astype(str), index=nodes.index),
        size_bytes=size,
    )


class _Load:
    def __init__(self, generation: int):
        self.generation = generation
        self.done = threading.Event()
        self.data: RunData | None = None
        self.error: BaseException | None = None


class RunCache:
    # One load per published attempt: concurrent misses share the first loader's result (cached or not, success or
    # error) instead of each decoding the run again. Keys include the resolved `current` target, so a republished run
    # is reloaded automatically, and a per-run generation stops a load that raced with invalidation from being cached.
    def __init__(self, budget_mb: int, loader: Callable[[str, Path], RunData] = load_run):
        self._budget = budget_mb * 1024 * 1024
        self._loader = loader
        self._items: OrderedDict[tuple[str, str], RunData] = OrderedDict()
        self._loading: dict[tuple[str, str], _Load] = {}
        self._generation: dict[str, int] = {}
        self._lock = threading.Lock()

    def get(self, run_id: str, current: Path) -> RunData:
        key = (run_id, os.path.realpath(current))
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
            load = self._loading.get(key)
            leader = load is None
            if leader:
                load = self._loading[key] = _Load(self._generation.get(run_id, 0))
        if not leader:
            return self._await(load)
        try:
            load.data = self._loader(run_id, current)
            with self._lock:
                if self._generation.get(run_id, 0) == load.generation:
                    self._store(key, load.data)
        except BaseException as e:
            load.error = e
            raise
        finally:
            with self._lock:
                self._loading.pop(key, None)
            load.done.set()
        return load.data

    @staticmethod
    def _await(load: _Load) -> RunData:
        load.done.wait()
        if load.error is not None:
            raise load.error
        return load.data

    def _store(self, key: tuple[str, str], data: RunData) -> None:
        for stale in [k for k in self._items if k[0] == key[0]]:
            del self._items[stale]
        if data.size_bytes > self._budget:
            log.warning("run %s (%d MB) exceeds the cache budget; serving it uncached", key[0], data.size_bytes >> 20)
            return
        self._items[key] = data
        while sum(d.size_bytes for d in self._items.values()) > self._budget:
            self._items.popitem(last=False)

    def invalidate(self, run_id: str) -> None:
        with self._lock:
            self._generation[run_id] = self._generation.get(run_id, 0) + 1
            for key in [k for k in self._items if k[0] == run_id]:
                del self._items[key]

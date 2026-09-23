"""Загрузка данных, проверки консистентности и сборка графа (порт стартового кода организаторов)."""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd


def load(data_dir: Path):
    edges = pd.read_parquet(data_dir / "edges.parquet")
    nodes = pd.read_parquet(data_dir / "nodes.parquet")
    tx = pd.read_parquet(data_dir / "transactions.parquet")
    tx["date"] = pd.to_datetime(tx["date"])
    for df, cols in ((edges, ["src", "dst"]), (nodes, ["gid"]), (tx, ["src", "dst"])):
        for c in cols:
            df[c] = df[c].astype("int64")
    return edges, nodes, tx


def sanity_check(edges: pd.DataFrame, nodes: pd.DataFrame, tx: pd.DataFrame, verbose: bool = True) -> set[int]:
    """Проверки до построения модели. Возвращает множество узлов без единого ребра."""
    agg = tx.groupby(["src", "dst"]).agg(s=("sum_kzt", "sum"), c=("sum_kzt", "size")).reset_index()
    m = edges.merge(agg, on=["src", "dst"], how="outer", indicator=True)
    assert (m["_merge"] == "both").all(), "edges и transactions не сходятся по парам"
    assert np.allclose(m["s"], m["sum_kzt"]) and (m["c"] == m["n_tx"]).all(), "суммы/количества рёбер не сходятся"
    assert nodes["gid"].is_unique, "дубликаты gid в nodes.parquet"
    in_edges = set(edges["src"]) | set(edges["dst"])
    assert in_edges <= set(nodes["gid"]), "в рёбрах есть gid, которых нет в nodes.parquet"
    orphans = set(nodes["gid"]) - in_edges
    if verbose:
        print(f"  узлов {len(nodes)}, рёбер {len(edges)}, транзакций {len(tx)}, seed {int(nodes.is_seed.sum())}")
        print(f"  оборот {edges.sum_kzt.sum():,.0f} KZT, период {tx.date.min().date()} — {tx.date.max().date()}")
        print(f"  edges == transactions: OK; узлов без рёбер: {len(orphans)}")
    return orphans


def build_graph(edges: pd.DataFrame, nodes: pd.DataFrame) -> nx.DiGraph:
    """Направленный граф: вес sum_kzt, n_tx — число переводов. Изолированные узлы тоже добавляются."""
    G = nx.DiGraph()
    G.add_nodes_from(nodes["gid"].tolist())
    for r in edges.itertuples(index=False):
        G.add_edge(int(r.src), int(r.dst), sum_kzt=float(r.sum_kzt), n_tx=int(r.n_tx), depth=int(r.depth))
    return G


def basic_features(G: nx.DiGraph, nodes: pd.DataFrame) -> pd.DataFrame:
    """Базовые метрики стартового кода: степени, обороты, число переводов, PageRank, pass_through."""
    df = nodes[["gid", "depth", "is_seed"]].copy()
    df["depth"] = df["depth"].astype(int)
    df["is_seed"] = df["is_seed"].astype(bool)
    df["in_deg"] = df.gid.map(dict(G.in_degree())).fillna(0).astype(int)
    df["out_deg"] = df.gid.map(dict(G.out_degree())).fillna(0).astype(int)
    df["in_kzt"] = df.gid.map(dict(G.in_degree(weight="sum_kzt"))).fillna(0.0).astype(float)
    df["out_kzt"] = df.gid.map(dict(G.out_degree(weight="sum_kzt"))).fillna(0.0).astype(float)
    df["in_tx"] = df.gid.map(dict(G.in_degree(weight="n_tx"))).fillna(0).astype(int)
    df["out_tx"] = df.gid.map(dict(G.out_degree(weight="n_tx"))).fillna(0).astype(int)
    df["pagerank"] = df.gid.map(nx.pagerank(G, weight="sum_kzt")).fillna(0.0)
    df["pass_through"] = np.where(df.in_kzt > 0, df.out_kzt / df.in_kzt.where(df.in_kzt > 0), np.nan)
    df["truncated_by_depth"] = (df.depth == 4) & (df.out_deg == 0)
    return df

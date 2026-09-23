"""Полный прогон: parquet → признаки → роли → кластеры → приоритеты → выгрузки."""

from __future__ import annotations

import time
from pathlib import Path

from moneygraph.load import basic_features, build_graph, load, sanity_check


def run(data_dir: Path, out_dir: Path) -> None:
    t0 = time.time()
    print("== Проверка данных")
    edges, nodes, tx = load(data_dir)
    sanity_check(edges, nodes, tx)
    G = build_graph(edges, nodes)
    df = basic_features(G, nodes)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"== Готово за {time.time() - t0:.1f} с; узлов с метриками: {len(df)}")

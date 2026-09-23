#!/usr/bin/env python3
"""
Граф денег — одна команда от сырых parquet до всех выгрузок и экрана просмотра.

    uv run run.py                       # data/ → out/*.csv + viewer/graph_data.js
    uv run run.py --data path/to/data --out out --no-viewer
"""
import argparse
import sys
from pathlib import Path

from moneygraph.pipeline import run


def main():
    ap = argparse.ArgumentParser(description="Граф денег: роли, кластеры и приоритеты узлов")
    ap.add_argument("--data", default="data", help="папка с edges/nodes/transactions.parquet")
    ap.add_argument("--out", default="out", help="куда писать CSV и отчёт")
    ap.add_argument("--viewer", default="viewer", help="папка экрана просмотра (пишется graph_data.js)")
    ap.add_argument("--no-viewer", action="store_true", help="не обновлять данные экрана просмотра")
    a = ap.parse_args()
    stats = run(Path(a.data), Path(a.out), None if a.no_viewer else Path(a.viewer))
    print(f"\nГотово за {stats['runtime_s']} с. Роли: {stats['roles']}. Кластеров: {stats['n_clusters']}.")
    print(f"Выгрузки: {a.out}/nodes_roles.csv, clusters.csv, top_nodes.csv (+ features, resilience, data_requests, "
          f"run_report.md)")
    if not a.no_viewer:
        if (Path(a.viewer) / "index.html").exists():
            print(f"Экран просмотра: откройте {a.viewer}/index.html в браузере")
        else:
            print(f"ВНИМАНИЕ: {a.viewer}/index.html не найден — скопируйте папку viewer/ из репозитория "
                  f"(данные для неё уже записаны в {a.viewer}/graph_data.js)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

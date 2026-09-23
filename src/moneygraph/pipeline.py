"""Полный прогон: parquet → признаки → кластеры → роли → приоритеты → выгрузки → экран просмотра."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from moneygraph import clusters as clmod
from moneygraph import extras, features, priority, roles, temporal
from moneygraph.config import CFG, ROLE_META, ROLES
from moneygraph.export import graph_json, write_all, write_graph_json
from moneygraph.load import basic_features, build_graph, load, sanity_check
from moneygraph.validate import check


def run(data_dir: Path, out_dir: Path, cfg=CFG) -> dict:
    t0 = time.time()
    print("== 1. Данные")
    edges, nodes, tx = load(data_dir)
    sanity_check(edges, nodes, tx)
    G = build_graph(edges, nodes)

    print("== 2. Признаки")
    df = basic_features(G, nodes)
    df = features.structural(G, df)
    tab, fwd_report = features.forward_table(df, cfg)
    df = features.add_p_forward(df, tab, fwd_report["base_rate"])
    df = features.add_temporal(df, tx, cfg)
    df = features.add_anomaly(df, cfg)
    cyc = features.cycles(G, cfg)
    routes = temporal.repeated_routes(tx, cfg)
    cycle_nodes = {n for c in cyc for n in c}
    route_nodes = set(routes.b) if len(routes) else set()
    print(f"  p_forward: база {fwd_report['base_rate']}, по коленам {fwd_report['rate_by_depth']}, "
          f"бэктест AUC (1–2 → 3) = {fwd_report['backtest_auc_depth3']}")
    print(f"  циклов ≤{cfg.cycle_max_len}: {len(cyc)}, устойчивых маршрутов A→B→C: {len(routes)}")

    print("== 3. Кластеры (Louvain на неориентированной проекции)")
    cid, stability, modularity = clmod.detect(G, cfg)
    df["cluster_id"] = df.gid.map(cid).astype(int)

    print("== 4. Роли и приоритеты")
    df = roles.assign(G, df, cfg)
    df["flags"] = priority.flags(df, cycle_nodes, route_nodes, cfg)
    df = priority.score(df, cfg)
    ctab = clmod.cluster_table(G, df, stability)
    hyp = dict(zip(ctab.cluster_id, ctab.hypothesis))
    sens = priority.sensitivity(df, cfg)

    top = df.sort_values("rank").head(cfg.top_n).copy()
    top["why"] = [priority.why(r, hyp[r.cluster_id]) for r in top.itertuples(index=False)]
    top["new_lead"] = ~top.is_seed
    top = top[["rank", "gid", "role", "priority_score", "why", "role_score", "is_seed", "new_lead", "cluster_id", "evidence"]]

    print("== 5. Дополнительно: циклы, маршруты, устойчивость, полнота данных")
    extra = {
        "cycles": extras.cycles_table(G, cyc),
        "routes": routes,
        "resilience": extras.resilience(G, df),
        "data_requests": extras.data_requests(df),
        "p_forward_table": pd.DataFrame(fwd_report["table"]),
    }

    print("== 6. Выгрузки")
    write_all(out_dir, df, ctab, top, extra)
    summary = {
        "runtime_sec": None,
        "role_counts": {r: int((df.role == r).sum()) for r in ROLES},
        "n_clusters": int(ctab.cluster_id.nunique()),
        "clusters_with_multiple_seeds": int((ctab.n_seed > 1).sum()),
        "modularity": round(modularity, 3),
        "new_leads_in_top20": int((~df.nsmallest(20, "rank").is_seed).sum()),
        "priority_sensitivity_top20": sens,
        "p_forward": {k: v for k, v in fwd_report.items() if k != "table"},
        "n_cycles": len(cyc), "n_routes": int(len(routes)),
        "transit_ratio_0_8_1_2": int(((df.in_kzt > 0) & (df.out_kzt / df.in_kzt.where(df.in_kzt > 0)).between(0.8, 1.2)).sum()),
    }
    graph = graph_json(G, df, ctab, top, clmod.layout(G, cid), temporal.edge_tx_lists(tx), {"summary": summary})
    write_graph_json(graph, out_dir / "graph.json")
    try:
        from moneygraph.viewer import write_viewer
        write_viewer(graph, out_dir / "viewer.html")
        print(f"  экран просмотра: {out_dir / 'viewer.html'}")
    except (ImportError, FileNotFoundError) as e:
        print(f"  (экран просмотра не собран: {e})")

    errs = check(out_dir, data_dir)
    summary["runtime_sec"] = round(time.time() - t0, 1)
    (out_dir / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== Итог")
    for r in ROLES:
        print(f"  {ROLE_META[r]['ru']:<22}{summary['role_counts'][r]:>6}")
    print(f"  кластеров: {summary['n_clusters']} (с >1 seed: {summary['clusters_with_multiple_seeds']}), "
          f"модулярность {summary['modularity']}")
    print(f"  новых (не seed) в топ-20: {summary['new_leads_in_top20']}; устойчивость топ-20 к весам ±20%: "
          f"мин. {sens['min_overlap']:.0%}")
    print(f"  выгрузки: {out_dir}/nodes_roles.csv, clusters.csv, top_nodes.csv (+ graph.json, extras)")
    if errs:
        raise SystemExit("ПРОВЕРКА СХЕМЫ НЕ ПРОЙДЕНА:\n  " + "\n  ".join(errs))
    print(f"  проверка схемы ТЗ: OK; время {summary['runtime_sec']} с")
    return summary

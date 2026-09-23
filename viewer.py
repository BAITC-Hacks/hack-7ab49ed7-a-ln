"""
Экспорт данных для экрана просмотра: viewer/graph_data.js (схема — docs/CONTRACT.md §5).
Данные подключаются как <script>, поэтому страница открывается прямо с диска (file://), без сервера.
Раскладка детерминированная: каждый кластер раскладывается отдельно, кластеры — по спирали.
"""
import json
import math
from datetime import datetime
from pathlib import Path

import networkx as nx
import pandas as pd

from . import config as C
from .texts import FLAG_RU, ROLE_COLORS, ROLE_HYPOTHESIS, ROLE_RU, kzt, pct

EXTRA = ["traced_in_kzt", "traced_share", "seed_sources", "main_seed", "control_nodes", "control_kzt",
         "betweenness_pct", "partner_clusters", "fast_2d_share", "strict_fast_2d_share", "sync_max_payers",
         "repeated_routes", "dated_returns", "p_continue", "pass_ratio", "followup_days", "hop_z",
         "reachable_seeds"]


def layout(G: nx.DiGraph, cluster_id: pd.Series) -> dict:
    UG = G.to_undirected()
    groups = cluster_id.groupby(cluster_id).groups
    order = sorted(groups, key=lambda c: (-len(groups[c]), c))
    golden = math.pi * (3 - math.sqrt(5))
    pos, placed = {}, []
    for c in order:
        members = sorted(groups[c])
        r = 1.2 * math.sqrt(len(members)) + 1.0
        if c == 0 or len(members) == 1:
            local = {v: (math.cos(k * golden) * math.sqrt(k + 1) * 0.6, math.sin(k * golden) * math.sqrt(k + 1) * 0.6)
                     for k, v in enumerate(members)}
        else:
            p = nx.spring_layout(UG.subgraph(members), seed=C.RANDOM_SEED, iterations=60,
                                 k=1.5 / math.sqrt(len(members)))
            local = {v: (x * r, y * r) for v, (x, y) in p.items()}
        if not placed:
            cx = cy = 0.0
        else:
            t = 0
            while True:
                d = 3.0 * math.sqrt(t + 1)
                cx, cy = d * math.cos(t * golden), d * math.sin(t * golden)
                if all(math.hypot(cx - px, cy - py) >= r + pr + 2.0 for px, py, pr in placed):
                    break
                t += 1
        placed.append((cx, cy, r))
        for v, (x, y) in local.items():
            pos[v] = (round(cx + x, 3), round(cy + y, 3))
    return pos


def card(g, r, G: nx.DiGraph, roles: pd.Series) -> str:
    """Автокарточка узла: роль, потоки, главные контрагенты, флаги, на что обратить внимание."""
    L = [f"Гипотеза: {ROLE_HYPOTHESIS[r.role]} (уверенность {r.role_score:.2f}); "
         f"приоритет {r.priority_score:.2f}, место {int(r['rank'])} из {C.EXPECTED_NODES}",
         f"Колено обхода {int(r.depth)}" + (", seed-клиент" if r.is_seed else "") + f"; кластер {int(r.cluster_id)}",
         f"Вход: {kzt(r.in_kzt)} от {int(r.in_deg)} плательщиков ({int(r.in_tx)} оп.); "
         f"выход: {kzt(r.out_kzt)} {int(r.out_deg)} получателям ({int(r.out_tx)} оп.)"]
    if r.traced_in_kzt > 0:
        L.append(f"Прослеживается до seed: {kzt(r.traced_in_kzt)} ({pct(r.traced_share)} входа), деньги {int(r.seed_sources)} seed")
    for title, nbrs in (("Главные плательщики", G.in_edges(g, data=True)), ("Главные получатели", G.out_edges(g, data=True))):
        top = sorted(nbrs, key=lambda e: -e[2]["sum_kzt"])[:3]
        if top:
            other = [(e[0] if e[1] == g else e[1], e[2]["sum_kzt"]) for e in top]
            L.append(f"{title}: " + ", ".join(f"…{str(o)[-9:]} ({ROLE_RU[roles[o]].lower()}, {kzt(s)})" for o, s in other))
    fl = [FLAG_RU[x] for x in r["flags"] if x in FLAG_RU and x != "seed"]
    if fl:
        L.append("Сигналы: " + "; ".join(fl))
    L.append(f"Обоснование роли: {r.evidence}")
    return "\n".join(L)


def export_viewer(G, f, clusters, top_df, edges, tx, viewer_dir: Path, meta_extra: dict | None = None) -> Path:
    pos = layout(G, f.cluster_id)
    top_rank = {g: i + 1 for i, g in enumerate(top_df.gid)}
    nodes = []
    for g, r in f.iterrows():
        n = {"id": str(g), "role": r.role, "role_score": float(r.role_score), "cluster_id": int(r.cluster_id),
             "priority_score": float(r.priority_score), "rank": top_rank.get(g), "priority_rank": int(r["rank"]),
             "evidence": r.evidence, "flags": list(r["flags"]), "depth": int(r.depth), "is_seed": bool(r.is_seed),
             "in_deg": int(r.in_deg), "out_deg": int(r.out_deg), "in_kzt": float(r.in_kzt),
             "out_kzt": float(r.out_kzt), "in_tx": int(r.in_tx), "out_tx": int(r.out_tx),
             "x": pos[g][0], "y": pos[g][1]}
        for c in EXTRA:
            v = r[c]
            if pd.isna(v) or (c == "p_continue" and not r.truncated):
                n[c] = None
            elif c == "main_seed":
                n[c] = str(int(v)) if int(v) else None
            elif isinstance(v, float):
                n[c] = round(v, 4)
            else:
                n[c] = int(v)
        n["card"] = card(g, r, G, f.role)
        nodes.append(n)

    day = tx.date.dt.strftime("%Y-%m-%d")
    edge_list = []
    for (s, d), grp in tx.assign(d_str=day).groupby(["src", "dst"], sort=True):
        e = G[s][d]
        edge_list.append({"source": str(s), "target": str(d), "sum_kzt": round(e["sum_kzt"], 2),
                          "n_tx": int(len(grp)), "depth": e["depth"],
                          "first_date": grp.d_str.min(), "last_date": grp.d_str.max(),
                          "tx": [[a, round(float(b), 2)] for a, b in zip(grp.d_str, grp.sum_kzt)]})
    cl = [{"cluster_id": int(r.cluster_id), "n_nodes": int(r.n_nodes), "n_seed": int(r.n_seed),
           "sum_kzt_internal": float(r.sum_kzt_internal),
           "top_gids": [x for x in str(r.top_gids).split(";") if x],
           "hypothesis": r.hypothesis, "max_priority": float(r.max_priority)} for r in clusters.itertuples(index=False)]
    tp = [{"rank": int(r.rank), "gid": str(r.gid), "role": r.role, "priority_score": float(r.priority_score),
           "why": r.why} for r in top_df.itertuples(index=False)]
    rules = (meta_extra or {}).get("role_rules", {})
    meta = {"generated_at": datetime.now().isoformat(timespec="seconds"),
            "period": [C.OBSERVATION_START, C.OBSERVATION_END], "n_nodes": len(nodes), "n_edges": len(edge_list),
            "n_tx": int(len(tx)), "total_kzt": round(float(edges.sum_kzt.sum()), 2),
            "roles": {k: {"label": ROLE_RU[k], "color": ROLE_COLORS[k], "rule": rules.get(k, "")} for k in C.ROLES},
            "flags": FLAG_RU}
    for k, v in (meta_extra or {}).items():
        if k != "role_rules":
            meta[k] = v
    data = {"meta": meta, "nodes": nodes, "edges": edge_list, "clusters": cl, "top": tp}
    viewer_dir.mkdir(parents=True, exist_ok=True)
    path = viewer_dir / "graph_data.js"
    path.write_text("window.GRAPH_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                                                         default=str) + ";\n", encoding="utf-8")
    return path

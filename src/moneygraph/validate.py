"""Механическая проверка выгрузок по схеме ТЗ (её же запускают тесты)."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from moneygraph.config import ROLES


def check(out_dir: Path, data_dir: Path) -> list[str]:
    """Возвращает список нарушений (пустой = всё в порядке)."""
    errs: list[str] = []
    nodes = pd.read_parquet(data_dir / "nodes.parquet")
    for name in ("nodes_roles.csv", "clusters.csv", "top_nodes.csv"):
        raw = (out_dir / name).read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            errs.append(f"{name}: UTF-8 BOM")
    nr = pd.read_csv(out_dir / "nodes_roles.csv", dtype={"gid": str})
    cl = pd.read_csv(out_dir / "clusters.csv")
    tp = pd.read_csv(out_dir / "top_nodes.csv", dtype={"gid": str})

    req = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
    missing = [c for c in req if c not in nr.columns]
    if missing:
        errs.append(f"nodes_roles: нет колонок {missing}")
        return errs
    if len(nr) != 2248 or len(nr) != len(nodes):
        errs.append(f"nodes_roles: {len(nr)} строк вместо {len(nodes)}")
    if set(nr.gid) != set(nodes.gid.astype(str)):
        errs.append("nodes_roles: множество gid не совпадает с nodes.parquet")
    if nr.gid.duplicated().any():
        errs.append("nodes_roles: дубликаты gid")
    if nr.isna().any().any():
        errs.append(f"nodes_roles: пустые значения в {list(nr.columns[nr.isna().any()])}")
    if not nr.role.isin(ROLES).all():
        errs.append(f"nodes_roles: роли вне словаря {set(nr.role) - set(ROLES)}")
    for c in ("role_score", "priority_score"):
        if not nr[c].between(0, 1).all():
            errs.append(f"nodes_roles: {c} вне [0, 1]")
    ev = nr.evidence.astype(str)
    if (ev.str.len() > 200).any() or (ev.str.strip() == "").any():
        errs.append("nodes_roles: evidence пустой или длиннее 200 символов")
    if not ev.map(lambda s: bool(re.search(r"\d", s))).all():
        errs.append("nodes_roles: evidence без чисел")

    for c in ("cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"):
        if c not in cl.columns:
            errs.append(f"clusters: нет колонки {c}")
    if not set(nr.cluster_id) <= set(cl.cluster_id):
        errs.append("clusters: не все cluster_id из nodes_roles описаны")
    if cl.n_nodes.sum() != len(nr):
        errs.append(f"clusters: сумма n_nodes {cl.n_nodes.sum()} ≠ {len(nr)}")
    if cl.n_seed.sum() != int(nodes.is_seed.sum()):
        errs.append("clusters: сумма n_seed ≠ числу seed")
    if cl.hypothesis.isna().any():
        errs.append("clusters: пустая гипотеза")

    for c in ("rank", "gid", "role", "priority_score", "why"):
        if c not in tp.columns:
            errs.append(f"top_nodes: нет колонки {c}")
    if len(tp) < 20:
        errs.append(f"top_nodes: {len(tp)} строк < 20")
    if list(tp["rank"]) != list(range(1, len(tp) + 1)):
        errs.append("top_nodes: rank не 1..N")
    if not tp.priority_score.is_monotonic_decreasing:
        errs.append("top_nodes: не отсортирован по приоритету")
    m = tp.merge(nr[["gid", "role", "priority_score"]], on="gid", suffixes=("", "_nr"))
    if len(m) != len(tp) or (m.role != m.role_nr).any() or ((m.priority_score - m.priority_score_nr).abs() > 1e-9).any():
        errs.append("top_nodes: не согласован с nodes_roles")
    return errs

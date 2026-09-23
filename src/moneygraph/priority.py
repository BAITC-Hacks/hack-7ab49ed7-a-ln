"""Приоритет проверки: прозрачная взвешенная сумма пяти компонент в [0, 1]."""

from __future__ import annotations

import numpy as np
import pandas as pd

from moneygraph.config import CFG, FLAG_RU, ROLE_META, Config


def flags(df: pd.DataFrame, cycle_nodes: set[int], route_nodes: set[int], cfg: Config = CFG) -> pd.Series:
    """Коды флагов временных паттернов и аномалий (см. FLAG_RU)."""
    out = []
    for r in df.itertuples(index=False):
        f = []
        if not np.isnan(r.fast_share) and r.fast_share >= cfg.fast_share_min:
            f.append("fast_transit")
        if r.burst_in >= cfg.burst_in_payers:
            f.append("burst_in")
        if r.burst_out >= cfg.burst_out_recipients:
            f.append("burst_out")
        if r.gid in cycle_nodes:
            f.append("in_cycle")
        if r.gid in route_nodes:
            f.append("repeat_route")
        if r.repeat_amount_n >= cfg.repeat_amount_min:
            f.append("repeat_amounts")
        if r.anomaly_z >= cfg.anomaly_z:
            f.append("anomaly")
        if r.unseen_inflow_kzt >= 100_000 and not r.is_seed:
            f.append("unseen_inflow")
        if r.late_in_share >= cfg.late_share and r.in_deg > 0 and r.out_deg == 0 and not r.truncated:
            f.append("late_inflow")
        if r.truncated:
            f.append("truncated")
        out.append(f)
    return pd.Series(out, index=df.index)


SIGNAL_FLAGS = {"fast_transit", "burst_in", "burst_out", "in_cycle", "repeat_route", "repeat_amounts", "anomaly"}


def components(df: pd.DataFrame, cfg: Config = CFG) -> pd.DataFrame:
    c = pd.DataFrame(index=df.index)
    c["role"] = df.role.map(cfg.role_weight) * df.role_score
    c["flow"] = np.log1p(df.in_kzt + df.out_kzt).rank(pct=True)
    c["centrality"] = np.maximum(df.pagerank.rank(pct=True), df.betweenness.rank(pct=True))
    c["seed"] = np.minimum(1.0, (df.seed_in + df.seed_out) / 3)
    c["flags"] = df["flags"].map(lambda f: min(1.0, len(SIGNAL_FLAGS & set(f)) / 3))
    return c


def score(df: pd.DataFrame, cfg: Config = CFG, weights: dict | None = None) -> pd.DataFrame:
    w = weights or {"role": cfg.w_role, "flow": cfg.w_flow, "centrality": cfg.w_central,
                    "seed": cfg.w_seed, "flags": cfg.w_flags}
    c = components(df, cfg)
    parts = pd.DataFrame({k: c[k] * w[k] for k in w}, index=df.index)
    disc = np.where(df.is_seed, cfg.seed_discount, 1.0)
    df = df.copy()
    df["priority_score"] = (parts.sum(axis=1) * disc).clip(0, 1).round(4)
    for k in w:
        df[f"prio_{k}"] = (parts[k] * disc).round(4)
    order = df.sort_values(["priority_score", "in_kzt", "gid"], ascending=[False, False, True]).index
    df.loc[order, "rank"] = np.arange(1, len(df) + 1)
    df["rank"] = df["rank"].astype(int)
    return df


def sensitivity(df: pd.DataFrame, cfg: Config = CFG, k: int = 20) -> dict:
    """Насколько топ-k устойчив к изменению каждого веса на ±20% (с перенормировкой)."""
    base_w = {"role": cfg.w_role, "flow": cfg.w_flow, "centrality": cfg.w_central, "seed": cfg.w_seed, "flags": cfg.w_flags}
    base = set(df.nsmallest(k, "rank").gid)
    overlaps = []
    for name in base_w:
        for f in (0.8, 1.2):
            w = dict(base_w)
            w[name] *= f
            tot = sum(w.values())
            w = {a: b / tot for a, b in w.items()}
            top = set(score(df, cfg, w).nsmallest(k, "rank").gid)
            overlaps.append(len(base & top) / k)
    return {"k": k, "min_overlap": round(min(overlaps), 3), "mean_overlap": round(float(np.mean(overlaps)), 3)}


def why(r, cluster_hyp: str) -> str:
    fl = [FLAG_RU[f] for f in r.flags if f in SIGNAL_FLAGS or f == "unseen_inflow"]
    parts = [f"{ROLE_META[r.role]['ru']} (уверенность {r.role_score:.2f}; {r.rule_fired}). {r.evidence}"]
    if fl:
        parts.append("Сигналы: " + "; ".join(fl))
    parts.append(
        f"Приоритет {r.priority_score:.3f} = роль {r.prio_role:.3f} + оборот {r.prio_flow:.3f} + "
        f"центральность {r.prio_centrality:.3f} + связь с seed {r.prio_seed:.3f} + сигналы {r.prio_flags:.3f}"
        + (" (×0,9: уже известный seed)" if r.is_seed else ""))
    parts.append(f"Кластер {r.cluster_id}: {cluster_hyp}")
    return ". ".join(p.rstrip(".") for p in parts) + "."

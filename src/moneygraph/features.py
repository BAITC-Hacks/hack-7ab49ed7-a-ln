"""Структурные признаки узлов + оценка «пересылает ли дальше» для узлов, обрезанных 4-м коленом."""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from moneygraph.config import CFG, Config
from moneygraph.temporal import fast_forward_share, node_temporal, robust_z

IN_DEG_BINS = [(1, 1, "1"), (2, 2, "2"), (3, 4, "3–4"), (5, 10**9, "5+")]
IN_TX_BINS = [(1, 1, "1"), (2, 4, "2–4"), (5, 10**9, "5+")]


def _bin(v: int, bins) -> str:
    for lo, hi, lab in bins:
        if lo <= v <= hi:
            return lab
    return bins[0][2]


def structural(G: nx.DiGraph, df: pd.DataFrame) -> pd.DataFrame:
    seeds = set(df.loc[df.is_seed, "gid"])
    df = df.copy()
    df["seed_in"] = df.gid.map(lambda g: sum(1 for p in G.predecessors(g) if p in seeds))
    df["seed_out"] = df.gid.map(lambda g: sum(1 for s in G.successors(g) if s in seeds))
    # Посредничество по числу шагов (без весов): networkx трактует weight как длину, сумма тут не подходит.
    df["betweenness"] = df.gid.map(nx.betweenness_centrality(G, normalized=True))
    df["observed_out"] = df.depth <= CFG.max_observed_out_depth
    df["avg_in"] = np.where(df.in_tx > 0, df.in_kzt / df.in_tx.clip(lower=1), 0.0)
    df["avg_out"] = np.where(df.out_tx > 0, df.out_kzt / df.out_tx.clip(lower=1), 0.0)
    df["unseen_inflow_kzt"] = (df.out_kzt - df.in_kzt).clip(lower=0)
    return df


def cycles(G: nx.DiGraph, cfg: Config = CFG) -> list[list[int]]:
    return [c for c in nx.simple_cycles(G, length_bound=cfg.cycle_max_len)]


def forward_table(df: pd.DataFrame, cfg: Config = CFG) -> tuple[pd.DataFrame, dict]:
    """Эмпирическая таблица P(пересылает дальше | число плательщиков, число переводов).

    Обучается на не-seed узлах колен 1–3, у которых исходящие известны полностью. Доли сглажены
    Beta-априором к общей доле. Бэктест: таблица по коленам 1–2 → прогноз для колена 3 (AUC, калибровка).
    """
    train = df[(~df.is_seed) & df.depth.between(1, 3) & (df.in_deg > 0)].copy()
    train["fwd"] = (train.out_deg > 0).astype(int)
    train["b_deg"] = train.in_deg.map(lambda v: _bin(v, IN_DEG_BINS))
    train["b_tx"] = train.in_tx.map(lambda v: _bin(v, IN_TX_BINS))

    def fit(t: pd.DataFrame) -> tuple[pd.Series, float]:
        base = t.fwd.mean()
        g = t.groupby(["b_deg", "b_tx"]).fwd.agg(["sum", "size"])
        p = (g["sum"] + cfg.p_forward_prior * base) / (g["size"] + cfg.p_forward_prior)
        return p, base

    def predict(p: pd.Series, base: float, t: pd.DataFrame) -> np.ndarray:
        return np.array([p.get((a, b), base) for a, b in zip(t.b_deg, t.b_tx)])

    table, base = fit(train)
    by_depth = train.groupby("depth").fwd.mean().round(3).to_dict()

    # бэктест: колена 1–2 → колено 3
    tr, te = train[train.depth <= 2], train[train.depth == 3]
    p_bt, base_bt = fit(tr)
    pred = predict(p_bt, base_bt, te)
    auc = _auc(te.fwd.to_numpy(), pred)
    te = te.assign(pred=pred)
    calib = te.groupby(pd.cut(te.pred, [0, 0.35, 0.5, 0.65, 1.0])).agg(
        predicted=("pred", "mean"), actual=("fwd", "mean"), n=("fwd", "size")).dropna()
    report = {
        "base_rate": round(float(base), 3),
        "rate_by_depth": {int(k): v for k, v in by_depth.items()},
        "backtest_auc_depth3": round(float(auc), 3),
        "backtest_calibration": [
            {"bin": str(i), "predicted": round(float(r.predicted), 3), "actual": round(float(r.actual), 3), "n": int(r.n)}
            for i, r in calib.iterrows()],
        "table": [{"in_deg": a, "in_tx": b, "p_forward": round(float(v), 3),
                   "n": int(((train.b_deg == a) & (train.b_tx == b)).sum())} for (a, b), v in table.items()],
    }
    tab = table.rename("p").reset_index()
    return tab, report


def _auc(y: np.ndarray, s: np.ndarray) -> float:
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    ranks = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return (ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def add_p_forward(df: pd.DataFrame, tab: pd.DataFrame, base: float) -> pd.DataFrame:
    """p_forward: для колен 0–3 — наблюдаемый факт (1 = переслал дальше, 0 = нет),
    для 4-го колена — оценка по таблице forward_table."""
    lut = {(r.b_deg, r.b_tx): r.p for r in tab.itertuples()}
    df = df.copy()
    est = [lut.get((_bin(d, IN_DEG_BINS), _bin(t, IN_TX_BINS)), base) for d, t in zip(df.in_deg, df.in_tx)]
    df["p_forward"] = np.where(df.observed_out, (df.out_deg > 0).astype(float), np.round(est, 3))
    df["truncated"] = ~df.observed_out
    return df


def add_temporal(df: pd.DataFrame, tx: pd.DataFrame, cfg: Config = CFG) -> pd.DataFrame:
    df = df.set_index("gid")
    df = df.join(fast_forward_share(tx, cfg)).join(node_temporal(tx, cfg))
    for c, v in {"burst_in": 0, "burst_out": 0, "active_days": 0, "late_in_share": 0.0, "repeat_amount_n": 0}.items():
        df[c] = df[c].fillna(v)
    df["burst_in_date"] = df["burst_in_date"].fillna("")
    df["burst_out_date"] = df["burst_out_date"].fillna("")
    return df.reset_index()


def add_anomaly(df: pd.DataFrame, cfg: Config = CFG) -> pd.DataFrame:
    """Аномальный профиль: робастный z-score оборота и числа переводов относительно узлов того же колена."""
    df = df.copy()
    vol = np.log1p(df.in_kzt + df.out_kzt)
    cnt = np.log1p(df.in_tx + df.out_tx)
    z_vol = vol.groupby(df.depth).transform(robust_z)
    z_cnt = cnt.groupby(df.depth).transform(robust_z)
    df["anomaly_z"] = np.maximum(z_vol, z_cnt).round(2)
    return df

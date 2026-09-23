"""Временные паттерны по transactions.parquet: сквозной транзит, всплески, обрыв по времени, маршруты."""

from __future__ import annotations

import numpy as np
import pandas as pd

from moneygraph.config import CFG, Config


def fast_forward_share(tx: pd.DataFrame, cfg: Config = CFG) -> pd.DataFrame:
    """FIFO-сопоставление: какая доля входящих денег ушла дальше за 0..fast_lag_days дней.

    Для каждого узла, у которого есть и входящие, и исходящие переводы, исходящие по датам «гасят»
    входящие, поступившие не раньше чем за fast_lag_days дней до них. Возвращает fast_share (доля
    входящей суммы) и first_lag (дни от первого поступления до первой отправки).
    """
    inc = tx.groupby(["dst", "date"]).sum_kzt.sum()
    out = tx.groupby(["src", "date"]).sum_kzt.sum()
    in_nodes = set(inc.index.get_level_values(0))
    out_nodes = set(out.index.get_level_values(0))
    rows = []
    for node in in_nodes & out_nodes:
        i = inc.loc[node]
        o = out.loc[node]
        events = sorted([(d, 0, a) for d, a in i.items()] + [(d, 1, a) for d, a in o.items()])
        pool: list[list] = []
        fast = 0.0
        for d, kind, a in events:
            if kind == 0:
                pool.append([d, a])
                continue
            need = a
            for p in pool:
                if need <= 0:
                    break
                if p[1] <= 0:
                    continue
                if 0 <= (d - p[0]).days <= cfg.fast_lag_days:
                    take = min(p[1], need)
                    p[1] -= take
                    need -= take
                    fast += take
        rows.append((node, fast / i.sum(), (o.index.min() - i.index.min()).days))
    return pd.DataFrame(rows, columns=["gid", "fast_share", "first_lag"]).set_index("gid")


def node_temporal(tx: pd.DataFrame, cfg: Config = CFG) -> pd.DataFrame:
    """Признаки узла по датам: всплески, доля поздних поступлений, повторяющиеся суммы."""
    end = pd.Timestamp(cfg.period_end)
    late_from = end - pd.Timedelta(days=cfg.late_days - 1)
    inc = tx.assign(late=tx.date >= late_from)
    late_share = inc.groupby("dst").apply(
        lambda g: g.loc[g.late, "sum_kzt"].sum() / g.sum_kzt.sum(), include_groups=False)

    b_in = tx.groupby(["dst", "date"]).src.nunique()
    b_in_max = b_in.groupby(level=0).max()
    b_in_date = b_in.groupby(level=0).idxmax().map(lambda t: t[1].strftime("%d.%m"))
    b_out = tx.groupby(["src", "date"]).dst.nunique()
    b_out_max = b_out.groupby(level=0).max()
    b_out_date = b_out.groupby(level=0).idxmax().map(lambda t: t[1].strftime("%d.%m"))

    # повторяющиеся одинаковые «круглые» суммы во входящих от ≥2 разных плательщиков
    rnd = tx[(tx.sum_kzt % 1000 == 0)]
    rep = rnd.groupby(["dst", "sum_kzt"]).agg(n=("src", "size"), payers=("src", "nunique")).reset_index()
    rep = rep[(rep.n >= cfg.repeat_amount_min) & (rep.payers >= 2)]
    rep_max = rep.sort_values("n", ascending=False).drop_duplicates("dst").set_index("dst")

    active_days = pd.concat([tx[["src", "date"]].rename(columns={"src": "gid"}),
                             tx[["dst", "date"]].rename(columns={"dst": "gid"})]).groupby("gid").date.nunique()
    df = pd.DataFrame({
        "late_in_share": late_share,
        "burst_in": b_in_max, "burst_in_date": b_in_date,
        "burst_out": b_out_max, "burst_out_date": b_out_date,
        "active_days": active_days,
    })
    df["repeat_amount"] = rep_max["sum_kzt"]
    df["repeat_amount_n"] = rep_max["n"]
    df.index.name = "gid"
    return df


def repeated_routes(tx: pd.DataFrame, cfg: Config = CFG) -> pd.DataFrame:
    """Устойчивые маршруты A→B→C: B пересылает C в течение 0..fast_lag_days дней после поступления от A,
    и так повторяется в ≥route_min_dates разных дат."""
    a = tx[["src", "dst", "date", "sum_kzt"]].rename(columns={"src": "a", "dst": "b", "date": "d1", "sum_kzt": "s1"})
    b = tx[["src", "dst", "date", "sum_kzt"]].rename(columns={"src": "b", "dst": "c", "date": "d2", "sum_kzt": "s2"})
    m = a.merge(b, on="b")
    lag = (m.d2 - m.d1).dt.days
    m = m[(lag >= 0) & (lag <= cfg.fast_lag_days) & (m.a != m.c)]
    if m.empty:
        return pd.DataFrame(columns=["a", "b", "c", "n_dates", "sum_in", "sum_out", "first", "last"])
    key = ["a", "b", "c"]
    g = m.groupby(key).agg(n_dates=("d1", "nunique"), first=("d1", "min"), last=("d2", "max"))
    g["sum_in"] = m.drop_duplicates(key + ["d1", "s1"]).groupby(key).s1.sum()
    g["sum_out"] = m.drop_duplicates(key + ["d2", "s2"]).groupby(key).s2.sum()
    g = g.reset_index()
    g = g[g.n_dates >= cfg.route_min_dates].sort_values(["n_dates", "sum_out"], ascending=False)
    g["first"] = g["first"].dt.strftime("%Y-%m-%d")
    g["last"] = g["last"].dt.strftime("%Y-%m-%d")
    return g.reset_index(drop=True)


def edge_tx_lists(tx: pd.DataFrame) -> dict[tuple[int, int], list]:
    """(src, dst) → [[дата, сумма], ...] для экрана просмотра."""
    t = tx.sort_values("date")
    out: dict[tuple[int, int], list] = {}
    for s, d, dt, amt in zip(t.src.to_numpy(), t.dst.to_numpy(), t.date.dt.strftime("%Y-%m-%d"), t.sum_kzt.to_numpy()):
        out.setdefault((int(s), int(d)), []).append([dt, round(float(amt), 2)])
    return out


def robust_z(x: pd.Series) -> pd.Series:
    med = x.median()
    mad = (x - med).abs().median()
    if mad == 0 or np.isnan(mad):
        return pd.Series(0.0, index=x.index)
    return 0.6745 * (x - med) / mad

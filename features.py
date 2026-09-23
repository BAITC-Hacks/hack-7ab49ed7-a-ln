"""
Признаки узлов. Граф направленный и взвешенный; ненаправленная проекция используется только
для Louvain (clusters.py). Авторство: трассировка, доминаторы и модель обрыва — Claude;
FIFO-сопоставление, датированные циклы, робастные аномалии и посредничество — Codex.
"""
from collections import Counter, defaultdict, deque

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import config as C


# ---------------------------------------------------------------- базовые

def base_features(G: nx.DiGraph, nodes: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    f = nodes.set_index("gid")[["depth", "is_seed"]].copy()
    f["in_deg"] = pd.Series(dict(G.in_degree()), dtype="int64")
    f["out_deg"] = pd.Series(dict(G.out_degree()), dtype="int64")
    for side, key in (("in", "dst"), ("out", "src")):
        g = edges.groupby(key)
        f[f"{side}_kzt"] = g.sum_kzt.sum().reindex(f.index, fill_value=0.0)
        f[f"{side}_tx"] = g.n_tx.sum().reindex(f.index, fill_value=0).astype(int)
        f[f"{side}_top_share"] = (g.sum_kzt.max().reindex(f.index, fill_value=0.0)
                                  / f[f"{side}_kzt"].clip(lower=1))
    f["out_observed"] = f.depth <= C.MAX_EXPANDED_DEPTH
    f["truncated"] = ~f.out_observed
    f["isolated"] = (f.in_deg + f.out_deg) == 0
    # отношение «отдал/получил» имеет смысл только для не-seed с видимым входом и раскрытыми исходящими;
    # у seed вход занижен, у 4-го колена исходящие не выгружались → отношение не публикуется (NaN)
    f["ratio_valid"] = (~f.is_seed) & (f.in_kzt > 0) & f.out_observed
    f["pass_ratio"] = (f.out_kzt / f.in_kzt.where(f.in_kzt > 0)).where(f.ratio_valid).round(4)
    seeds = set(nodes.gid[nodes.is_seed])
    f["seed_payers"] = [sum(p in seeds for p in G.predecessors(g)) for g in f.index]
    f["pays_seeds"] = [sum(s in seeds for s in G.successors(g)) for g in f.index]
    reach = Counter()
    for s in sorted(seeds):
        reach.update(nx.descendants(G, s))
    f["reachable_seeds"] = pd.Series(reach).reindex(f.index, fill_value=0).astype(int)
    return f


# ---------------------------------------------------------------- трассировка денег seed

def trace_seed_money(nodes: pd.DataFrame, tx: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    """
    Хронологическая пропорциональная трассировка (haircut по датам). Транзакции обрабатываются по
    порядку дат (внутри дня — по колену обхода, т. е. по направлению движения денег). У каждого узла
    есть видимый остаток (вход − выход, не ниже нуля) и «пул» помеченных денег по каждому seed.
    Перевод суммы a уносит долю a / max(остаток, a) пула — пропорционально составу средств узла;
    если узел отправляет больше видимого остатка, разница — внешние средства без метки.
    У seed непомеченная часть оттока получает метку самого seed (его вход вне выгрузки).
    Деньги не могут «уйти раньше, чем пришли»; итераций и вопроса сходимости нет.
    """
    gids = nodes.gid.values
    idx = {g: i for i, g in enumerate(gids)}
    n = len(gids)
    is_seed = nodes.is_seed.values
    S = np.where(is_seed)[0]
    label = {int(s): k for k, s in enumerate(S)}
    depth = {(r.src, r.dst): int(r.depth) for r in edges.itertuples(index=False)}
    order = tx.assign(edge_depth=[depth[(s, d)] for s, d in zip(tx.src, tx.dst)]) \
              .sort_values(["day", "edge_depth", "src", "dst", "sum_kzt"], kind="mergesort")
    pool = np.zeros((n, len(S)))
    recv = np.zeros((n, len(S)))
    bal = np.zeros(n)
    inn = np.zeros(n)
    for s, d, a in zip(order.src.map(idx).values, order.dst.map(idx).values, order.sum_kzt.values):
        avail = max(bal[s], a)
        moved = pool[s] * (a / avail)
        pool[s] -= moved
        if is_seed[s]:
            moved = moved.copy()
            moved[label[s]] += a - moved.sum()
        pool[d] += moved
        recv[d] += moved
        bal[s] = max(bal[s] - a, 0.0)
        bal[d] += a
        inn[d] += a
    Cm = recv
    T = Cm.sum(1)
    p = np.divide(Cm, T[:, None], out=np.zeros_like(Cm), where=T[:, None] > 0)
    res = pd.DataFrame(index=pd.Index(gids, name="gid"))
    res["traced_in_kzt"] = T.round(0)
    res["traced_share"] = np.divide(T, inn, out=np.zeros(n), where=inn > 0).clip(0, 1).round(4)
    res["seed_sources"] = (Cm >= C.SEED_SOURCE_MIN_KZT).sum(1)
    res["seed_mix_eff"] = np.where(T >= C.SEED_MIX_MIN_KZT, 1.0 / np.maximum((p ** 2).sum(1), 1e-12), 0.0).round(2)
    top = np.argmax(Cm, axis=1)
    res["main_seed"] = np.where(T > 0, gids[S[top]], 0)
    res["main_seed_share"] = np.where(T > 0, p[np.arange(n), top], 0.0).round(4)
    return res


# ---------------------------------------------------------------- контроль (доминаторы)

def dominator_control(G: nx.DiGraph, nodes: pd.DataFrame) -> pd.DataFrame:
    """control_nodes(v): сколько узлов перестанут быть достижимы от seed при блокировке v."""
    ROOT = -1
    H = G.copy()
    H.add_edges_from((ROOT, int(s)) for s in nodes.gid[nodes.is_seed])
    idom = nx.immediate_dominators(H, ROOT)
    children = defaultdict(list)
    for v, d in idom.items():
        if v != d:
            children[d].append(v)
    in_kzt = dict(G.in_degree(weight="sum_kzt"))
    tree = nx.DiGraph([(d, v) for d, vs in children.items() for v in vs])
    size, money = {}, {}
    for v in reversed(list(nx.dfs_preorder_nodes(tree, ROOT))):
        size[v] = sum(size[c] + 1 for c in children.get(v, []))
        money[v] = sum(money[c] + in_kzt.get(c, 0.0) for c in children.get(v, []))
    res = pd.DataFrame(index=pd.Index(nodes.gid.values, name="gid"))
    res["control_nodes"] = [size.get(v, 0) for v in res.index]
    res["control_kzt"] = [round(money.get(v, 0.0)) for v in res.index]
    return res


# ---------------------------------------------------------------- структура: посредничество, PageRank

def structure_features(G: nx.DiGraph, f: pd.DataFrame, cluster_of: dict) -> pd.DataFrame:
    res = pd.DataFrame(index=f.index)
    comps = sorted(nx.weakly_connected_components(G), key=lambda c: (-len(c), min(c)))
    comp_id, comp_size = {}, {}
    bet = pd.Series(0.0, index=f.index)
    bet_pct = pd.Series(0.0, index=f.index)
    for cid, members in enumerate(comps):
        ids = sorted(members)
        for g in ids:
            comp_id[g], comp_size[g] = cid, len(ids)
        if len(ids) > 2:
            # длина ребра = 1/сумма: «коротки» каналы с крупным оборотом
            bc = pd.Series(nx.betweenness_centrality(G.subgraph(ids), k=min(C.BETWEENNESS_SAMPLES, len(ids)),
                                                     weight="distance", normalized=True, seed=C.RANDOM_SEED))
            bet.loc[bc.index] = bc
            bet_pct.loc[bc.index] = bc.rank(pct=True).where(bc > 0, 0.0)
    res["component_id"] = pd.Series(comp_id)
    res["component_size"] = pd.Series(comp_size)
    res["betweenness"] = bet
    res["betweenness_pct"] = bet_pct.round(4)
    res["partner_clusters"] = [len({cluster_of[p] for p in set(G.predecessors(g)) | set(G.successors(g))})
                               for g in f.index]
    pr = nx.pagerank(G, weight="sum_kzt", max_iter=300, tol=1e-10)
    res["pagerank"] = pd.Series(pr).round(6)
    return res


# ---------------------------------------------------------------- время

def fifo_match(incoming, outgoing, window=C.FAST_DAYS, allow_same_day=True, keep_routes=False):
    """Сопоставление сумм по FIFO с окном: совместимость по датам, а не доказанное происхождение."""
    incoming, outgoing = sorted(incoming), sorted(outgoing)
    queue, cursor, matched = deque(), 0, 0.0
    routes = defaultdict(float)
    for out_day, recipient, amount in outgoing:
        while cursor < len(incoming) and (incoming[cursor][0] <= out_day if allow_same_day
                                          else incoming[cursor][0] < out_day):
            d, payer, a = incoming[cursor]
            queue.append([d, payer, float(a)])
            cursor += 1
        while queue and queue[0][0] < out_day - window:
            queue.popleft()
        remaining = float(amount)
        while remaining > 0 and queue:
            d, payer, available = queue[0]
            take = min(available, remaining)
            matched += take
            remaining -= take
            queue[0][2] -= take
            if keep_routes and payer != recipient:
                routes[(payer, recipient, d, out_day)] += take
            if queue[0][2] <= 1e-8:
                queue.popleft()
    return matched, routes


def temporal_features(f: pd.DataFrame, tx: pd.DataFrame):
    incoming, outgoing = defaultdict(list), defaultdict(list)
    edge_days = defaultdict(set)
    split = Counter()
    for t in tx.itertuples(index=False):
        incoming[t.dst].append((t.day, t.src, float(t.sum_kzt)))
        outgoing[t.src].append((t.day, t.dst, float(t.sum_kzt)))
        edge_days[(t.src, t.dst)].add(t.day)
        split[(t.src, t.dst, t.day)] += 1
    split_nodes = Counter()
    for (s, d, _), c in split.items():
        if c >= C.SPLIT_MIN_TX:
            split_nodes[s] += 1
            split_nodes[d] += 1
    total_days = (pd.Timestamp(C.OBSERVATION_END) - pd.Timestamp(C.OBSERVATION_START)).days
    seeds = set(f.index[f.is_seed])
    rows = []
    for gid in f.index:
        ins, outs = incoming[gid], outgoing[gid]
        m2, routes = fifo_match(ins, outs, keep_routes=True)
        strict, _ = fifo_match(ins, outs, allow_same_day=False)
        denom = max(float(f.at[gid, "in_kzt"]), float(f.at[gid, "out_kzt"]), 1.0)
        rd = defaultdict(lambda: [set(), set(), 0.0])
        for (payer, rcpt, din, dout), v in sorted(routes.items()):
            if v >= C.MIN_VISIBLE_KZT:
                e = rd[(payer, rcpt)]
                e[0].add(din)
                e[1].add(dout)
                e[2] += v
        repeated = [v for v in rd.values() if min(len(v[0]), len(v[1])) >= C.REPEATED_ROUTE_MIN_DAYS]
        per_day = defaultdict(set)
        seed_day = defaultdict(set)
        for d, payer, _ in ins:
            per_day[d].add(payer)
            if payer in seeds:
                seed_day[d].add(payer)
        daily = Counter(d for d, _, _ in ins + outs)
        last_in = max((d for d, _, _ in ins), default=-1)
        small = [sum(C.MIN_VISIBLE_KZT <= a < C.SMALL_UPPER_KZT for _, _, a in side) for side in (ins, outs)]
        small_share = [c / max(len(side), 1) for c, side in zip(small, (ins, outs))]
        small_flag = any(c >= C.SMALL_MIN_TX and sh >= C.SMALL_MIN_SHARE for c, sh in zip(small, small_share))
        n_all = len(ins) + len(outs)
        rows.append(dict(
            gid=gid,
            fast_2d_share=round(m2 / denom, 4), strict_fast_2d_share=round(strict / denom, 4),
            repeated_routes=len(repeated), repeated_route_kzt=round(sum(v[2] for v in repeated)),
            sync_max_payers=max(map(len, per_day.values()), default=0),
            sync_days=sum(len(v) >= C.SYNC_MIN_PAYERS for v in per_day.values()),
            sync_max_seed_payers=max(map(len, seed_day.values()), default=0),
            active_days=len(daily), peak_day_tx=max(daily.values(), default=0),
            peak_day_share=round(max(daily.values(), default=0) / max(n_all, 1), 4),
            split_days=split_nodes.get(gid, 0),
            small_in_tx=small[0], small_out_tx=small[1],
            small_share=round(max(small_share), 4), small_amounts=small_flag,
            first_in_day=min((d for d, _, _ in ins), default=-1),
            last_in_day=last_in, first_out_day=min((d for d, _, _ in outs), default=-1),
            followup_days=total_days - last_in if last_in >= 0 else 0))
    res = pd.DataFrame(rows).set_index("gid")
    res["fast_transit"] = (res.fast_2d_share >= C.FAST_MIN_SHARE) & (res.strict_fast_2d_share >= C.STRICT_FAST_MIN_SHARE)
    res["sync_inflow"] = res.sync_max_payers >= C.SYNC_MIN_PAYERS
    res["burst"] = (res.peak_day_tx >= C.BURST_MIN_TX) & (res.peak_day_share >= C.BURST_MIN_SHARE)
    res["structuring"] = res.split_days > 0
    res["repeated_route"] = res.repeated_routes > 0
    return res, edge_days


# ---------------------------------------------------------------- циклы и аномалии

def _chronological_return(cycle, edge_days):
    for shift in range(len(cycle)):
        route = cycle[shift:] + cycle[:shift]
        days = [sorted(edge_days[(route[i], route[(i + 1) % len(route)])]) for i in range(len(route))]
        for first in days[0]:
            prev = first
            for options in days[1:]:
                nxt = [d for d in options if prev < d <= first + C.CYCLE_RETURN_DAYS]
                if not nxt:
                    break
                prev = nxt[0]
            else:
                return True
    return False


def cycle_features(G: nx.DiGraph, f: pd.DataFrame, edge_days) -> tuple[pd.DataFrame, dict]:
    res = pd.DataFrame(index=f.index)
    scc = {}
    for members in nx.strongly_connected_components(G):
        for g in members:
            scc[g] = len(members)
    res["scc_size"] = pd.Series(scc)
    short = Counter()
    dated = Counter()
    n_short = n_dated = 0
    for cyc in nx.simple_cycles(G, length_bound=C.CYCLE_MAX_LENGTH):
        if len(cyc) < 2:
            continue
        n_short += 1
        short.update(cyc)
        if _chronological_return(cyc, edge_days):
            n_dated += 1
            dated.update(cyc)
    res["short_cycles"] = pd.Series(short).reindex(f.index, fill_value=0).astype(int)
    res["dated_returns"] = pd.Series(dated).reindex(f.index, fill_value=0).astype(int)
    res["cycle"] = res.scc_size > 1
    res["dated_return"] = res.dated_returns > 0
    return res, {"short_cycles": n_short, "dated_cycles": n_dated}


def hop_anomaly(f: pd.DataFrame) -> pd.DataFrame:
    """Робастный z (медиана/MAD/IQR в log-шкале) относительно узлов того же колена."""
    res = pd.DataFrame(index=f.index)
    zs = {}
    for col in ("in_kzt", "out_kzt", "in_deg", "out_deg", "in_tx", "out_tx"):
        x = np.log1p(f[col].astype(float))
        med = x.groupby(f.depth).transform("median")
        mad = (x - med).abs().groupby(f.depth).transform("median")
        iqr = x.groupby(f.depth).transform(lambda s: s.quantile(0.75) - s.quantile(0.25))
        scale = pd.concat([1.4826 * mad, iqr / 1.349], axis=1).max(axis=1).clip(lower=C.ROBUST_SCALE_FLOOR)
        zs[col] = ((x - med) / scale).clip(lower=0)
    z = pd.DataFrame(zs)
    res["hop_z"] = z.max(axis=1).round(2)
    res["hop_z_metric"] = z.idxmax(axis=1)
    res["hop_anomaly"] = res.hop_z >= C.HOP_ANOMALY_MIN_Z
    return res


# ---------------------------------------------------------------- модель обрыва 4-го колена

def truncation_model(f: pd.DataFrame, tx: pd.DataFrame):
    """
    У узлов 4-го колена исходящие не выгружались. На коленах 1–3 ответ известен (исходящие собраны),
    поэтому учим логистическую регрессию: по профилю ВХОДЯЩИХ — передаёт ли узел деньги дальше.
    Качество — AUC на 5-кратной кросс-валидации; коэффициенты стандартизованы и интерпретируемы.
    """
    ins = tx.groupby("dst")
    X = pd.DataFrame(index=f.index)
    X["log_in_kzt"] = np.log1p(f.in_kzt)
    X["in_deg"] = f.in_deg
    X["log_in_tx"] = np.log1p(f.in_tx)
    X["log_max_tx"] = np.log1p(ins.sum_kzt.max()).reindex(f.index).fillna(0)
    X["round_share"] = ins.sum_kzt.apply(lambda s: float((s % 10_000 == 0).mean())).reindex(f.index).fillna(0)
    X["days_before_end"] = (pd.Timestamp(C.OBSERVATION_END) - ins.date.max()).dt.days.reindex(f.index).fillna(31)
    X["seed_payer"] = (f.seed_payers > 0).astype(int)
    fan = tx.groupby("src").dst.nunique()
    main_payer = tx.sort_values(["dst", "sum_kzt", "src"], ascending=[True, False, True]).drop_duplicates("dst")
    X["log_payer_fanout"] = np.log1p(main_payer.set_index("dst").src.map(fan)).reindex(f.index).fillna(0)

    # цель — «передаёт деньги дальше»: есть исходящий перевод в день первого поступления или позже
    first_in = tx.groupby("dst").day.min()
    last_out = tx.groupby("src").day.max()
    forwards = (last_out.reindex(f.index) >= first_in.reindex(f.index)).fillna(False)
    train = f[(f.depth.between(1, C.MAX_EXPANDED_DEPTH)) & (~f.is_seed) & (f.in_deg > 0)]
    Xt, y = X.loc[train.index], forwards.loc[train.index].astype(int)
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=C.RANDOM_SEED)
    oof = cross_val_predict(model, Xt, y, cv=cv, method="predict_proba")[:, 1]
    # проверка переноса между коленами: учим на 1–2, проверяем на 3 (ближайший аналог переноса на 4)
    near, far = train.depth <= 2, train.depth == 3
    m2 = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(Xt[near], y[near])
    p3 = m2.predict_proba(Xt[far])[:, 1]
    model.fit(Xt, y)
    p = pd.Series(model.predict_proba(X)[:, 1], index=f.index).round(3)
    info = {"auc_cv": round(float(roc_auc_score(y, oof)), 3), "base_rate": round(float(y.mean()), 3),
            "n_train": int(len(y)),
            "auc_transfer_d12_to_d3": round(float(roc_auc_score(y[far], p3)), 3),
            "d3_mean_pred": round(float(p3.mean()), 3), "d3_actual_rate": round(float(y[far].mean()), 3),
            "coefs": {k: round(float(v), 3) for k, v in zip(X.columns, model[-1].coef_[0])}}
    return p, info

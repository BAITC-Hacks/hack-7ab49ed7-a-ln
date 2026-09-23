from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field

import pandas as pd

from .. import config as C
from ..collection import Collection

Lot = tuple[int, int, float]


@dataclass
class _NodeTransfers:
    incoming: list[Lot] = field(default_factory=list)
    outgoing: list[Lot] = field(default_factory=list)


def fifo_match(
    incoming: list[Lot],
    outgoing: list[Lot],
    window: int = C.FAST_DAYS,
    allow_same_day: bool = True,
    keep_routes: bool = False,
) -> tuple[float, dict]:
    # Date/amount compatibility only — it does not prove the same money moved.
    incoming, outgoing = sorted(incoming), sorted(outgoing)
    queue, cursor, matched = deque(), 0, 0.0
    routes = defaultdict(float)
    for out_day, recipient, amount in outgoing:
        while cursor < len(incoming) and (
            incoming[cursor][0] <= out_day if allow_same_day else incoming[cursor][0] < out_day
        ):
            day, payer, value = incoming[cursor]
            queue.append([day, payer, float(value)])
            cursor += 1
        while queue and queue[0][0] < out_day - window:
            queue.popleft()
        remaining = float(amount)
        while remaining > 0 and queue:
            day, payer, available = queue[0]
            take = min(available, remaining)
            matched += take
            remaining -= take
            queue[0][2] -= take
            if keep_routes and payer != recipient:
                routes[(payer, recipient, day, out_day)] += take
            if queue[0][2] <= 1e-8:
                queue.popleft()
    return matched, routes


def _repeated_routes(routes: dict, min_kzt: float) -> list[list]:
    by_pair = defaultdict(lambda: [set(), set(), 0.0])
    for (payer, recipient, day_in, day_out), value in sorted(routes.items()):
        if value >= min_kzt:
            entry = by_pair[(payer, recipient)]
            entry[0].add(day_in)
            entry[1].add(day_out)
            entry[2] += value
    return [v for v in by_pair.values() if min(len(v[0]), len(v[1])) >= C.REPEATED_ROUTE_MIN_DAYS]


def _payers_per_day(incoming: list[Lot], seeds: set) -> tuple[dict, dict]:
    per_day, seeds_per_day = defaultdict(set), defaultdict(set)
    for day, payer, _ in incoming:
        per_day[day].add(payer)
        if payer in seeds:
            seeds_per_day[day].add(payer)
    return per_day, seeds_per_day


def _small_amounts(t: _NodeTransfers, collection: Collection) -> tuple[list[int], list[float], bool]:
    sides = (t.incoming, t.outgoing)
    counts = [
        sum(collection.min_transfer_kzt <= a < collection.small_amount_ceiling for _, _, a in side) for side in sides
    ]
    shares = [c / max(len(side), 1) for c, side in zip(counts, sides, strict=True)]
    flagged = any(c >= C.SMALL_MIN_TX and s >= C.SMALL_MIN_SHARE for c, s in zip(counts, shares, strict=True))
    return counts, shares, flagged


def _node_profile(
    gid, t: _NodeTransfers, in_kzt: float, out_kzt: float, seeds: set, split_days: int, collection: Collection
) -> dict:
    matched, routes = fifo_match(t.incoming, t.outgoing, keep_routes=True)
    strict, _ = fifo_match(t.incoming, t.outgoing, allow_same_day=False)
    denom = max(in_kzt, out_kzt, 1.0)
    repeated = _repeated_routes(routes, collection.min_transfer_kzt)
    per_day, seeds_per_day = _payers_per_day(t.incoming, seeds)
    daily = Counter(d for d, _, _ in t.incoming + t.outgoing)
    n_all = len(t.incoming) + len(t.outgoing)
    last_in = max((d for d, _, _ in t.incoming), default=-1)
    small, small_share, small_flag = _small_amounts(t, collection)
    return dict(
        gid=gid,
        fast_2d_share=round(matched / denom, 4),
        strict_fast_2d_share=round(strict / denom, 4),
        repeated_routes=len(repeated),
        repeated_route_kzt=round(sum(v[2] for v in repeated)),
        sync_max_payers=max(map(len, per_day.values()), default=0),
        sync_days=sum(len(v) >= C.SYNC_MIN_PAYERS for v in per_day.values()),
        sync_max_seed_payers=max(map(len, seeds_per_day.values()), default=0),
        active_days=len(daily),
        peak_day_tx=max(daily.values(), default=0),
        peak_day_share=round(max(daily.values(), default=0) / max(n_all, 1), 4),
        split_days=split_days,
        small_in_tx=small[0],
        small_out_tx=small[1],
        small_share=round(max(small_share), 4),
        small_amounts=small_flag,
        first_in_day=min((d for d, _, _ in t.incoming), default=-1),
        last_in_day=last_in,
        first_out_day=min((d for d, _, _ in t.outgoing), default=-1),
        followup_days=collection.observation_days - last_in if last_in >= 0 else 0,
    )


def temporal_features(f: pd.DataFrame, tx: pd.DataFrame, collection: Collection) -> tuple[pd.DataFrame, dict]:
    transfers: dict = defaultdict(_NodeTransfers)
    edge_days = defaultdict(set)
    per_pair_day = Counter()
    for t in tx.itertuples(index=False):
        transfers[t.dst].incoming.append((t.day, t.src, float(t.sum_kzt)))
        transfers[t.src].outgoing.append((t.day, t.dst, float(t.sum_kzt)))
        edge_days[(t.src, t.dst)].add(t.day)
        per_pair_day[(t.src, t.dst, t.day)] += 1
    split_days = Counter()
    for (s, d, _), count in per_pair_day.items():
        if count >= C.SPLIT_MIN_TX:
            split_days[s] += 1
            split_days[d] += 1
    seeds = set(f.index[f.is_seed])
    rows = [
        _node_profile(
            gid,
            transfers[gid],
            float(f.at[gid, "in_kzt"]),
            float(f.at[gid, "out_kzt"]),
            seeds,
            split_days.get(gid, 0),
            collection,
        )
        for gid in f.index
    ]
    res = pd.DataFrame(rows).set_index("gid")
    res["fast_transit"] = (res.fast_2d_share >= C.FAST_MIN_SHARE) & (
        res.strict_fast_2d_share >= C.STRICT_FAST_MIN_SHARE
    )
    res["sync_inflow"] = res.sync_max_payers >= C.SYNC_MIN_PAYERS
    res["burst"] = (res.peak_day_tx >= C.BURST_MIN_TX) & (res.peak_day_share >= C.BURST_MIN_SHARE)
    res["structuring"] = res.split_days > 0
    res["repeated_route"] = res.repeated_routes > 0
    return res, edge_days

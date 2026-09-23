from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config as C
from .collection import Collection
from .texts import fit_text, kzt, nodes_acc, payers, payers_nom, pct, plural, recipients_dat, recipients_nom, seeds


def c01(x) -> float:
    return float(np.clip(x, 0.0, 1.0))


def rule_flags(r) -> dict:
    n_in, n_out, ss = r.in_deg, r.out_deg, r.seed_sources
    ratio = r.pass_ratio
    fan = n_out >= C.DIST_MIN_RECIPIENTS and n_out >= C.DIST_FANOUT_FACTOR * max(n_in, 1)
    link = (
        ss >= C.COORD_LINK_SEED_SOURCES
        or r.betweenness_pct >= C.COORD_LINK_BETWEENNESS
        or r.partner_clusters >= C.COORD_LINK_PARTNER_CLUSTERS
    )
    hub = n_in >= C.COORD_MIN_PAYERS and n_out >= C.COORD_MIN_RECIPIENTS
    payback = (
        n_in >= C.COORD_ALT_PAYERS
        and ss >= C.COORD_ALT_SEED_SOURCES
        and r.pays_seeds >= 1
        and n_out >= C.COORD_ALT_MIN_RECIPIENTS
    )
    collect = n_in >= C.CONS_MIN_PAYERS or (n_in >= C.CONS_ALT_PAYERS and ss >= C.CONS_ALT_SEED_SOURCES)
    funnel = max(C.CONS_FUNNEL_BASE, n_in / C.CONS_FUNNEL_FACTOR) >= n_out
    retains = bool(r.ratio_valid and ratio <= C.CONS_RETAIN_MAX_RATIO)
    return {
        "rule_coordinator": bool(r.out_observed and link and (hub or payback)),
        "rule_consolidator": bool(collect and (funnel or retains) and not fan),
        "rule_distributor": bool(fan),
        "rule_transit": bool(
            r.ratio_valid and n_out > 0 and C.TRANSIT_RATIO[0] <= ratio <= C.TRANSIT_RATIO[1] and r.fast_transit
        ),
        "rule_terminal": bool(
            r.out_observed
            and n_in > 0
            and (n_out == 0 or (r.ratio_valid and ratio <= C.TERMINAL_MAX_RATIO))
            and r.followup_days >= C.TERMINAL_MIN_FOLLOWUP_DAYS
        ),
        "collect_signal": bool(collect),
    }


def flag_list(r, rules: dict, role: str) -> list:
    fl = []
    if r.is_seed:
        fl.append("seed")
    if r.isolated:
        fl.append("isolated")
    if r.truncated:
        fl.append("truncated")
        if r.p_continue == r.p_continue and r.p_continue >= C.LIKELY_CONTINUES_P:
            fl.append("likely_continues")
    if (
        r.out_observed
        and r.in_deg > 0
        and r.followup_days < C.TERMINAL_MIN_FOLLOWUP_DAYS
        and (r.out_deg == 0 or (r.ratio_valid and r.pass_ratio <= C.TERMINAL_MAX_RATIO))
    ):
        fl.append("short_followup")
    if r.ratio_valid and r.pass_ratio > C.TRANSIT_RATIO[1]:
        fl.append("external_funds")
    if rules["collect_signal"] and role not in ("coordinator", "consolidator"):
        fl.append("collector")
    for name in (
        "fast_transit",
        "sync_inflow",
        "burst",
        "structuring",
        "small_amounts",
        "cycle",
        "dated_return",
        "repeated_route",
        "hop_anomaly",
    ):
        if bool(getattr(r, name)):
            fl.append(name)
    if r.pays_seeds > 0 and r.seed_payers + r.seed_sources > 0 and not r.is_seed:
        fl.append("return_to_seed")
    if r.control_nodes >= C.BOTTLENECK_MIN_NODES:
        fl.append("bottleneck")
    if r.betweenness_pct >= C.COORD_LINK_BETWEENNESS:
        fl.append("bridge")
    return fl


def _extras(r, skip=()) -> list:
    ph = []
    if "sync" not in skip and r.sync_max_payers >= C.SYNC_MIN_PAYERS:
        ph.append(f"{r.sync_max_payers} плательщ. в один день")
    if "fast" not in skip and r.fast_transit:
        ph.append(f"{pct(r.fast_2d_share)} суммы пересылалось за 0–2 дня")
    if r.dated_returns:
        ph.append(f"датированных возвратов: {r.dated_returns}")
    if r.repeated_routes:
        ph.append(f"повторяющихся маршрутов: {r.repeated_routes}")
    if r.structuring:
        ph.append(f"дробление ≥{C.SPLIT_MIN_TX} переводов/день одному контрагенту")
    if r.control_nodes >= C.BOTTLENECK_MIN_NODES and "control" not in skip:
        ph.append(f"блокировка отрежет {nodes_acc(r.control_nodes)}")
    return ph


def _outflow_phrase(r) -> str:
    if r.out_deg == 0:
        return "дальше не передал"
    if not r.ratio_valid:
        return f"отдал {kzt(r.out_kzt)} {recipients_dat(r.out_deg)}"
    if r.pass_ratio > C.TRANSIT_RATIO[1]:
        return f"отдал {kzt(r.out_kzt)} (×{r.pass_ratio:.1f} к видимому входу, источник разницы не виден)"
    return f"отдал дальше {pct(r.pass_ratio)}"


@dataclass(frozen=True)
class RoleDecision:
    role: str
    score: float
    evidence: str


def _decision(role: str, score: float, parts: list[str]) -> RoleDecision:
    return RoleDecision(role, round(c01(score), 4), fit_text(parts))


def _coordinator(r) -> RoleDecision:
    n_in, n_out, ss = int(r.in_deg), int(r.out_deg), int(r.seed_sources)
    score = 0.5 + 0.5 * np.mean([c01(n_in / 15), c01(n_out / 40), c01(ss / 4), c01(r.betweenness_pct)])
    parts = [
        f"признаки координации: собирает от {payers(n_in)}"
        + (f" (деньги {seeds(ss)})" if ss else "")
        + f", рассылает {recipients_dat(n_out)}"
    ]
    if r.pays_seeds:
        parts.append(f"платит {r.pays_seeds} seed")
    if r.control_nodes:
        parts.append(f"блокировка отрежет от seed {nodes_acc(r.control_nodes)}")
    if r.partner_clusters >= C.COORD_LINK_PARTNER_CLUSTERS:
        parts.append(f"связывает {plural(r.partner_clusters, 'кластер', 'кластера', 'кластеров')}")
    return _decision("coordinator", score, parts + _extras(r, skip=("control",)))


def _consolidator(r) -> RoleDecision:
    n_in, n_out, ss = int(r.in_deg), int(r.out_deg), int(r.seed_sources)
    score = 0.5 + 0.5 * np.mean([c01(n_in / 15), c01(ss / 4), c01(1 - n_out / max(n_in, 1)), c01(r.traced_share)])
    sources = f", деньги {seeds(ss)}" if ss else ""
    return _decision(
        "consolidator",
        score,
        [
            f"признаки консолидации: {payers_nom(n_in)} ({r.seed_payers} из них seed)"
            f"{sources}; получил {kzt(r.in_kzt)}, {_outflow_phrase(r)}"
        ]
        + _extras(r),
    )


def _distributor(r) -> RoleDecision:
    n_in, n_out = int(r.in_deg), int(r.out_deg)
    score = 0.5 + 0.5 * np.mean([c01(n_out / 50), c01(1 - n_in / n_out), c01(1 - r.out_top_share)])
    parts = [
        f"веерная рассылка: {kzt(r.out_kzt)} на {plural(n_out, 'получателя', 'получателей', 'получателей')}, "
        f"получил {kzt(r.in_kzt)} от {payers(n_in)}; крупнейшему — {pct(r.out_top_share)}"
    ]
    if r.in_kzt > 0 and r.out_kzt > 2 * r.in_kzt:
        parts.append(f"отдал в {r.out_kzt / r.in_kzt:.0f} р. больше видимого входа")
    return _decision("distributor", score, parts + _extras(r))


def _transit(r) -> RoleDecision:
    closeness = c01(1 - abs(np.log2(r.pass_ratio)))
    score = 0.4 + 0.6 * np.mean(
        [closeness, c01(r.fast_2d_share), c01(r.strict_fast_2d_share / 0.5), c01(r.in_kzt / 300_000)]
    )
    return _decision(
        "transit",
        score,
        [
            f"признаки транзита: получил {kzt(r.in_kzt)} от {payers(r.in_deg)}, отдал "
            f"дальше {pct(r.pass_ratio)} ({recipients_nom(r.out_deg)}); "
            f"{pct(r.fast_2d_share)} суммы — за 0–2 дня"
        ]
        + _extras(r, skip=("fast",)),
    )


def _terminal(r) -> RoleDecision:
    kept = 1.0 if r.out_deg == 0 else 1 - r.pass_ratio
    score = 0.4 + 0.6 * np.mean([kept, c01(r.in_kzt / 500_000), c01(r.in_deg / 3), c01(r.followup_days / 30)])
    passed = "дальше не передал" if r.out_deg == 0 else f"отдал дальше {pct(r.pass_ratio)}"
    seed_note = "; seed: вход извне не виден" if r.is_seed else ""
    return _decision(
        "terminal",
        score,
        [
            f"деньги оседают: получил {kzt(r.in_kzt)} от {payers(r.in_deg)}, {passed}; "
            f"исходящие собраны полностью, наблюдение {r.followup_days} дн.{seed_note}"
        ]
        + _extras(r, skip=("fast",)),
    )


def _truncated(r, collection: Collection) -> RoleDecision:
    known = r.p_continue == r.p_continue
    estimate = (
        f"оценка вероятности дальнейших переводов {pct(r.p_continue)} (по аналогии с раскрытыми коленами)"
        if known
        else "оценка дальнейших переводов недоступна (мало данных)"
    )
    return _decision(
        "peripheral",
        1 - float(r.p_continue) if known else 0.5,
        [
            f"обрыв обхода на {collection.max_depth}-м колене: получил {kzt(r.in_kzt)} от {payers(r.in_deg)}; "
            f"исходящие не выгружались, {estimate}"
        ]
        + _extras(r),
    )


def _peripheral(r, rules: dict, collection: Collection) -> RoleDecision:
    n_in, n_out, ratio = int(r.in_deg), int(r.out_deg), r.pass_ratio
    if r.isolated:
        return _decision(
            "peripheral",
            0.9,
            [
                f"нет переводов ≥{kzt(collection.min_transfer_kzt)} в выгрузке "
                "(seed из списка); признаков роли в сети нет — нужны данные вне выгрузки"
            ],
        )
    if r.truncated:
        return _truncated(r, collection)
    if rules["collect_signal"]:
        return _decision(
            "peripheral",
            0.5,
            [
                f"сбор без накопления: {payers_nom(n_in)}, но {recipients_nom(n_out)}; "
                f"получил {kzt(r.in_kzt)}, {_outflow_phrase(r)}"
            ]
            + _extras(r),
        )
    if r.is_seed and n_out > 0:
        return _decision(
            "peripheral",
            0.5,
            [
                f"seed: входящие вне выгрузки, долю пропуска не оценить; отправил "
                f"{kzt(r.out_kzt)} {recipients_dat(n_out)}, {pct(r.out_top_share)} — "
                f"крупнейшему"
            ]
            + _extras(r),
        )
    if n_in > 0 and (n_out == 0 or (r.ratio_valid and ratio <= C.TERMINAL_MAX_RATIO)):
        kept = "дальше не передал" if n_out == 0 else f"отдал дальше лишь {pct(ratio)}"
        return _decision(
            "peripheral",
            0.5,
            [
                f"получил {kzt(r.in_kzt)} от {payers(n_in)}, {kept}, но после последнего "
                f"поступления всего {r.followup_days} дн. наблюдения — вывод об оседании "
                f"отложен"
            ]
            + _extras(r),
        )
    if r.ratio_valid and ratio > C.TRANSIT_RATIO[1]:
        return _decision(
            "peripheral",
            0.6,
            [
                f"отдал {kzt(r.out_kzt)} при видимом входе {kzt(r.in_kzt)} (×{ratio:.1f}): "
                f"источник разницы {kzt(r.out_kzt - r.in_kzt)} в выгрузке не виден; "
                f"{recipients_dat(n_out)}"
            ]
            + _extras(r),
        )
    if r.ratio_valid and ratio >= C.TRANSIT_RATIO[0]:
        return _decision(
            "peripheral",
            0.5,
            [
                f"баланс как у транзита (отдал {pct(ratio)} полученного), но пересылка "
                f"по датам не подтверждена: за 0–2 дня сопоставлено {pct(r.fast_2d_share)} "
                f"суммы"
            ]
            + _extras(r, skip=("fast",)),
        )
    if r.ratio_valid:
        return _decision(
            "peripheral",
            0.6,
            [f"частично удерживает: получил {kzt(r.in_kzt)}, отдал дальше {pct(ratio)}; выраженных признаков роли нет"]
            + _extras(r),
        )
    only_outflow = f"только исходящие: {kzt(r.out_kzt)} {recipients_dat(n_out)}; признаков роли нет"
    return _decision("peripheral", 0.6, [only_outflow] + _extras(r))


# Checked in order: the first satisfied rule decides the role.
_RULE_ORDER = (
    ("rule_coordinator", _coordinator),
    ("rule_consolidator", _consolidator),
    ("rule_distributor", _distributor),
    ("rule_transit", _transit),
    ("rule_terminal", _terminal),
)


def assign(r, rules: dict, collection: Collection) -> RoleDecision:
    for rule, build in _RULE_ORDER:
        if rules[rule]:
            return build(r)
    return _peripheral(r, rules, collection)


def assign_all(f: pd.DataFrame, collection: Collection) -> pd.DataFrame:
    out = []
    for r in f.itertuples():
        rules = rule_flags(r)
        decision = assign(r, rules, collection)
        out.append(
            dict(
                gid=r.Index,
                role=decision.role,
                role_score=decision.score,
                evidence=decision.evidence,
                flags=flag_list(r, rules, decision.role),
                **rules,
            )
        )
    return pd.DataFrame(out).set_index("gid")

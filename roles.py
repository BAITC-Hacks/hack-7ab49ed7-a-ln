"""
Роли: явные правила с порогами из config.py. Правила проверяются по порядку, первое сработавшее
задаёт роль. role_score = сила поддержки правила данными (0–1), а не вероятность вины.
Каждое слагаемое role_score ограничено отрезком [0, 1] (функция c01).
"""
import numpy as np
import pandas as pd

from . import config as C
from .texts import (fit_text, kzt, nodes_acc, payers, payers_nom, pct, plural, recipients_dat,
                    recipients_nom, seeds)


def c01(x) -> float:
    return float(np.clip(x, 0.0, 1.0))


def rule_flags(r) -> dict:
    """Истинность каждого правила — выгружается в features.csv (rule_*) для проверки любого gid."""
    I, O, ss = r.in_deg, r.out_deg, r.seed_sources
    ratio = r.pass_ratio
    fan = O >= C.DIST_MIN_RECIPIENTS and O >= C.DIST_FANOUT_FACTOR * max(I, 1)
    link = (ss >= C.COORD_LINK_SEED_SOURCES or r.betweenness_pct >= C.COORD_LINK_BETWEENNESS
            or r.partner_clusters >= C.COORD_LINK_PARTNER_CLUSTERS)
    hub = I >= C.COORD_MIN_PAYERS and O >= C.COORD_MIN_RECIPIENTS
    payback = (I >= C.COORD_ALT_PAYERS and ss >= C.COORD_ALT_SEED_SOURCES and r.pays_seeds >= 1
               and O >= C.COORD_ALT_MIN_RECIPIENTS)
    collect = I >= C.CONS_MIN_PAYERS or (I >= C.CONS_ALT_PAYERS and ss >= C.CONS_ALT_SEED_SOURCES)
    funnel = O <= max(C.CONS_FUNNEL_BASE, I / C.CONS_FUNNEL_FACTOR)
    retains = bool(r.ratio_valid and ratio <= C.CONS_RETAIN_MAX_RATIO)
    return {
        "rule_coordinator": bool(r.out_observed and link and (hub or payback)),
        "rule_consolidator": bool(collect and (funnel or retains) and not fan),
        "rule_distributor": bool(fan),
        "rule_transit": bool(r.ratio_valid and O > 0 and C.TRANSIT_RATIO[0] <= ratio <= C.TRANSIT_RATIO[1]
                             and r.fast_transit),
        "rule_terminal": bool(r.out_observed and I > 0 and (O == 0 or (r.ratio_valid and ratio <= C.TERMINAL_MAX_RATIO))
                              and r.followup_days >= C.TERMINAL_MIN_FOLLOWUP_DAYS),
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
        if r.p_continue >= C.LIKELY_CONTINUES_P:
            fl.append("likely_continues")
    if (r.out_observed and r.in_deg > 0 and r.followup_days < C.TERMINAL_MIN_FOLLOWUP_DAYS
            and (r.out_deg == 0 or (r.ratio_valid and r.pass_ratio <= C.TERMINAL_MAX_RATIO))):
        fl.append("short_followup")
    if r.ratio_valid and r.pass_ratio > C.TRANSIT_RATIO[1]:
        fl.append("external_funds")
    if rules["collect_signal"] and role not in ("coordinator", "consolidator"):
        fl.append("collector")
    for name in ("fast_transit", "sync_inflow", "burst", "structuring", "small_amounts", "cycle", "dated_return",
                 "repeated_route", "hop_anomaly"):
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
    """Что узел сделал с деньгами — только по фактическим числам."""
    if r.out_deg == 0:
        return "дальше не передал"
    if not r.ratio_valid:
        return f"отдал {kzt(r.out_kzt)} {recipients_dat(r.out_deg)}"
    if r.pass_ratio > C.TRANSIT_RATIO[1]:
        return f"отдал {kzt(r.out_kzt)} (×{r.pass_ratio:.1f} к видимому входу, источник разницы не виден)"
    return f"отдал дальше {pct(r.pass_ratio)}"


def assign(r, rules: dict):
    """Возвращает (role, role_score, evidence) для одной строки признаков."""
    I, O, ss = int(r.in_deg), int(r.out_deg), int(r.seed_sources)
    ratio = r.pass_ratio

    if rules["rule_coordinator"]:
        s = 0.5 + 0.5 * np.mean([c01(I / 15), c01(O / 40), c01(ss / 4), c01(r.betweenness_pct)])
        head = (f"признаки координации: собирает от {payers(I)}"
                + (f" (деньги {seeds(ss)})" if ss else "") + f", рассылает {recipients_dat(O)}")
        parts = [head]
        if r.pays_seeds:
            parts.append(f"платит {r.pays_seeds} seed")
        if r.control_nodes:
            parts.append(f"блокировка отрежет от seed {nodes_acc(r.control_nodes)}")
        if r.partner_clusters >= C.COORD_LINK_PARTNER_CLUSTERS:
            parts.append(f"связывает {plural(r.partner_clusters, 'кластер', 'кластера', 'кластеров')}")
        return "coordinator", s, fit_text(parts + _extras(r, skip=("control",)))

    if rules["rule_consolidator"]:
        s = 0.5 + 0.5 * np.mean([c01(I / 15), c01(ss / 4), c01(1 - O / max(I, 1)), c01(r.traced_share)])
        src = f", деньги {seeds(ss)}" if ss else ""
        parts = [f"признаки консолидации: {payers_nom(I)} ({r.seed_payers} из них seed){src}; "
                 f"получил {kzt(r.in_kzt)}, {_outflow_phrase(r)}"]
        return "consolidator", s, fit_text(parts + _extras(r))

    if rules["rule_distributor"]:
        s = 0.5 + 0.5 * np.mean([c01(O / 50), c01(1 - I / O), c01(1 - r.out_top_share)])
        parts = [f"веерная рассылка: {kzt(r.out_kzt)} на {plural(O, 'получателя', 'получателей', 'получателей')}, "
                 f"получил {kzt(r.in_kzt)} от {payers(I)}; крупнейшему — {pct(r.out_top_share)}"]
        if r.in_kzt > 0 and r.out_kzt > 2 * r.in_kzt:
            parts.append(f"отдал в {r.out_kzt / r.in_kzt:.0f} р. больше видимого входа")
        return "distributor", s, fit_text(parts + _extras(r))

    if rules["rule_transit"]:
        close = c01(1 - abs(np.log2(ratio)))
        s = 0.4 + 0.6 * np.mean([close, c01(r.fast_2d_share), c01(r.strict_fast_2d_share / 0.5), c01(r.in_kzt / 300_000)])
        parts = [f"признаки транзита: получил {kzt(r.in_kzt)} от {payers(I)}, отдал дальше {pct(ratio)} "
                 f"({recipients_nom(O)}); {pct(r.fast_2d_share)} суммы — за 0–2 дня"]
        return "transit", s, fit_text(parts + _extras(r, skip=("fast",)))

    if rules["rule_terminal"]:
        kept = 1.0 if O == 0 else 1 - ratio
        s = 0.4 + 0.6 * np.mean([kept, c01(r.in_kzt / 500_000), c01(I / 3), c01(r.followup_days / 30)])
        seed_note = "; seed: вход извне не виден" if r.is_seed else ""
        parts = [f"деньги оседают: получил {kzt(r.in_kzt)} от {payers(I)}, "
                 f"{'дальше не передал' if O == 0 else 'отдал дальше ' + pct(ratio)}; исходящие собраны полностью, "
                 f"наблюдение {r.followup_days} дн.{seed_note}"]
        return "terminal", s, fit_text(parts + _extras(r, skip=("fast",)))

    # ---- периферия: признаков роли не выявлено (или данных недостаточно); тексты — только по фактам
    if r.isolated:
        return "peripheral", 0.9, ("нет переводов ≥5 000 ₸ внутри банка за июль (seed из списка); "
                                   "признаков роли в сети нет — нужны данные вне выгрузки")
    if r.truncated:
        parts = [f"обрыв обхода на 4-м колене: получил {kzt(r.in_kzt)} от {payers(I)}; исходящие не выгружались, "
                 f"оценка вероятности дальнейших переводов {pct(r.p_continue)} (по аналогии с коленами 1–3)"]
        return "peripheral", round(1 - float(r.p_continue), 4), fit_text(parts + _extras(r))
    if rules["collect_signal"]:
        parts = [f"сбор без накопления: {payers_nom(I)}, но {recipients_nom(O)}; получил {kzt(r.in_kzt)}, "
                 f"{_outflow_phrase(r)}"]
        return "peripheral", 0.5, fit_text(parts + _extras(r))
    if r.is_seed and O > 0:
        parts = [f"seed: входящие вне выгрузки, долю пропуска не оценить; отправил {kzt(r.out_kzt)} "
                 f"{recipients_dat(O)}, {pct(r.out_top_share)} — крупнейшему"]
        return "peripheral", 0.5, fit_text(parts + _extras(r))
    if I > 0 and (O == 0 or (r.ratio_valid and ratio <= C.TERMINAL_MAX_RATIO)):
        kept = "дальше не передал" if O == 0 else f"отдал дальше лишь {pct(ratio)}"
        parts = [f"получил {kzt(r.in_kzt)} от {payers(I)}, {kept}, но после последнего поступления всего "
                 f"{r.followup_days} дн. наблюдения — вывод об оседании отложен"]
        return "peripheral", 0.5, fit_text(parts + _extras(r))
    if r.ratio_valid and ratio > C.TRANSIT_RATIO[1]:
        parts = [f"отдал {kzt(r.out_kzt)} при видимом входе {kzt(r.in_kzt)} (×{ratio:.1f}): источник разницы "
                 f"{kzt(r.out_kzt - r.in_kzt)} в выгрузке не виден; {recipients_dat(O)}"]
        return "peripheral", 0.6, fit_text(parts + _extras(r))
    if r.ratio_valid and ratio >= C.TRANSIT_RATIO[0]:
        parts = [f"баланс как у транзита (отдал {pct(ratio)} полученного), но пересылка по датам не подтверждена: "
                 f"за 0–2 дня сопоставлено {pct(r.fast_2d_share)} суммы"]
        return "peripheral", 0.5, fit_text(parts + _extras(r, skip=("fast",)))
    if r.ratio_valid:
        parts = [f"частично удерживает: получил {kzt(r.in_kzt)}, отдал дальше {pct(ratio)}; "
                 f"выраженных признаков роли нет"]
        return "peripheral", 0.6, fit_text(parts + _extras(r))
    parts = [f"только исходящие: {kzt(r.out_kzt)} {recipients_dat(O)}; признаков роли нет"]
    return "peripheral", 0.6, fit_text(parts + _extras(r))


def assign_all(f: pd.DataFrame) -> pd.DataFrame:
    out = []
    for r in f.itertuples():
        rules = rule_flags(r)
        role, score, ev = assign(r, rules)
        out.append(dict(gid=r.Index, role=role, role_score=round(c01(score), 4), evidence=ev,
                        flags=flag_list(r, rules, role), **rules))
    return pd.DataFrame(out).set_index("gid")

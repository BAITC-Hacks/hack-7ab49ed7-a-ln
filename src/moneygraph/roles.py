"""Роли узлов: упорядоченный список правил (первое сработавшее — роль), уверенность и обоснование с числами.

Шкала role_score: 0.5 — узел ровно на пороге правила, 1.0 — порог превышен многократно (линейные рампы).
Для узлов 4-го колена role_score — эмпирическая вероятность (1 − p_forward или p_forward).
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from moneygraph.config import CFG, RAPID_MOVEMENT, ROLE_META, Config

EVIDENCE_MAX = 200


def fmt_kzt(x: float) -> str:
    x = float(x)
    if abs(x) >= 1e6:
        return f"{x / 1e6:.2f}".replace(".", ",") + " млн ₸"
    return f"{x / 1e3:.0f} тыс ₸"


def fmt_pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _ramp(x: float, lo: float, hi: float) -> float:
    return float(np.clip((x - lo) / (hi - lo), 0.0, 1.0)) if hi > lo else 1.0


def _score(*strengths: float) -> float:
    return round(0.5 + 0.5 * float(np.mean(strengths)), 3)


def _clip(text: str) -> str:
    """Обрезка до 200 символов по границам «; », чтобы не рвать фразы."""
    if len(text) <= EVIDENCE_MAX:
        return text
    out = ""
    for seg in text.split("; "):
        cand = seg if not out else out + "; " + seg
        if len(cand) > EVIDENCE_MAX:
            break
        out = cand
    return out if out else text[: EVIDENCE_MAX - 1] + "…"


def fmt_x(x: float) -> str:
    return f"{x:.1f}".replace(".", ",") + "×"


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _payers(n: int) -> str:
    return f"{n} {_plural(n, 'плательщика', 'плательщиков', 'плательщиков')}" if n != 1 else "1 плательщика"


def _recips(n: int) -> str:
    return f"{n} {_plural(n, 'получателю', 'получателям', 'получателям')}"


def _tx(n: int) -> str:
    return f"{n} {_plural(n, 'перевод', 'перевода', 'переводов')}"


def seed_cluster_span(G: nx.DiGraph, df: pd.DataFrame) -> dict[int, int]:
    """Сколько разных кластеров, содержащих seed, у узла среди соседей (включая свой)."""
    cl = dict(zip(df.gid, df.cluster_id))
    seed_clusters = set(df.loc[df.is_seed, "cluster_id"]) - {0}
    out = {}
    for g in df.gid:
        cs = {cl[n] for n in nx.all_neighbors(G, g)} | {cl[g]}
        out[g] = len(cs & seed_clusters)
    return out


def assign(G: nx.DiGraph, df: pd.DataFrame, cfg: Config = CFG) -> pd.DataFrame:
    df = df.copy()
    span = seed_cluster_span(G, df)
    btw_cut = df.betweenness.quantile(cfg.bridge_btw_quantile)
    act = np.log1p(df.in_kzt + df.out_kzt).rank(pct=True)
    res = [_decide(r, span[r.gid], btw_cut, a, cfg) for r, a in zip(df.itertuples(index=False), act)]
    df["role"], df["role_score"], df["rule_fired"], df["alt_role"], df["evidence"], df["sink_status"] = zip(*res)
    return df


def _flow_line(r) -> str:
    """Короткая сводка потоков с учётом неполноты данных."""
    parts = []
    if r.in_deg:
        parts.append(f"получил {fmt_kzt(r.in_kzt)} от {_payers(r.in_deg)} ({_tx(r.in_tx)})")
    if r.out_deg:
        parts.append(f"отправил {fmt_kzt(r.out_kzt)} {_recips(r.out_deg)} ({_tx(r.out_tx)})")
    return ", ".join(parts)


def _decide(r, n_seed_clusters: int, btw_cut: float, activity: float, cfg: Config):
    ratio = r.out_kzt / r.in_kzt if r.in_kzt > 0 else np.inf
    fast = 0.0 if np.isnan(r.fast_share) else float(r.fast_share)
    seeds_txt = ""
    if r.seed_in:
        seeds_txt = f"; seed среди плательщиков: {r.seed_in}"
    late = r.late_in_share >= cfg.late_share and r.in_deg > 0
    trunc = bool(r.truncated)
    trunc_txt = "; 4-е колено: исходящие не выгружены" if trunc else ""

    # ---- R1 coordinator
    fired = []
    if r.in_deg >= cfg.hub_min_in and r.out_deg >= cfg.hub_min_out:
        s = _score(_ramp(r.in_deg, cfg.hub_min_in, cfg.hub_full_in), _ramp(r.out_deg, cfg.hub_min_out, cfg.hub_full_out))
        fired.append((s, f"R1 хаб: in_deg={r.in_deg}≥{cfg.hub_min_in}, out_deg={r.out_deg}≥{cfg.hub_min_out}",
                      f"Хаб: собирает от {_payers(r.in_deg)} ({fmt_kzt(r.in_kzt)}) и раздаёт {_recips(r.out_deg)} "
                      f"({fmt_kzt(r.out_kzt)}); связан с {n_seed_clusters} кластерами с seed"))
    if r.seed_out >= cfg.coord_min_seed_payees:
        s = _score(_ramp(r.seed_out, cfg.coord_min_seed_payees, cfg.coord_full_seed_payees))
        fired.append((s, f"R1 платит seed: seed-получателей={r.seed_out}≥{cfg.coord_min_seed_payees}",
                      f"Платит {r.seed_out} известным участникам (seed); {_flow_line(r)}"))
    if r.betweenness >= btw_cut and r.betweenness > 0 and n_seed_clusters >= cfg.bridge_min_seed_clusters:
        s = _score(_ramp(n_seed_clusters, cfg.bridge_min_seed_clusters, cfg.bridge_full_seed_clusters))
        fired.append((s, f"R1 мост: посредничество {r.betweenness:.4f} (топ-1%), кластеров с seed={n_seed_clusters}",
                      f"Мост между {n_seed_clusters} кластерами с seed (посредничество в топ-1%); {_flow_line(r)}"))
    d_fire = r.out_deg >= cfg.distr_min_out and r.out_deg >= cfg.distr_fan_ratio * max(r.in_deg, 1)
    c_fire = r.in_deg >= cfg.cons_min_in or r.seed_in >= cfg.cons_min_seed_payers
    if fired:
        s, rule, ev = max(fired, key=lambda f: f[0])
        alt = "distributor" if d_fire else ("consolidator" if c_fire else "-")
        return "coordinator", s, rule, alt, _clip(ev + seeds_txt), "not_sink"

    # ---- R2 distributor / R3 consolidator
    fan_out_only = r.out_deg >= cfg.distr_min_out  # для alt_role
    if d_fire and (not c_fire or r.out_deg / cfg.distr_min_out >= r.in_deg / cfg.cons_min_in):
        s = _score(_ramp(r.out_deg, cfg.distr_min_out, cfg.distr_strong_out))
        ev = (f"Веерная раздача: {fmt_kzt(r.out_kzt)} {_recips(r.out_deg)} ({_tx(r.out_tx)}, в среднем "
              f"{fmt_kzt(r.avg_out)})")
        ev += f"; получил {fmt_kzt(r.in_kzt)} от {_payers(r.in_deg)}" if r.in_deg else "; входящие вне выборки"
        if r.burst_out >= cfg.burst_out_recipients:
            ev += f"; {int(r.burst_out)} {_plural(r.burst_out, 'получатель', 'получателя', 'получателей')} за один день ({r.burst_out_date})"
        return ("distributor", s, f"R2: out_deg={r.out_deg}≥{cfg.distr_min_out} и ≥{cfg.distr_fan_ratio:g}×in_deg",
                "consolidator" if c_fire else "-", _clip(ev), "not_sink")
    if c_fire:
        s = _score(max(_ramp(r.in_deg, cfg.cons_min_in, cfg.cons_strong_in),
                       _ramp(r.seed_in, cfg.cons_min_seed_payers, cfg.cons_full_seed_payers)))
        rule = (f"R3: in_deg={r.in_deg}≥{cfg.cons_min_in}" if r.in_deg >= cfg.cons_min_in
                else f"R3: seed-плательщиков={r.seed_in}≥{cfg.cons_min_seed_payers}")
        ev = f"Получает от {_payers(r.in_deg)}: {fmt_kzt(r.in_kzt)}, {_tx(r.in_tx)} (в среднем {fmt_kzt(r.avg_in)})"
        ev += seeds_txt
        if trunc:
            ev += trunc_txt
            sink = "truncated_depth"
        elif r.out_deg:
            ev += (f"; дальше ушло {fmt_pct(ratio)} полученного {_recips(r.out_deg)}" if ratio <= cfg.transit_hi else
                   f"; отправил {_recips(r.out_deg)} в {fmt_x(ratio)} больше полученного (невидимые входящие)")
            sink = "not_sink"
        else:
            ev += "; дальше не отправлял"
            sink = "truncated_time" if late else "confirmed_sink"
        if r.burst_in >= cfg.burst_in_payers:
            ev += f"; {int(r.burst_in)} {_plural(r.burst_in, 'плательщик', 'плательщика', 'плательщиков')} за один день ({r.burst_in_date})"
        alt = "distributor" if fan_out_only else ("terminal" if sink == "confirmed_sink" else "-")
        return "consolidator", s, rule, alt, _clip(ev), sink

    # ---- 4-е колено: исходящие неизвестны → роль по эмпирической вероятности пересылки
    if trunc:
        p = float(r.p_forward)
        material = r.in_kzt >= cfg.term_min_kzt or r.in_tx >= cfg.term_min_tx
        base = (f"4-е колено, исходящие не выгружены; {_flow_line(r)}. У узлов колен 1–3 с таким профилем "
                f"пересылают дальше {fmt_pct(p)}")
        if not material:
            return ("peripheral", round(1 - activity, 3), f"R6: разовый перевод {fmt_kzt(r.in_kzt)} < {fmt_kzt(cfg.term_min_kzt)}",
                    "-", _clip(f"Разовый перевод {fmt_kzt(r.in_kzt)} от {_payers(r.in_deg)}; 4-е колено, исходящие не выгружены"),
                    "truncated_depth")
        if p < cfg.trunc_forward_cut:
            return ("terminal", round(1 - p, 3), f"T4: p_forward={p:.2f}<{cfg.trunc_forward_cut} (оценка по коленам 1–3)",
                    "transit", _clip(base), "truncated_depth")
        return ("transit", round(min(p, cfg.trunc_transit_cap), 3), f"T4: p_forward={p:.2f}≥{cfg.trunc_forward_cut} (оценка)",
                "terminal", _clip(base), "truncated_depth")

    # ---- R4 transit
    if r.out_deg > 0 and r.is_seed and r.in_kzt == 0:
        s = min(_score(_ramp(r.out_kzt, cfg.term_min_kzt, cfg.term_full_kzt)), cfg.seed_transit_cap)
        ev = (f"Seed: входящие вне выгрузки; отправил {fmt_kzt(r.out_kzt)} {_recips(r.out_deg)} ({_tx(r.out_tx)}) — "
              f"передаёт средства дальше по цепочке")
        return "transit", s, "R4s: seed с исходящими, входящие не наблюдаются", "-", _clip(ev), "not_sink"
    if r.out_deg > 0 and r.in_deg > 0 and (ratio >= cfg.transit_weak_lo or fast >= cfg.fast_share_min):
        if cfg.transit_lo <= ratio <= cfg.transit_hi:
            close = 1.0
        elif ratio > cfg.transit_hi:
            close = max(0.0, 1 - np.log(ratio / cfg.transit_hi) / np.log(10))
        else:
            close = 0.5 * (ratio - cfg.transit_weak_lo) / (cfg.transit_lo - cfg.transit_weak_lo)
        s = round(0.5 + 0.3 * close + 0.2 * fast, 3)
        if r.is_seed:
            s = min(s, cfg.seed_transit_cap)
        if ratio > cfg.transit_hi:
            ratio_txt = f"отправил в {fmt_x(ratio)} больше полученного → есть невидимые входящие"
            rule = f"R4: out/in={ratio:.2f}>{cfg.transit_hi} (невидимые входящие)"
        else:
            ratio_txt = f"дальше ушло {fmt_pct(ratio)}"
            rule = f"R4: out/in={ratio:.2f}" + (f"∈[{cfg.transit_lo};{cfg.transit_hi}]" if ratio >= cfg.transit_lo else f"≥{cfg.transit_weak_lo}")
        ev = f"{_flow_line(r)}; {ratio_txt}"
        if fast > 0:
            ev += f"; {fmt_pct(fast)} полученного ушло за ≤{cfg.fast_lag_days} дн"
        ev += seeds_txt
        return "transit", s, rule, "-", _clip(ev[0].upper() + ev[1:]), "not_sink"

    # ---- R5 terminal (исходящие известны полностью)
    if r.in_deg > 0 and ratio <= cfg.term_max_out_share and (r.in_kzt >= cfg.term_min_kzt or r.in_tx >= cfg.term_min_tx):
        s = _score(_ramp(r.in_kzt, cfg.term_min_kzt, cfg.term_full_kzt), 1 - ratio / cfg.term_max_out_share)
        ev = f"Получил {fmt_kzt(r.in_kzt)} от {_payers(r.in_deg)} ({_tx(r.in_tx)}), дальше ушло {fmt_pct(ratio)}"
        sink = "confirmed_sink"
        rule = f"R5: out/in={ratio:.2f}≤{cfg.term_max_out_share}, in={fmt_kzt(r.in_kzt)}"
        if late:
            s = round(s * cfg.late_penalty, 3)
            ev += f"; {fmt_pct(r.late_in_share)} поступило 30–31 июля — август не виден"
            sink = "truncated_time"
        ev += seeds_txt
        return "terminal", s, rule, "-", _clip(ev), sink

    # ---- R6 peripheral
    s = round(max(0.05, 1 - activity), 3)
    if r.in_deg == 0 and r.out_deg == 0:
        return ("peripheral", 1.0, "R6: нет переводов ≥5 000 ₸", "-",
                "Seed без внутрибанковских переводов ≥5 000 ₸ за июль: 0 входящих и 0 исходящих — данных для роли нет",
                "no_data")
    if r.out_deg == 0:
        ev = f"Разовое поступление: {fmt_kzt(r.in_kzt)} от {_payers(r.in_deg)} ({_tx(r.in_tx)}); дальше не отправлял"
        return ("peripheral", s, f"R6: in={fmt_kzt(r.in_kzt)}<{fmt_kzt(cfg.term_min_kzt)} и 1 перевод", "-", _clip(ev + seeds_txt),
                "truncated_time" if late else "confirmed_sink")
    ev = f"Смешанный профиль: {_flow_line(r)}; дальше ушло {fmt_pct(min(ratio, 1))}"
    return ("peripheral", s, f"R6: out/in={ratio:.2f} между {cfg.term_max_out_share} и {cfg.transit_weak_lo}", "-",
            _clip(ev + seeds_txt), "not_sink")


def role_ru(role: str) -> str:
    return ROLE_META[role]["ru"]


def typologies(role: str, flags: list[str]) -> str:
    """Названия типологий AML для узла: типология роли + rapid movement of funds при быстром транзите."""
    names = [ROLE_META[role]["typology"]] if ROLE_META[role]["typology"] else []
    if "fast_transit" in flags:
        names.append(RAPID_MOVEMENT)
    return "; ".join(names)

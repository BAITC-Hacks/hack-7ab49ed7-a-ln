"""
Приоритет проверки = взвешенная сумма 8 компонент (каждая 0–1) × надёжность данных узла.
Это очерёдность ручной проверки, а не вероятность вины.
"""
import numpy as np
import pandas as pd

from . import config as C
from .texts import ROLE_HYPOTHESIS, kzt, nodes_acc, payers, pct, plural, recipients_dat, seeds

COMPONENT_RU = {
    "money": "прослеживаемые деньги seed",
    "converge": "сходятся деньги нескольких seed",
    "control": "контроль (блокировка отрезает узлы)",
    "collect": "много разных плательщиков",
    "volume": "оборот",
    "bridge": "связующее звено сети",
    "role": "значимая роль",
    "signals": "красные флаги",
}


def _log_scale(x: pd.Series, q=None, unit: float = 1.0) -> pd.Series:
    """log(1 + x/unit) / log(1 + max): суммы меряем в единицах порога выгрузки (5 000 ₸)."""
    lx = np.log1p(x.astype(float).clip(lower=0) / unit)
    top = lx.quantile(q) if q else lx.max()
    return (lx / max(top, 1e-9)).clip(0, 1)


def priority(f: pd.DataFrame) -> pd.DataFrame:
    comp = pd.DataFrame(index=f.index)
    money = _log_scale(f.traced_in_kzt, unit=C.MIN_VISIBLE_KZT)
    seed_out = 0.7 * _log_scale(f.out_kzt, unit=C.MIN_VISIBLE_KZT)      # у seed вход занижен: учитываем их собственный отток
    comp["money"] = np.where(f.is_seed, np.maximum(money, seed_out), money)
    comp["converge"] = (f.seed_sources / 4).clip(0, 1)
    comp["control"] = _log_scale(f.control_nodes)
    comp["collect"] = (f.in_deg / 10).clip(0, 1)
    comp["volume"] = _log_scale(f.in_kzt + f.out_kzt, q=0.99, unit=C.MIN_VISIBLE_KZT)
    bet_pos = f.betweenness[f.betweenness > 0]
    comp["bridge"] = (f.betweenness / max(bet_pos.quantile(0.95) if len(bet_pos) else 1, 1e-12)).clip(0, 1)
    comp["role"] = f.role.map(C.ROLE_WEIGHT) * (0.5 + 0.5 * f.role_score)
    comp["signals"] = f["flags"].apply(lambda fl: sum(x in C.RED_FLAGS for x in fl) / 3).clip(0, 1)
    raw = sum(C.PRIORITY_WEIGHTS[k] * comp[k] for k in C.PRIORITY_WEIGHTS)
    rel = pd.Series(1.0, index=f.index)
    rel[f.is_seed] *= C.SEED_PRIORITY_FACTOR
    rel[f.truncated] *= C.TRUNCATED_PRIORITY_FACTOR
    rel[f.isolated] = C.ISOLATED_PRIORITY_FACTOR
    out = comp.add_prefix("p_").round(4)
    out["priority_raw"] = raw.round(4)
    out["priority_reliability"] = rel
    out["priority_score"] = (raw * rel).clip(0, 1).round(4)
    return out


def why(g, r) -> str:
    """Развёрнутое обоснование позиции в топ-листе: вклад компонент + ключевые числа + следующий шаг."""
    contrib = sorted(((C.PRIORITY_WEIGHTS[k] * r[f"p_{k}"], k) for k in C.PRIORITY_WEIGHTS), reverse=True)[:3]
    parts = [f"Гипотеза: {ROLE_HYPOTHESIS[r.role]} (уверенность {r.role_score:.2f}); приоритет {r.priority_score:.2f}, "
             f"основной вклад: " + ", ".join(f"{COMPONENT_RU[k]} (+{v:.2f})" for v, k in contrib) + "."]
    parts.append(f"Получил {kzt(r.in_kzt)} от {payers(r.in_deg)} ({plural(r.in_tx, 'операция', 'операции', 'операций')}), "
                 f"отправил {kzt(r.out_kzt)} {recipients_dat(r.out_deg)} ({plural(r.out_tx, 'операция', 'операции', 'операций')}).")
    if r.traced_in_kzt > 0:
        parts.append(f"До seed-клиентов прослеживается {kzt(r.traced_in_kzt)} входа ({pct(r.traced_share)}), "
                     f"деньги {seeds(r.seed_sources)}.")
    if r.is_seed:
        parts.append("Узел сам из списка seed: его входящие из-за пределов выгрузки не видны.")
    if r.control_nodes:
        parts.append(f"Блокировка узла отрезает от seed {nodes_acc(r.control_nodes)} с входом {kzt(r.control_kzt)}.")
    if r.betweenness_pct >= C.COORD_LINK_BETWEENNESS:
        parts.append(f"По посредничеству — в верхних {max(1, round(100 * (1 - r.betweenness_pct)))}% узлов своей "
                     f"компоненты; контрагенты из "
                     f"{plural(r.partner_clusters, 'кластера', 'кластеров', 'кластеров')}.")
    if r.fast_transit:
        parts.append(f"{pct(r.fast_2d_share)} суммы пересылалось в течение 0–2 дней после поступлений.")
    if r.sync_max_payers >= C.SYNC_MIN_PAYERS:
        parts.append(f"До {r.sync_max_payers} разных плательщиков в один день ({r.sync_days} таких дн.).")
    if r.dated_returns:
        parts.append(f"Датированных возвратов по циклам 2–3 звена за ≤{C.CYCLE_RETURN_DAYS} дн.: {r.dated_returns}.")
    if r.repeated_routes:
        parts.append(f"Повторяющихся маршрутов A→узел→C: {r.repeated_routes} (на сумму {kzt(r.repeated_route_kzt)}).")
    step = {"coordinator": "запросить полную выписку, проверить связи с seed и роль возможного организатора",
            "consolidator": "проверить источники поступлений и дальнейшее использование накопленных средств",
            "distributor": "проверить получателей веера (выплаты, обналичивание, дропы)",
            "transit": "установить, чьи средства проходят транзитом, и конечного получателя",
            "terminal": "проверить, как расходуются накопленные средства (снятие, покупки, другие банки)",
            "peripheral": "дозагрузить недостающие данные (исходящие, другие банки) перед выводами"}[r.role]
    parts.append(f"Рекомендуется: {step}. Это гипотеза для проверки, не вывод о виновности.")
    return " ".join(parts)

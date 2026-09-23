from pathlib import Path

import pandas as pd

from . import config as C
from .collection import Collection
from .features import ContinuationModel
from .stats import RunStats
from .texts import kzt, pct


def _expanded_phrase(collection: Collection | None) -> str:
    return f"колено ≤{collection.expanded_depth}" if collection else "не последнее колено обхода"


def _last_hop_phrase(collection: Collection | None) -> str:
    return f"последнего ({collection.max_depth}-го) колена" if collection else "последнего колена"


def role_rules_text(collection: Collection | None) -> dict:
    expanded, last_hop = _expanded_phrase(collection), _last_hop_phrase(collection)
    return {
        "coordinator": (
            f"{expanded.capitalize()} и (≥{C.COORD_MIN_PAYERS} плательщиков и ≥{C.COORD_MIN_RECIPIENTS} "
            f"получателей — и собирает, и распределяет; или ≥{C.COORD_ALT_PAYERS} плательщика, деньги "
            f"≥{C.COORD_ALT_SEED_SOURCES} разных seed, выплаты обратно seed и ≥{C.COORD_ALT_MIN_RECIPIENTS} "
            f"получателя) и признак связующего звена: деньги ≥{C.COORD_LINK_SEED_SOURCES} seed, или "
            f"посредничество ≥P{int(C.COORD_LINK_BETWEENNESS * 100)} компоненты, или контрагенты из "
            f"≥{C.COORD_LINK_PARTNER_CLUSTERS} кластеров."
        ),
        "consolidator": (
            f"≥{C.CONS_MIN_PAYERS} разных плательщиков, либо ≥{C.CONS_ALT_PAYERS} плательщика, через которых "
            f"сходятся деньги ≥{C.CONS_ALT_SEED_SOURCES} разных seed (по трассировке); и деньги накапливаются: "
            f"получателей ≤ max({C.CONS_FUNNEL_BASE}, плательщики/{C.CONS_FUNNEL_FACTOR}) или отдал "
            f"≤{pct(C.CONS_RETAIN_MAX_RATIO)} полученного; и узел не веер."
        ),
        "distributor": (
            f"≥{C.DIST_MIN_RECIPIENTS} получателей и получателей ≥{C.DIST_FANOUT_FACTOR}× больше, чем "
            f"плательщиков (веерная рассылка)."
        ),
        "transit": (
            f"Не seed, {expanded}; отдал {pct(C.TRANSIT_RATIO[0])}–{pct(C.TRANSIT_RATIO[1])} полученного "
            f"И пересылка подтверждена по датам (FIFO): ≥{pct(C.FAST_MIN_SHARE)} суммы ушло за 0–{C.FAST_DAYS} "
            f"дня после поступлений и ≥{pct(C.STRICT_FAST_MIN_SHARE)} — строго через 1–{C.FAST_DAYS} дня "
            f"(не только в тот же день)."
        ),
        "terminal": (
            f"{expanded.capitalize()} (исходящие собраны полностью), есть вход, отдал дальше "
            f"≤{pct(C.TERMINAL_MAX_RATIO)} полученного, и после последнего поступления наблюдали "
            f"≥{C.TERMINAL_MIN_FOLLOWUP_DAYS} дней. Узлы {last_hop} конечными не считаются никогда."
        ),
        "peripheral": (
            f"Ни одно правило не выполнено или данных недостаточно: узлы {last_hop} (обрыв обхода), "
            "seed без видимого входа, поступления в последние дни окна наблюдения, баланс транзита без "
            "подтверждения по датам, сбор без накопления, частичное удержание, seed без переводов в выгрузке."
        ),
    }


def data_requests(f: pd.DataFrame, collection: Collection) -> pd.DataFrame:
    rows = []
    t = f[f.truncated & (f.in_kzt > 0)].copy()
    t["value"] = t.p_continue * t.in_kzt
    for g, r in t.sort_values("value", ascending=False).iterrows():
        if r.p_continue >= C.LIKELY_CONTINUES_P or r.in_kzt >= 300_000:
            rows.append(
                (
                    g,
                    f"исходящие переводы ({collection.max_depth + 1}-е колено)",
                    r.value,
                    f"{collection.max_depth}-е колено, получил {kzt(r.in_kzt)}, оценка дальнейших переводов "
                    f"{pct(r.p_continue)} (по аналогии с раскрытыми коленами)",
                )
            )
    for g in f.index[f.isolated]:
        rows.append(
            (
                g,
                "операции в других банках / наличные",
                0.0,
                f"seed без единого перевода ≥{kzt(collection.min_transfer_kzt)} в выгрузке",
            )
        )
    for g, r in f[(f.is_seed) & (f.out_kzt > 0)].sort_values("out_kzt", ascending=False).iterrows():
        rows.append(
            (
                g,
                "входящие seed из-за пределов выгрузки",
                float(r.out_kzt),
                f"seed отправил {kzt(r.out_kzt)}, источник средств не виден",
            )
        )
    sf = f[f["flags"].apply(lambda x: "short_followup" in x)]
    for g, r in sf.sort_values("in_kzt", ascending=False).iterrows():
        rows.append(
            (
                g,
                "операции за август",
                float(r.in_kzt),
                f"получил {kzt(r.in_kzt)} за {r.followup_days} дн. до конца периода — отток мог уйти позже",
            )
        )
    ext = f[f["flags"].apply(lambda x: "external_funds" in x) & (f.priority_score > 0.3)]
    for g, r in ext.sort_values("priority_score", ascending=False).iterrows():
        rows.append(
            (
                g,
                "входящие из других банков/наличные",
                float(r.out_kzt - r.in_kzt),
                f"отдал {kzt(r.out_kzt)} при видимом входе {kzt(r.in_kzt)}",
            )
        )
    df = pd.DataFrame(rows, columns=["gid", "request", "value_kzt", "reason"])
    df["value_kzt"] = df.value_kzt.round(0)
    return df


def _model_section(model: ContinuationModel) -> str:
    if model.status == "insufficient_data":
        return (
            f"**Модель обрыва последнего колена:** недостаточно раскрытых узлов для обучения ({model.n_train}) — "
            f"оценка не строится, узлы обрыва ранжируются только по объёму."
        )
    transfer = (
        f"проверка переноса «ранние колена → последнее раскрытое» AUC = {model.auc_transfer} "
        f"(средний прогноз {model.transfer_mean_pred} при фактической доле {model.transfer_actual_rate}); "
        if model.auc_transfer is not None
        else ""
    )
    coefs = ", ".join(f"`{k}` {v:+}" for k, v in model.coefs.items())
    return (
        f"**Модель обрыва последнего колена** (цель: «после поступления отправил деньги дальше»): "
        f"AUC (кросс-валидация) = {model.auc_cv}; {transfer}доля «передаёт дальше» на раскрытых коленах = "
        f"{model.base_rate}; обучающих узлов {model.n_train}. Это оценка по аналогии, а не проверенная "
        f"вероятность. Коэффициенты (стандартизованные): {coefs}."
    )


def _resilience_section(resilience_rows: pd.DataFrame) -> list[str]:
    lines = [
        "## Устойчивость сети",
        "",
        "Удаляем топ-N не-seed узлов по приоритету и сравниваем со случайным удалением N узлов (среднее "
        f"{C.RESILIENCE_RANDOM_TRIALS} прогонов): доля узлов, достижимых от seed, и доля оборота, идущего к ним.",
        "",
        "| N | достижимо (топ) | оборот (топ) | компонент (топ) | достижимо (случ.) | оборот (случ.) |",
        "|---|---|---|---|---|---|",
    ]
    return lines + [
        f"| {r.removed_top_n} | {r.reach_top:.1%} | {r.flow_top:.1%} | {r.components_top} | "
        f"{r.reach_random:.1%} | {r.flow_random:.1%} |"
        for r in resilience_rows.itertuples()
    ]


def write_run_report(out: Path, stats: RunStats, resilience_rows: pd.DataFrame, clusters: pd.DataFrame) -> None:
    lines = [
        "# Отчёт прогона\n",
        f"Время полного пересчёта: **{stats.runtime_s} с**. Узлов {stats.summary['n_nodes']}, рёбер "
        f"{stats.summary['n_edges']}, транзакций {stats.summary['n_tx']}, кластеров {stats.n_clusters}.\n",
        "| Роль | Узлов |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in stats.roles.items()]
    lines += [
        "",
        _model_section(stats.model),
        "",
        f"**Циклы:** коротких (2–3 звена) {stats.cycles['short_cycles']}, из них датированных возвратов "
        f"{stats.cycles['dated_cycles']}.",
        "",
        "**Флаги:** " + ", ".join(f"`{k}` {v}" for k, v in stats.flags.items()) + ".",
        "",
    ]
    lines += _resilience_section(resilience_rows)
    lines += ["", "## Запросы на дозагрузку данных", ""] + [f"- {k}: {v}" for k, v in stats.data_requests.items()]
    lines += ["", "## Кластеры с seed (по убыванию максимального приоритета)", ""]
    for r in clusters[clusters.n_seed > 0].sort_values("max_priority", ascending=False).head(12).itertuples():
        lines.append(f"- **{r.cluster_id}** ({r.n_nodes} узлов, {r.n_seed} seed): {r.hypothesis}")
    (out / "run_report.md").write_text("\n".join(lines) + "\n")

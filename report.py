"""Тексты правил, запросы на дозагрузку данных, отчёт прогона и механическая проверка схемы."""
from pathlib import Path

import pandas as pd

from . import config as C
from .texts import kzt, pct


def role_rules_text() -> dict:
    """Человекочитаемые правила с фактическими порогами (показываются в экране «Методика»)."""
    return {
        "coordinator": (f"Колено ≤{C.MAX_EXPANDED_DEPTH} и (≥{C.COORD_MIN_PAYERS} плательщиков и ≥{C.COORD_MIN_RECIPIENTS} "
                        f"получателей — и собирает, и распределяет; или ≥{C.COORD_ALT_PAYERS} плательщика, деньги "
                        f"≥{C.COORD_ALT_SEED_SOURCES} разных seed, выплаты обратно seed и ≥{C.COORD_ALT_MIN_RECIPIENTS} "
                        f"получателя) и признак связующего звена: "
                        f"деньги ≥{C.COORD_LINK_SEED_SOURCES} seed, или посредничество ≥P{int(C.COORD_LINK_BETWEENNESS * 100)} "
                        f"компоненты, или контрагенты из ≥{C.COORD_LINK_PARTNER_CLUSTERS} кластеров."),
        "consolidator": (f"≥{C.CONS_MIN_PAYERS} разных плательщиков, либо ≥{C.CONS_ALT_PAYERS} плательщика, через которых "
                         f"сходятся деньги ≥{C.CONS_ALT_SEED_SOURCES} разных seed (по трассировке); и деньги накапливаются: "
                         f"получателей ≤ max({C.CONS_FUNNEL_BASE}, плательщики/{C.CONS_FUNNEL_FACTOR}) или отдал "
                         f"≤{pct(C.CONS_RETAIN_MAX_RATIO)} полученного; и узел не веер."),
        "distributor": (f"≥{C.DIST_MIN_RECIPIENTS} получателей и получателей ≥{C.DIST_FANOUT_FACTOR}× больше, чем "
                        f"плательщиков (веерная рассылка)."),
        "transit": (f"Не seed, колено ≤{C.MAX_EXPANDED_DEPTH}; отдал {pct(C.TRANSIT_RATIO[0])}–{pct(C.TRANSIT_RATIO[1])} "
                    f"полученного И пересылка подтверждена по датам (FIFO): ≥{pct(C.FAST_MIN_SHARE)} суммы ушло за "
                    f"0–{C.FAST_DAYS} дня после поступлений и ≥{pct(C.STRICT_FAST_MIN_SHARE)} — строго через "
                    f"1–{C.FAST_DAYS} дня (не только в тот же день)."),
        "terminal": (f"Колено ≤{C.MAX_EXPANDED_DEPTH} (исходящие собраны полностью), есть вход, отдал дальше "
                     f"≤{pct(C.TERMINAL_MAX_RATIO)} полученного, и после последнего поступления наблюдали "
                     f"≥{C.TERMINAL_MIN_FOLLOWUP_DAYS} дней. Узлы 4-го колена конечными не считаются никогда."),
        "peripheral": ("Ни одно правило не выполнено или данных недостаточно: узлы 4-го колена (обрыв обхода), "
                       "seed без видимого входа, поступления в последние дни июля, баланс транзита без подтверждения "
                       "по датам, сбор без накопления, частичное удержание, seed без переводов в выгрузке."),
    }


def data_requests(f: pd.DataFrame) -> pd.DataFrame:
    """Оценка полноты: каких данных не хватает и какой запрос сделать следующим (по убыванию пользы)."""
    rows = []
    t = f[f.truncated & (f.in_kzt > 0)].copy()
    t["value"] = t.p_continue * t.in_kzt
    for g, r in t.sort_values("value", ascending=False).iterrows():
        if r.p_continue >= C.LIKELY_CONTINUES_P or r.in_kzt >= 300_000:
            rows.append((g, "исходящие переводы (5-е колено)", r.value,
                         f"4-е колено, получил {kzt(r.in_kzt)}, оценка дальнейших переводов {pct(r.p_continue)} (по аналогии с коленами 1–3)"))
    for g, r in f[f.isolated].iterrows():
        rows.append((g, "операции в других банках / наличные", 0.0,
                     "seed без единого перевода ≥5 000 ₸ внутри банка за июль"))
    for g, r in f[(f.is_seed) & (f.out_kzt > 0)].sort_values("out_kzt", ascending=False).iterrows():
        rows.append((g, "входящие seed из-за пределов выгрузки", float(r.out_kzt),
                     f"seed отправил {kzt(r.out_kzt)}, источник средств не виден"))
    sf = f[f["flags"].apply(lambda x: "short_followup" in x)]
    for g, r in sf.sort_values("in_kzt", ascending=False).iterrows():
        rows.append((g, "операции за август", float(r.in_kzt),
                     f"получил {kzt(r.in_kzt)} за {r.followup_days} дн. до конца периода — отток мог уйти позже"))
    ext = f[f["flags"].apply(lambda x: "external_funds" in x) & (f.priority_score > 0.3)]
    for g, r in ext.sort_values("priority_score", ascending=False).iterrows():
        rows.append((g, "входящие из других банков/наличные", float(r.out_kzt - r.in_kzt),
                     f"отдал {kzt(r.out_kzt)} при видимом входе {kzt(r.in_kzt)}"))
    df = pd.DataFrame(rows, columns=["gid", "request", "value_kzt", "reason"])
    df["value_kzt"] = df.value_kzt.round(0)
    return df


def write_run_report(out: Path, stats: dict, res: pd.DataFrame, clusters: pd.DataFrame):
    tm = stats["truncation_model"]
    L = ["# Отчёт прогона\n",
         f"Время полного пересчёта: **{stats['runtime_s']} с**. Узлов {stats['data']['nodes']}, рёбер "
         f"{stats['data']['edges']}, транзакций {stats['data']['transactions']}, кластеров {stats['n_clusters']}.\n",
         "| Роль | Узлов |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in stats["roles"].items()]
    L += ["", f"**Модель обрыва 4-го колена** (цель: «после поступления отправил деньги дальше»): AUC (5-fold CV) = "
          f"{tm['auc_cv']}; проверка переноса «обучение на коленах 1–2 → проверка на 3-м» AUC = "
          f"{tm['auc_transfer_d12_to_d3']} (средний прогноз {tm['d3_mean_pred']} при фактической доле "
          f"{tm['d3_actual_rate']}); доля «передаёт дальше» на коленах 1–3 = {tm['base_rate']}; обучающих узлов "
          f"{tm['n_train']}. Это оценка по аналогии, а не проверенная вероятность. Коэффициенты (стандартизованные): "
          + ", ".join(f"`{k}` {v:+}" for k, v in tm["coefs"].items()) + ".", "",
          f"**Циклы:** коротких (2–3 звена) {stats['cycles']['short_cycles']}, из них датированных возвратов "
          f"{stats['cycles']['dated_cycles']}.", "",
          "**Флаги:** " + ", ".join(f"`{k}` {v}" for k, v in stats["flags"].items()) + ".", "",
          "## Устойчивость сети", "",
          "Удаляем топ-N не-seed узлов по приоритету и сравниваем со случайным удалением N узлов (среднее "
          f"{C.RESILIENCE_RANDOM_TRIALS} прогонов): доля узлов, достижимых от seed, и доля оборота, идущего к ним.", "",
          "| N | достижимо (топ) | оборот (топ) | компонент (топ) | достижимо (случ.) | оборот (случ.) |",
          "|---|---|---|---|---|---|"]
    L += [f"| {r.removed_top_n} | {r.reach_top:.1%} | {r.flow_top:.1%} | {r.components_top} | {r.reach_random:.1%} | "
          f"{r.flow_random:.1%} |" for r in res.itertuples()]
    L += ["", "## Запросы на дозагрузку данных", ""]
    L += [f"- {k}: {v}" for k, v in stats["data_requests"].items()]
    L += ["", "## Кластеры с seed (по убыванию максимального приоритета)", ""]
    for r in clusters[clusters.n_seed > 0].sort_values("max_priority", ascending=False).head(12).itertuples():
        L.append(f"- **{r.cluster_id}** ({r.n_nodes} узлов, {r.n_seed} seed): {r.hypothesis}")
    (out / "run_report.md").write_text("\n".join(L) + "\n")


def validate(out: Path, nodes: pd.DataFrame):
    r = pd.read_csv(out / "nodes_roles.csv")
    req = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
    assert list(r.columns[:6]) == req, "порядок обязательных колонок"
    assert len(r) == C.EXPECTED_NODES and r.gid.nunique() == C.EXPECTED_NODES, "должно быть 2248 уникальных gid"
    assert set(r.gid) == set(nodes.gid), "gid не совпадают с nodes.parquet"
    assert r[req].notna().all().all() and (r.evidence.str.len() > 0).all(), "пустые обязательные поля"
    assert r.role.isin(C.ROLES).all(), "роль вне словаря"
    assert r.role_score.between(0, 1).all() and r.priority_score.between(0, 1).all(), "скор вне [0,1]"
    assert (r.evidence.str.len() <= 200).all(), "evidence длиннее 200 символов"
    assert r.evidence.str.contains(r"\d").all(), "evidence без чисел"
    first = (out / "nodes_roles.csv").read_text().splitlines()[1].split(",")[0]
    assert first.isdigit() and len(first) == 18, "gid должен быть записан целым 18-значным числом"
    c = pd.read_csv(out / "clusters.csv")
    assert list(c.columns[:6]) == ["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"]
    assert set(r.cluster_id) == set(c.cluster_id) and c.n_nodes.sum() == C.EXPECTED_NODES
    assert c.hypothesis.notna().all()
    t = pd.read_csv(out / "top_nodes.csv")
    assert list(t.columns[:5]) == ["rank", "gid", "role", "priority_score", "why"]
    assert len(t) >= 20 and t["rank"].is_monotonic_increasing and t.priority_score.is_monotonic_decreasing

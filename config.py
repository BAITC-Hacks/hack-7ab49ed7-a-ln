"""Все пороги и веса в одном месте. Любое правило роли ссылается только на эти константы."""

EXPECTED_NODES = 2248
RANDOM_SEED = 42

# --- устройство выгрузки
MAX_EXPANDED_DEPTH = 3          # колена 0..3 раскрыты обходом → их исходящие собраны полностью
OBSERVATION_START = "2026-07-01"
OBSERVATION_END = "2026-07-31"
MIN_VISIBLE_KZT = 5_000         # порог выгрузки; всё, что ниже, невидимо

# --- трассировка денег seed (хронологический haircut)
SEED_SOURCE_MIN_KZT = MIN_VISIBLE_KZT   # seed — «источник» узла, если от него прослеживается ≥5 000 ₸
SEED_MIX_MIN_KZT = 50_000

# --- роли (проверяются по порядку, первое сработавшее правило задаёт роль)
COORD_MIN_PAYERS = 5            # координатор: собирает от ≥5 плательщиков
COORD_MIN_RECIPIENTS = 10       # и рассылает ≥10 получателям
COORD_ALT_PAYERS = 3            # или: ≥3 плательщика, деньги ≥3 разных seed и платит обратно seed
COORD_ALT_SEED_SOURCES = 3
COORD_ALT_MIN_RECIPIENTS = 2    #   (и сам рассылает ≥2 получателям)
COORD_LINK_SEED_SOURCES = 2     # плюс хотя бы один признак связующего звена:
COORD_LINK_BETWEENNESS = 0.90   #   деньги ≥2 seed, или посредничество ≥ P90 компоненты,
COORD_LINK_PARTNER_CLUSTERS = 3 #   или контрагенты из ≥3 кластеров

CONS_MIN_PAYERS = 5             # консолидатор: ≥5 разных плательщиков
CONS_ALT_PAYERS = 3             # или ≥3 плательщика, если сходятся деньги ≥3 разных seed
CONS_ALT_SEED_SOURCES = 3
CONS_FUNNEL_BASE = 2            # и деньги «сужаются»: получателей ≤ max(2, плательщики/3)
CONS_FUNNEL_FACTOR = 3
CONS_RETAIN_MAX_RATIO = 0.8     #   или узел удерживает ≥20% видимого входа (отдал ≤80%)

DIST_MIN_RECIPIENTS = 10        # распределитель: ≥10 получателей
DIST_FANOUT_FACTOR = 2          # и получателей ≥ 2× больше, чем плательщиков

TRANSIT_RATIO = (0.5, 1.5)      # транзит: отдал 50–150% полученного (ядро 80–120%)
                                # И ОБЯЗАТЕЛЬНО пересылка подтверждена по датам (fast_transit)
FAST_DAYS = 2                   # «сквозной»: вышло в течение 0–2 дней после поступления
FAST_MIN_SHARE = 0.5            # ≥50% max(вход, выход) сопоставлено за 0–2 дня
STRICT_FAST_MIN_SHARE = 0.25    # и ≥25% — строго через 1–2 дня (не только в тот же день)

TERMINAL_MAX_RATIO = 0.2        # конечный: отдал дальше ≤20% полученного
TERMINAL_MIN_FOLLOWUP_DAYS = 7  # и после последнего поступления наблюдали ≥7 дней

# --- флаги
SYNC_MIN_PAYERS = 3             # ≥3 разных плательщика в один день
BURST_MIN_TX = 5                # ≥5 операций в пиковый день и ≥50% всех операций узла
BURST_MIN_SHARE = 0.5
SPLIT_MIN_TX = 3                # ≥3 перевода одному контрагенту в один день
SMALL_UPPER_KZT = 2 * MIN_VISIBLE_KZT   # [5 000; 10 000) — повтор сумм у порога видимости
SMALL_MIN_TX = 5
SMALL_MIN_SHARE = 0.5
REPEATED_ROUTE_MIN_DAYS = 2     # A→B→C через FIFO ≤2 дня, на ≥2 разных датах входа и выхода
CYCLE_MAX_LENGTH = 3            # короткие циклы 2–3 звена
CYCLE_RETURN_DAYS = 7           # цикл «датированный»: каждое звено позже предыдущего, всё за ≤7 дней
HOP_ANOMALY_MIN_Z = 3.5         # робастный z относительно узлов своего колена
ROBUST_SCALE_FLOOR = 0.25
BOTTLENECK_MIN_NODES = 20       # блокировка отрезает от seed ≥20 узлов
BETWEENNESS_SAMPLES = 128
LIKELY_CONTINUES_P = 0.5

# --- кластеры
LOUVAIN_RESOLUTION = 1.0

# --- приоритет: веса компонент (сумма = 1)
PRIORITY_WEIGHTS = {
    "money": 0.15,      # сколько денег seed прослеживается до узла
    "converge": 0.15,   # деньги скольких разных seed сходятся в узле
    "control": 0.15,    # сколько узлов отрежет блокировка (дерево доминаторов)
    "collect": 0.10,    # число разных плательщиков
    "volume": 0.10,     # видимый оборот узла
    "bridge": 0.10,     # посредничество между частями сети
    "role": 0.15,       # вес роли × уверенность
    "signals": 0.10,    # временные и структурные красные флаги
}
ROLE_WEIGHT = {"coordinator": 1.0, "consolidator": 1.0, "distributor": 0.8,
               "transit": 0.7, "terminal": 0.35, "peripheral": 0.1}
RED_FLAGS = ("fast_transit", "sync_inflow", "burst", "structuring", "small_amounts",
             "dated_return", "repeated_route", "hop_anomaly")
SEED_PRIORITY_FACTOR = 0.85     # seed уже известны правоохранителям → фокус на новых участниках
TRUNCATED_PRIORITY_FACTOR = 0.75
ISOLATED_PRIORITY_FACTOR = 0.0
TOP_N = 50

RESILIENCE_N = (5, 10, 20, 50)
RESILIENCE_RANDOM_TRIALS = 20

ROLES = ("coordinator", "consolidator", "distributor", "transit", "terminal", "peripheral")

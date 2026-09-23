"""Все пороги и веса в одном месте. README ссылается на эти значения; меняйте здесь, а не в коде правил."""

from __future__ import annotations

from dataclasses import dataclass, field

ROLES = ["coordinator", "consolidator", "distributor", "transit", "terminal", "peripheral"]

ROLE_META = {
    # Цвета проверены валидатором палитры (all-pairs, светлый фон): различимы при обычном зрении,
    # для дальтоников пара красный/зелёный подкреплена подписями ролей в легенде, подсказке и карточке.
    "coordinator": {"ru": "Координатор", "color": "#e34948", "typology": "",
                    "description": "координирующий узел, кандидат в организаторы",
                    "rule": "Собирает от ≥8 и отправляет ≥20 разным клиентам; или платит ≥3 разным seed; "
                            "или служит мостом между ≥4 кластерами с seed (посредничество в топ-1%)."},
    "consolidator": {"ru": "Консолидатор", "color": "#eda100", "typology": "funnel account (воронка)",
                     "description": "точка консолидации — аккумулирует средства от нескольких участников",
                     "rule": "≥4 разных плательщика или ≥2 seed среди плательщиков. Правило опирается только на "
                             "входящие, поэтому работает и для 4-го колена."},
    "distributor": {"ru": "Распределитель", "color": "#4a3aa7", "typology": "fan-out payouts",
                    "description": "веерное распределение средств на много получателей",
                    "rule": "≥10 получателей, и получателей минимум втрое больше, чем плательщиков."},
    "transit": {"ru": "Транзит", "color": "#2a78d6", "typology": "pass-through / money mule layering",
                "description": "транзитный счёт — пропускает средства дальше, не удерживая",
                "rule": "Есть и вход, и выход; отправлено ≥50% полученного или ≥80% ушло дальше за ≤2 дня. "
                        "Уверенность максимальна, когда отправлено 80–120%. На 4-м колене — если похожие узлы "
                        "колен 1–3 пересылают дальше в ≥50% случаев."},
    "terminal": {"ru": "Конечный получатель", "color": "#008300", "typology": "",
                 "description": "деньги приходят и остаются",
                 "rule": "Исходящие известны (колено ≤3), дальше ушло ≤10%, получено ≥30 тыс ₸ или ≥2 перевода. "
                         "На 4-м колене — если похожие узлы пересылают дальше реже чем в 50% случаев."},
    "peripheral": {"ru": "Периферия", "color": "#a0a9b1", "typology": "",
                   "description": "признаков роли не выявлено",
                   "rule": "Всё остальное: разовый мелкий перевод, смешанный профиль, клиенты без переводов."},
}

# Типология AML для флага быстрого транзита (добавляется к типологии роли)
RAPID_MOVEMENT = "rapid movement of funds"

FLAG_RU = {
    "fast_transit": "rapid movement of funds: ушло дальше за ≤2 дн",
    "burst_in": "синхронные поступления от нескольких плательщиков в один день",
    "burst_out": "веерная рассылка многим получателям в один день",
    "in_cycle": "участвует в возвратном потоке (цикле)",
    "repeat_route": "устойчивый повторяющийся маршрут A→B→C",
    "repeat_amounts": "повторяющиеся одинаковые суммы",
    "anomaly": "аномальный профиль относительно своего колена",
    "unseen_inflow": "отдаёт больше, чем получил в выборке (невидимые входящие)",
    "late_inflow": "основные поступления 30–31 июля (продолжение в августе не видно)",
    "truncated": "4-е колено: исходящие не выгружены",
}


@dataclass(frozen=True)
class Config:
    # --- устройство выгрузки
    max_observed_out_depth: int = 3        # исходящие полностью известны только для колен 0–3
    period_end: str = "2026-07-31"
    late_days: int = 2                     # поступления в последние 2 дня периода → «обрыв по времени»
    late_share: float = 0.5                # ...если на них приходится ≥50% входящей суммы
    fast_lag_days: int = 2                 # «сквозной транзит»: ушло дальше за 0–2 дня

    # --- R1 coordinator
    hub_min_in: int = 8                    # хаб: собирает от ≥8 ...
    hub_min_out: int = 20                  # ... и раздаёт ≥20
    coord_min_seed_payees: int = 3         # платит ≥3 разным seed
    bridge_btw_quantile: float = 0.99      # мост: посредничество в топ-1% ...
    bridge_min_seed_clusters: int = 4      # ... и соседи в ≥4 кластерах, где есть seed

    # --- R2 distributor
    distr_min_out: int = 10
    distr_fan_ratio: float = 3.0           # получателей ≥3× больше, чем плательщиков
    distr_strong_out: int = 60

    # --- R3 consolidator
    cons_min_in: int = 4
    cons_min_seed_payers: int = 2
    cons_strong_in: int = 15

    # --- R4 transit
    transit_lo: float = 0.8
    transit_hi: float = 1.2
    transit_weak_lo: float = 0.5
    fast_share_min: float = 0.8
    seed_transit_cap: float = 0.6

    # --- R5 terminal
    term_min_kzt: float = 30_000.0         # ≈ медиана суммы по ребру (45 тыс.) / чуть выше медианы перевода (30 тыс.)
    term_min_tx: int = 2
    term_max_out_share: float = 0.10
    late_penalty: float = 0.6

    # --- 4-е колено (обрыв обхода)
    trunc_forward_cut: float = 0.5
    trunc_transit_cap: float = 0.6
    p_forward_prior: float = 10.0          # сила сглаживания Beta к общей доле пересылающих

    # --- приоритет
    w_role: float = 0.35
    w_flow: float = 0.25
    w_central: float = 0.20
    w_seed: float = 0.10
    w_flags: float = 0.10
    seed_discount: float = 0.9             # seed уже известны правоохранителям — поднимаем новые узлы
    role_weight: dict = field(default_factory=lambda: {
        "coordinator": 1.0, "consolidator": 0.9, "distributor": 0.8,
        "transit": 0.6, "terminal": 0.5, "peripheral": 0.1})
    top_n: int = 50

    # --- кластеры
    louvain_seed: int = 42
    louvain_resolution: float = 1.0
    stability_runs: int = 10

    # --- временные паттерны и аномалии
    burst_in_payers: int = 3
    burst_out_recipients: int = 5
    route_min_dates: int = 2
    repeat_amount_min: int = 3
    anomaly_z: float = 3.5
    cycle_max_len: int = 5


CFG = Config()

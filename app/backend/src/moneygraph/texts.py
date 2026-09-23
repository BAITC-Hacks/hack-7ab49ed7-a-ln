ROLE_RU = {
    "coordinator": "Координатор",
    "consolidator": "Точка консолидации",
    "distributor": "Распределитель",
    "transit": "Транзит",
    "terminal": "Конечный получатель",
    "peripheral": "Периферия",
}

ROLE_HYPOTHESIS = {
    "coordinator": "кандидат в координаторы",
    "consolidator": "точка консолидации",
    "distributor": "распределитель",
    "transit": "транзитный узел",
    "terminal": "конечный получатель (в видимом контуре)",
    "peripheral": "периферия",
}

ROLE_COLORS = {
    "coordinator": "#e6007e",
    "consolidator": "#d62728",
    "distributor": "#9467bd",
    "transit": "#ff7f0e",
    "terminal": "#8c564b",
    "peripheral": "#9e9e9e",
}

FLAG_RU = {
    "seed": "Seed-клиент (исходный список)",
    "isolated": "Нет переводов в выгрузке (выше порога суммы)",
    "truncated": "Обрыв обхода на последнем колене: исходящие не выгружались",
    "likely_continues": "Вероятно, цепочка продолжается — нужна дозагрузка",
    "short_followup": "Поступления в последние дни июля: вывод об оседании отложен",
    "external_funds": "Отдаёт заметно больше видимого входа (есть внешние средства)",
    "collector": "Сбор от многих плательщиков без накопления (много получателей)",
    "fast_transit": "Сквозной транзит: вышло в течение 0–2 дней после поступлений",
    "sync_inflow": "Синхронные поступления от ≥3 плательщиков в один день",
    "burst": "Всплеск: ≥5 операций и ≥50% активности за один день",
    "structuring": "Дробление: ≥3 перевода одному контрагенту за день",
    "small_amounts": "Повтор малых сумм у порога видимости (5–10 тыс ₸)",
    "cycle": "В сильно связной компоненте (деньги могут вернуться)",
    "dated_return": "Датированный возврат: цикл 2–3 звена замкнулся за ≤7 дней",
    "return_to_seed": "Платит seed-клиентам и получает деньги от seed",
    "repeated_route": "Повторяющийся маршрут A→узел→C (≥2 разные даты)",
    "hop_anomaly": "Аномальный профиль относительно узлов своего колена",
    "bottleneck": "Узкое место: блокировка отрезает от seed ≥20 узлов",
    "bridge": "Связующее звено: посредничество ≥ P90 компоненты",
}


def kzt(x: float) -> str:
    x = float(x)
    if abs(x) >= 1e6:
        return f"{x / 1e6:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " млн ₸"
    if abs(x) >= 1e3:
        return f"{x / 1e3:.0f} тыс ₸"
    return f"{x:.0f} ₸"


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def plural(n, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def operations(n) -> str:
    return plural(n, "операция", "операции", "операций")


def payers(n) -> str:
    return plural(n, "плательщика", "плательщиков", "плательщиков")


def payers_nom(n) -> str:
    return plural(n, "плательщик", "плательщика", "плательщиков")


def recipients_dat(n) -> str:
    return plural(n, "получателю", "получателям", "получателям")


def recipients_nom(n) -> str:
    return plural(n, "получатель", "получателя", "получателей")


def seeds(n) -> str:
    return plural(n, "seed", "разных seed", "разных seed")


def nodes_acc(n) -> str:
    return plural(n, "узел", "узла", "узлов")


def fit_text(parts, limit: int = 200, sep: str = "; ") -> str:
    out = parts[0]
    for p in parts[1:]:
        if p and len(out) + len(sep) + len(p) <= limit:
            out += sep + p
    if len(out) > limit:
        out = out[: limit - 1].rstrip() + "…"
    return out

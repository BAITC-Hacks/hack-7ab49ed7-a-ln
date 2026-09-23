import re
from dataclasses import dataclass
from itertools import pairwise

from moneygraph.texts import ROLE_HYPOTHESIS, ROLE_RU, kzt

from ..analytics import graphops
from ..analytics.store import RunData
from ..analytics.views import node_detail
from .answers import Answer, citation, label, resolve_mentions, suggestions

REACHABILITY_WARNING = "Достижимость по графу переводов не доказывает движение одних и тех же денег."
MAX_HOPS = 4
_ROLE_WORDS = (
    ("координатор", "coordinator"),
    ("организатор", "coordinator"),
    ("консолидат", "consolidator"),
    ("сборщик", "consolidator"),
    ("распределит", "distributor"),
    ("веер", "distributor"),
    ("транзит", "transit"),
    ("конечн", "terminal"),
    ("терминал", "terminal"),
    ("перифер", "peripheral"),
    *((role, role) for role in ROLE_RU),
)


@dataclass(frozen=True)
class Question:
    text: str
    ids: list[int]


def _top(data: RunData, q: Question) -> Answer | None:
    match = re.search(r"топ\s*-?\s*(\d+)?", q.text)
    if not match or q.ids:
        return None
    n = min(int(match.group(1) or 10), 50)
    role = next((key for word, key in _ROLE_WORDS if word in q.text), None)
    df = data.nodes if role is None else data.nodes[data.nodes.role == role]
    rows = df.sort_values(["priority_score", "gid"], ascending=[False, True]).head(n)
    title = f"Топ-{len(rows)}" + (f" — {ROLE_RU[role].lower()}" if role else " по приоритету")
    lines = [f"**{title}** (из {len(df)}):"] + [
        f"{i}. {label(data, g)} — {r.evidence}" for i, (g, r) in enumerate(rows.iterrows(), 1)
    ]
    ids = [str(g) for g in rows.index]
    return Answer(
        "top",
        "\n".join(lines),
        citations=[citation(data, g) for g in rows.index],
        actions=[{"type": "highlight", "ids": ids, "label": title}],
        highlight_nodes=ids,
    )


def _collectors(data: RunData, q: Question) -> Answer | None:
    if not re.search(r"кто\s+собира|общ\w*\s+получател|где\s+сход|куда\s+сход", q.text):
        return None
    if not q.ids:
        return Answer("collectors", "Укажите хотя бы один идентификатор клиента.")
    found = graphops.collectors(data, q.ids, MAX_HOPS)
    if not found:
        return Answer("collectors", f"В пределах {MAX_HOPS} переходов общих получателей у заданных узлов нет.")
    lines = [f"**Общие получатели** для {len(q.ids)} узлов (≤ {MAX_HOPS} перехода по направлению переводов):"]
    nodes, edges = [str(i) for i in q.ids], []
    for i, c in enumerate(found[:10], 1):
        lines.append(f"{i}. {label(data, c.gid)} — достижим от {c.coverage} из {len(q.ids)}")
        for path in c.paths:
            nodes += path
            edges += [[a, b] for a, b in pairwise(path)]
    return Answer(
        "collectors",
        "\n".join(lines),
        citations=[citation(data, c.gid, f"покрытие {c.coverage}") for c in found[:10]],
        actions=[{"type": "highlight", "ids": nodes, "label": "Пути к общим получателям"}],
        highlight_nodes=nodes,
        highlight_edges=edges,
        warnings=[REACHABILITY_WARNING],
    )


def _path(data: RunData, q: Question) -> Answer | None:
    if not re.search(r"путь|связ\w*\s+между|как\s+связан", q.text):
        return None
    if len(q.ids) < 2:
        return Answer("path", "Для пути нужны два идентификатора: «путь от A к B».")
    result = graphops.shortest_path(data, q.ids[0], q.ids[1])
    if not result["found"]:
        return Answer("path", f"Связи между `{q.ids[0]}` и `{q.ids[1]}` в выгрузке нет.")
    lines = [f"**Кратчайший {'направленный ' if result['directed'] else ''}путь** из {len(result['nodes']) - 1} шагов:"]
    lines += [
        f"- `{e['source']}` → `{e['target']}`: {kzt(e['sum_kzt'])}, {e['n_tx']} оп., "
        f"{e['first_date']} — {e['last_date']}"
        for e in result["edges"]
    ]
    warnings = [] if result["directed"] else ["Направленного пути нет — показан путь без учёта направления переводов."]
    warnings.append("Порядок дат по звеньям не проверяется: это связь по графу, а не доказанный маршрут денег.")
    return Answer(
        "path",
        "\n".join(lines),
        citations=[citation(data, int(n)) for n in result["nodes"]],
        actions=[{"type": "path", "ids": result["nodes"], "label": "Путь"}],
        highlight_nodes=result["nodes"],
        highlight_edges=[[e["source"], e["target"]] for e in result["edges"]],
        warnings=warnings,
    )


def _trace(data: RunData, gid: int, direction: str) -> Answer:
    sub = graphops.trace(data, gid, direction, MAX_HOPS, 400)
    ids = [int(n["id"]) for n in sub["nodes"]]
    seeds = [g for g in ids if g != gid and bool(data.nodes.is_seed.at[g])]
    ranked = [g for g in graphops.by_priority(data, ids) if g != gid][:10]
    if direction == "up":
        head = (
            f"**Откуда деньги у `{gid}`**: {len(ids) - 1} узлов выше по потоку (≤ {MAX_HOPS} перехода), "
            f"из них seed: {len(seeds)}."
        )
    else:
        head = f"**Куда ушли деньги `{gid}`**: {len(ids) - 1} узлов ниже по потоку (≤ {MAX_HOPS} перехода)."
    lines = [head] + (["Seed-источники: " + ", ".join(f"`{s}`" for s in seeds[:10])] if seeds else [])
    lines += ["Ключевые узлы по приоритету:"] + [f"- {label(data, g)}" for g in ranked]
    warnings = [f"Показано {len(ids)} из {sub['total_nodes']} узлов."] if sub["truncated"] else []
    node_ids = [n["id"] for n in sub["nodes"]]
    return Answer(
        "trace_up" if direction == "up" else "trace_down",
        "\n".join(lines),
        citations=[citation(data, g) for g in ranked],
        actions=[
            {"type": "highlight", "ids": node_ids, "label": "Откуда деньги" if direction == "up" else "Куда ушли"}
        ],
        highlight_nodes=node_ids,
        highlight_edges=[[e["source"], e["target"]] for e in sub["edges"]],
        warnings=warnings + [REACHABILITY_WARNING],
    )


def _sources(data: RunData, q: Question) -> Answer | None:
    if q.ids and re.search(r"откуда|источник|кто\s+(платил|переводил)", q.text):
        return _trace(data, q.ids[0], "up")
    return None


def _destinations(data: RunData, q: Question) -> Answer | None:
    if q.ids and re.search(r"куда\s+(ушл|ид|уход|переводил)|кому\s+(платил|переводил)", q.text):
        return _trace(data, q.ids[0], "down")
    return None


def _cluster(data: RunData, q: Question) -> Answer | None:
    if "кластер" not in q.text:
        return None
    number = re.search(r"кластер\w*\s*№?\s*(\d{1,5})(?!\d)", q.text)
    cluster_id = int(data.nodes.cluster_id.at[q.ids[0]]) if q.ids else int(number.group(1)) if number else None
    cluster = next((c for c in data.clusters if c["cluster_id"] == cluster_id), None)
    if cluster is None:
        return Answer("cluster", "Укажите номер кластера или идентификатор узла из него.")
    members = data.nodes[data.nodes.cluster_id == cluster_id].sort_values("priority_score", ascending=False)
    markdown = (
        f"**Кластер {cluster_id}**: {cluster['n_nodes']} узлов, seed {cluster['n_seed']}, внутренний оборот "
        f"{kzt(cluster['sum_kzt_internal'])}.\n\n{cluster['hypothesis']}\n\nКлючевые узлы:\n"
        + "\n".join(f"- {label(data, g)}" for g in members.index[:10])
    )
    ids = [str(g) for g in members.index[:300]]
    return Answer(
        "cluster",
        markdown,
        citations=[citation(data, g) for g in members.index[:10]],
        actions=[{"type": "highlight", "ids": ids, "label": f"Кластер {cluster_id}"}],
        highlight_nodes=ids,
    )


def _explain(data: RunData, q: Question) -> Answer | None:
    if not q.ids:
        return None
    gid = q.ids[0]
    d = node_detail(data, gid)
    rules = ", ".join(k for k, v in d["rules"].items() if v) or "ни одно правило роли"
    components = sorted(d["priority_components"], key=lambda c: -c["contribution"])[:3]
    markdown = (
        f"**{gid}** — {ROLE_HYPOTHESIS[d['role']]} (уверенность {d['role_score']:.2f}), приоритет "
        f"{d['priority_score']:.2f}, место {d['priority_rank']}.\n\n**Основание:** {d['evidence']}\n\n"
        f"**Выполнены правила:** {rules}.\n\n**Главный вклад в приоритет:** "
        + ", ".join(f"{c['label']} (+{c['contribution']:.2f})" for c in components)
        + "."
        + (f"\n\n{d['why']}" if d["why"] else "")
    )
    return Answer(
        "explain",
        markdown,
        citations=[citation(data, gid)],
        actions=[{"type": "focus", "ids": [str(gid)], "label": "Показать узел"}],
        highlight_nodes=[str(gid)],
    )


# Order matters: specific intents first, the bare-gid explanation last.
_INTENTS = (_top, _collectors, _path, _sources, _destinations, _cluster, _explain)


def answer_offline(data: RunData, question: str) -> Answer:
    text = question.lower().strip()
    ids, ambiguous, missing = resolve_mentions(data, re.findall(r"\d{6,19}", text))
    warnings = [f"не найден узел по фрагменту «{m}»" for m in missing]
    if ambiguous:
        answer = Answer(
            "ambiguous",
            "Фрагмент идентификатора подходит нескольким узлам — уточните, какой имеется в виду.",
            candidates=ambiguous,
        )
    else:
        q = Question(text, ids)
        answer = next((a for a in (intent(data, q) for intent in _INTENTS) if a is not None), None) or Answer(
            "help",
            "Не понял вопрос. Примеры запросов — ниже; идентификатор можно указать целиком или уникальным "
            "фрагментом от 6 цифр.",
        )
    answer.warnings = warnings + answer.warnings
    answer.suggestions = suggestions(data)
    return answer

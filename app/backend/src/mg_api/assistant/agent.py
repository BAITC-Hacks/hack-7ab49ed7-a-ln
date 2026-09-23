import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from moneygraph.texts import ROLE_RU

from ..analytics import graphops
from ..analytics.store import RunData
from ..analytics.views import node_detail
from ..schemas import Role
from .answers import Answer, citation, suggestions
from .llm import LLMClient

SYSTEM_PROMPT = """Ты — ассистент AML-аналитика банка. Данные — обезличенный граф внутрибанковских переводов:
узлы — клиенты (gid, 18 цифр), рёбра — переводы плательщик → получатель. Исходные «seed»-клиенты известны
правоохранителям; граф собран от них по исходящим переводам на несколько колен. Каждому узлу движок уже присвоил
роль (coordinator, consolidator, distributor, transit, terminal, peripheral) по явным правилам, приоритет проверки
и числовое обоснование.

Отвечай по-русски, кратко и по существу, опираясь только на данные из инструментов. Каждое утверждение об узле
подкрепляй числами и указывай gid полностью. Выводы формулируй как гипотезы для проверки («признаки
консолидации»), никогда не утверждай виновность. Достижимость по графу не доказывает движение одних и тех же
денег — если это важно для ответа, скажи об этом. Если данных недостаточно, так и скажи и предложи, что запросить."""

TOOLS = [
    {
        "name": "search_nodes",
        "description": "Найти узлы по фрагменту gid (≥ 3 цифр). До 10 узлов с ролью и приоритетом.",
        "input_schema": {"type": "object", "properties": {"fragment": {"type": "string"}}, "required": ["fragment"]},
    },
    {
        "name": "get_node",
        "description": "Сведения об узле: роль, обоснование, метрики, выполненные правила, вклад в "
        "приоритет, главные контрагенты.",
        "input_schema": {"type": "object", "properties": {"gid": {"type": "string"}}, "required": ["gid"]},
    },
    {
        "name": "trace",
        "description": "Узлы выше (up — откуда могли прийти деньги) или ниже (down — куда могли уйти) "
        "по потоку, до max_hops переходов.",
        "input_schema": {
            "type": "object",
            "properties": {
                "gid": {"type": "string"},
                "direction": {"type": "string", "enum": ["up", "down"]},
                "max_hops": {"type": "integer", "minimum": 1, "maximum": 6},
            },
            "required": ["gid", "direction"],
        },
    },
    {
        "name": "shortest_path",
        "description": "Кратчайший путь между двумя узлами (по направлению переводов, иначе без него).",
        "input_schema": {
            "type": "object",
            "properties": {"source": {"type": "string"}, "target": {"type": "string"}},
            "required": ["source", "target"],
        },
    },
    {
        "name": "common_collectors",
        "description": "Общие получатели ниже по потоку (≤ 4 переходов) для нескольких узлов.",
        "input_schema": {
            "type": "object",
            "properties": {"gids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20}},
            "required": ["gids"],
        },
    },
    {
        "name": "top_nodes",
        "description": "Топ узлов по приоритету, опционально с фильтром по роли.",
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "enum": list(ROLE_RU)},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
    },
    {
        "name": "cluster_info",
        "description": "Кластер по номеру: размер, seed, оборот, гипотеза.",
        "input_schema": {
            "type": "object",
            "properties": {"cluster_id": {"type": "integer"}},
            "required": ["cluster_id"],
        },
    },
]
_MAX_TOOL_RESULT_CHARS = 60_000


class ToolInputError(Exception):
    pass


GidText = Annotated[str, StringConstraints(pattern=r"^\d{3,19}$")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchInput(_Input):
    fragment: GidText


class NodeInput(_Input):
    gid: GidText


class TraceInput(_Input):
    gid: GidText
    direction: Literal["up", "down"]
    max_hops: int = Field(4, ge=1, le=6)


class PathInput(_Input):
    source: GidText
    target: GidText


class CollectorsInput(_Input):
    gids: list[GidText] = Field(min_length=1, max_length=20)


class TopInput(_Input):
    role: Role | None = None
    limit: int = Field(10, ge=1, le=50)


class ClusterInput(_Input):
    cluster_id: int = Field(ge=0)


class _Trail:
    def __init__(self):
        self.nodes: set[int] = set()
        self.edges: list[list[str]] = []


def _gid(data: RunData, text: str) -> int:
    if int(text) in data.G:
        return int(text)
    hits = graphops.resolve(data, text, min_len=3)
    if len(hits) != 1:
        raise ToolInputError(f"узел «{text}» не найден или неоднозначен")
    return hits[0]


def _brief(data: RunData, gid: int) -> dict:
    row = data.nodes.loc[gid]
    return {
        "gid": str(gid),
        "role": row.role,
        "priority": round(float(row.priority_score), 3),
        "is_seed": bool(row.is_seed),
    }


_NODE_FIELDS = (
    "id",
    "role",
    "role_score",
    "priority_score",
    "priority_rank",
    "is_seed",
    "depth",
    "evidence",
    "flags",
    "in_kzt",
    "out_kzt",
    "in_deg",
    "out_deg",
    "rules",
    "why",
)


def _get_node(data: RunData, args: NodeInput, trail: _Trail) -> dict:
    gid = _gid(data, args.gid)
    trail.nodes.add(gid)
    d = node_detail(data, gid)
    top_in = sorted(data.G.pred[gid].items(), key=lambda kv: -kv[1]["sum_kzt"])[:5]
    top_out = sorted(data.G.succ[gid].items(), key=lambda kv: -kv[1]["sum_kzt"])[:5]
    return {k: d[k] for k in _NODE_FIELDS} | {
        "metrics": {m["key"]: m["value"] for m in d["metrics"]},
        "priority_components": {c["key"]: c["contribution"] for c in d["priority_components"]},
        "top_payers": [{"gid": str(o), "sum_kzt": e["sum_kzt"]} for o, e in top_in],
        "top_recipients": [{"gid": str(o), "sum_kzt": e["sum_kzt"]} for o, e in top_out],
    }


def _trace(data: RunData, args: TraceInput, trail: _Trail) -> dict:
    sub = graphops.trace(data, _gid(data, args.gid), args.direction, args.max_hops, 300)
    ids = [int(n["id"]) for n in sub["nodes"]]
    trail.nodes.update(ids)
    trail.edges += [[e["source"], e["target"]] for e in sub["edges"]]
    return {
        "total_nodes": sub["total_nodes"],
        "seeds": [str(i) for i in ids if bool(data.nodes.is_seed.at[i])][:30],
        "top_by_priority": [_brief(data, i) for i in graphops.by_priority(data, ids)[:25]],
    }


def _shortest_path(data: RunData, args: PathInput, trail: _Trail) -> dict:
    result = graphops.shortest_path(data, _gid(data, args.source), _gid(data, args.target))
    trail.nodes.update(int(n) for n in result["nodes"])
    trail.edges += [[e["source"], e["target"]] for e in result["edges"]]
    return result


def _common_collectors(data: RunData, args: CollectorsInput, trail: _Trail) -> dict:
    found = graphops.collectors(data, [_gid(data, g) for g in args.gids])
    trail.nodes.update(c.gid for c in found[:10])
    return {"collectors": [_brief(data, c.gid) | {"coverage": c.coverage} for c in found[:15]]}


def _top_nodes(data: RunData, args: TopInput, trail: _Trail) -> dict:
    df = data.nodes if args.role is None else data.nodes[data.nodes.role == args.role]
    rows = df.sort_values(["priority_score", "gid"], ascending=[False, True]).head(args.limit)
    trail.nodes.update(rows.index)
    return {"nodes": [_brief(data, g) | {"evidence": r.evidence} for g, r in rows.iterrows()]}


def _search_nodes(data: RunData, args: SearchInput, trail: _Trail) -> dict:
    hits = graphops.resolve(data, args.fragment, min_len=3)
    trail.nodes.update(hits)
    return {"nodes": [_brief(data, g) for g in hits]}


def _cluster_info(data: RunData, args: ClusterInput, trail: _Trail) -> dict:
    cluster = next((c for c in data.clusters if c["cluster_id"] == args.cluster_id), None)
    if cluster is None:
        raise ToolInputError("кластер не найден")
    return cluster


_HANDLERS = {
    "search_nodes": (SearchInput, _search_nodes),
    "get_node": (NodeInput, _get_node),
    "trace": (TraceInput, _trace),
    "shortest_path": (PathInput, _shortest_path),
    "common_collectors": (CollectorsInput, _common_collectors),
    "top_nodes": (TopInput, _top_nodes),
    "cluster_info": (ClusterInput, _cluster_info),
}


def _run_tool(data: RunData, name: str, raw_input, trail: _Trail) -> dict:
    if name not in _HANDLERS:
        raise ToolInputError(f"неизвестный инструмент {name}")
    model, handler = _HANDLERS[name]
    try:
        args = model.model_validate(raw_input)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        raise ToolInputError(f"некорректные параметры: {problems}") from e
    return handler(data, args, trail)


def _tool_result(data: RunData, block, trail: _Trail) -> dict:
    try:
        payload = json.dumps(_run_tool(data, block.name, block.input, trail), ensure_ascii=False, default=str)
    except ToolInputError as e:
        return {"type": "tool_result", "tool_use_id": block.id, "content": f"Ошибка: {e}", "is_error": True}
    return {"type": "tool_result", "tool_use_id": block.id, "content": payload[:_MAX_TOOL_RESULT_CHARS]}


def answer_with_llm(data: RunData, question: str, llm: LLMClient, max_steps: int) -> Answer:
    summary = data.meta["summary"]
    context = (
        f"Прогон: {summary['n_nodes']} узлов, {summary['n_edges']} рёбер, период {summary['period'][0]} — "
        f"{summary['period'][1]}. Роли: {json.dumps(summary['roles'], ensure_ascii=False)}."
    )
    messages = [{"role": "user", "content": f"{context}\n\nВопрос аналитика: {question}"}]
    trail, warnings, text = _Trail(), [], ""
    for _ in range(max_steps):
        response = llm.create(system=SYSTEM_PROMPT, tools=TOOLS, messages=messages)
        if response.stop_reason == "refusal":
            warnings.append("Модель отклонила запрос; переформулируйте вопрос или используйте офлайн-режим.")
            break
        text = "\n".join(b.text for b in response.content if b.type == "text").strip() or text
        if response.stop_reason == "max_tokens":
            warnings.append("Ответ обрезан по длине.")
            break
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            continue
        if response.stop_reason != "tool_use":
            break
        messages.append(
            {
                "role": "user",
                "content": [_tool_result(data, b, trail) for b in response.content if b.type == "tool_use"],
            }
        )
    else:
        warnings.append("Достигнут предел шагов агента; ответ может быть неполным.")
    cited = [int(x) for x in dict.fromkeys(re.findall(r"\d{15,19}", text)) if int(x) in data.G]
    nodes = [str(g) for g in dict.fromkeys(cited + sorted(trail.nodes))][:400]
    return Answer(
        "llm",
        text or "Модель не дала ответа.",
        mode_used="llm",
        citations=[citation(data, g) for g in cited[:30]],
        actions=[{"type": "highlight", "ids": nodes, "label": "Узлы из ответа"}] if nodes else [],
        highlight_nodes=nodes,
        highlight_edges=trail.edges[:2000],
        warnings=warnings,
        suggestions=suggestions(data),
    )

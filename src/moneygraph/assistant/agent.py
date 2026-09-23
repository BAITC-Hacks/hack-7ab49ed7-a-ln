"""AI-ассистент аналитика: вопрос на естественном языке → ответ по графу со ссылками на gid.

Цикл tool-calling поверх out/graph.json. Без ключа или при ошибке API — детерминированный режим:
карточки узлов, найденных по gid/окончаниям в вопросе, либо топ-5 по приоритету.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from moneygraph.assistant.llm import LLMProvider, get_provider
from moneygraph.assistant.tools import TOOLS, execute, to_json
from moneygraph.cards import index, load_graph, match_line, node_card, resolve

MAX_ROUNDS = 6
GID_RE = re.compile(r"(?<!\d)\d{18}(?!\d)")

SYSTEM_PROMPT = """Ты — ассистент AML-аналитика банка второго уровня. Перед тобой граф внутрибанковских \
переводов, собранный от 81 seed-клиента (участники незаконного оборота) на 4 колена по исходящим переводам, \
июль 2026, переводы ≥ 5 000 ₸. Каждому узлу уже присвоены роль (coordinator — координатор, consolidator — \
консолидатор, distributor — распределитель, transit — транзит, terminal — конечный получатель, peripheral — \
периферия), уверенность, кластер и приоритет проверки.

Правила:
- Используй ТОЛЬКО данные, полученные через инструменты. Ничего не выдумывай: ни ФИО, ни атрибутов клиентов.
- Каждое утверждение подкрепляй полным 18-значным gid и числами (суммы в ₸, число плательщиков/получателей, \
переводов, доли).
- Формулируй как гипотезы для проверки: «признаки консолидации», «требует проверки», «вероятно». Никогда не \
утверждай виновность.
- Учитывай ограничения данных, когда они важны для вывода: у узлов 4-го колена исходящие не выгружены \
(обрыв обхода); входящие у всех узлов видны лишь частично (только от участников выборки); переводы < 5 000 ₸ \
не попали; только июль и только внутри банка.
- Отвечай кратко и по делу, на русском языке; в конце — 1–3 конкретных шага для аналитика."""


def _extract_gids(text: str, graph: dict) -> list[str]:
    by_id = index(graph)["by_id"]
    seen: list[str] = []
    for g in GID_RE.findall(text or ""):
        if g in by_id and g not in seen:
            seen.append(g)
    return seen


def _context(graph: dict, focus_gid: str | None) -> str:
    meta = graph.get("meta", {})
    counts = ", ".join(f"{k}: {v}" for k, v in (meta.get("role_counts") or {}).items())
    s = (f"\n\nСводка: {meta.get('n_nodes')} узлов, {meta.get('n_edges')} связей, {meta.get('n_tx')} переводов, "
         f"период {meta.get('period')}; роли — {counts}; кластеров {len(graph.get('clusters', []))}.")
    if focus_gid and focus_gid in index(graph)["by_id"]:
        s += f"\nАналитик сейчас смотрит на узел {focus_gid} (если вопрос про «этот узел» — речь о нём)."
    return s


def _short_args(args: dict) -> str:
    s = json.dumps(args, ensure_ascii=False)
    return s if len(s) <= 120 else s[:117] + "…"


def _result_summary(res: dict) -> str:
    if "error" in res:
        return f"ошибка: {res['error']}"
    for k in ("nodes", "neighbors", "paths"):
        if k in res:
            return f"{len(res[k])} из {res.get('total', res.get('n_found', len(res[k])))}"
    if "gid" in res:
        return f"{res['gid']} ({res.get('role_ru', res.get('role'))})"
    return "ok"


def fallback(question: str, focus_gid: str | None, graph: dict, reason: str) -> dict:
    """Ответ без LLM: карточки по gid/окончаниям из вопроса, иначе топ-5 по приоритету."""
    trace = [f"детерминированный режим: {reason}"]
    tokens = re.findall(r"\d{4,}", question or "")
    if focus_gid and not tokens:
        tokens = [focus_gid]
    found: list[str] = []
    ambiguous: list[str] = []
    for tok in tokens:
        hits = resolve(tok, graph)
        trace.append(f"resolve({tok}) → {len(hits)} совп.")
        if len(hits) == 1 or (hits and hits[0] == tok):
            if hits[0] not in found:
                found.append(hits[0])
        elif hits:
            ambiguous.append(f"«{tok}»: {len(hits)} совпадений — уточните, например: "
                             + ", ".join(hits[:3]))
    parts = [f"⚠ LLM недоступен ({reason}). Показываю данные без генерации текста."]
    if found:
        parts += [node_card(g, graph) for g in found[:5]]
    if ambiguous:
        parts += ambiguous
    gids = list(found)
    if not found and not ambiguous:
        top = index(graph)["by_rank"][:5]
        parts.append("\n".join(["Топ-5 узлов по приоритету проверки:", *(match_line(n["id"], graph) for n in top)]))
        gids = [n["id"] for n in top]
    return {"answer": "\n\n".join(parts), "gids": gids, "trace": trace, "mode": "fallback"}


def ask(question: str, focus_gid: str | None = None, out_dir: Path = Path("out"),
        provider: LLMProvider | None = None) -> dict:
    """Вопрос → {"answer", "gids", "trace", "mode"}; никогда не бросает исключений наружу."""
    try:
        graph = load_graph(out_dir)
    except FileNotFoundError:
        return {"answer": "Нет out/graph.json — сначала запустите `uv run moneygraph`.", "gids": [],
                "trace": [], "mode": "error"}
    question = (question or "").strip()
    if not question:
        return {"answer": "Задайте вопрос о сети, например: «кто собирает деньги с этих пятерых?»",
                "gids": [], "trace": [], "mode": "error"}
    if provider is None:
        provider = get_provider()
    if provider is None:
        return fallback(question, focus_gid, graph, "не задан OPENAI_API_KEY")

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT + _context(graph, focus_gid)},
                            {"role": "user", "content": question}]
    trace: list[str] = []
    answer = None
    try:
        for _ in range(MAX_ROUNDS):
            reply = provider.chat(messages, tools=TOOLS)
            if not reply.tool_calls:
                answer = reply.content
                break
            messages.append(reply.as_message())
            for call in reply.tool_calls:
                res = execute(call.name, call.arguments, graph)
                trace.append(f"{call.name}({_short_args(call.arguments)}) → {_result_summary(res)}")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": to_json(res)})
        if answer is None:
            messages.append({"role": "user", "content": "Лимит вызовов инструментов исчерпан. Сформулируй итоговый "
                                                        "ответ по уже полученным данным."})
            answer = provider.chat(messages, tools=None).content
    except Exception as exc:
        fb = fallback(question, focus_gid, graph, f"ошибка API: {type(exc).__name__}: {str(exc)[:200]}")
        fb["trace"] = trace + fb["trace"]
        return fb
    answer = (answer or "").strip() or "Модель не вернула текст ответа."
    model = getattr(provider, "model_if_known", None) or getattr(provider, "model", None)
    return {"answer": answer, "gids": _extract_gids(answer, graph), "trace": trace, "mode": "llm",
            "model": model}

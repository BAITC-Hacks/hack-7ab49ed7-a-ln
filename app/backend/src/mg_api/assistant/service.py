from ..analytics.store import RunData
from ..errors import ServiceUnavailable
from .agent import answer_with_llm
from .answers import Answer
from .llm import LLMClient, LLMUnavailable
from .offline import answer_offline


def answer(data: RunData, question: str, mode: str, llm: LLMClient | None, max_steps: int) -> Answer:
    if mode == "offline" or (mode == "auto" and llm is None):
        return answer_offline(data, question)
    if llm is None:
        raise ServiceUnavailable("LLM-режим выключен на сервере", retryable=False)
    try:
        return answer_with_llm(data, question, llm, max_steps)
    except LLMUnavailable as e:
        if mode == "llm":
            raise ServiceUnavailable(str(e)) from e
        fallback = answer_offline(data, question)
        fallback.warnings.insert(0, f"{e} — ответ получен в офлайн-режиме.")
        return fallback

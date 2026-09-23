"""Провайдеры LLM. Сейчас OpenAI (ключ хакатона); интерфейс минимален, чтобы добавить Claude позже.

Формат истории сообщений — OpenAI chat (system/user/assistant/tool); описания инструментов нейтральные:
{"name", "description", "parameters": JSON Schema}. Провайдер сам переводит их в свой формат.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

REPO_ROOT = Path(__file__).resolve().parents[3]

# порядок предпочтения семейств моделей при автоматическом выборе (если OPENAI_MODEL не задан)
MODEL_FAMILIES = ("gpt-5", "gpt-4.1", "gpt-4o")
SKIP_MARKERS = ("audio", "realtime", "tts", "transcribe", "image", "search", "embedding", "mini-tts",
                "ft:", "codex", "-pro", "deep-research", "moderation")
FALLBACK_MODELS = ("gpt-5-mini", "gpt-5", "gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    raw_arguments: str = ""


@dataclass
class ChatReply:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)

    def as_message(self) -> dict:
        """Ответ модели в формате истории (OpenAI chat)."""
        msg: dict = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [{"id": c.id, "type": "function",
                                  "function": {"name": c.name, "arguments": c.raw_arguments or json.dumps(
                                      c.arguments, ensure_ascii=False)}} for c in self.tool_calls]
        return msg


class LLMProvider(Protocol):
    name: str

    @property
    def model(self) -> str: ...

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatReply: ...


def _load_env() -> None:
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # python-dotenv — зависимость проекта, но не роняем импорт
        return
    load_dotenv(find_dotenv(usecwd=True), override=False)
    load_dotenv(REPO_ROOT / ".env", override=False)


def _version(model_id: str, family: str) -> float:
    m = re.match(re.escape(family) + r"\.(\d+)", model_id)
    base = float(re.sub(r"[^\d.]", "", family.split("-")[1]) or 0)
    return base + (float("0." + m.group(1)) if m else 0.0)


def pick_model(ids: list[str]) -> str | None:
    """Эвристика выбора: семейство по MODEL_FAMILIES, без nano/pro/спец-моделей, новее версия, не mini."""
    best = None
    for mid in ids:
        low = mid.lower()
        if any(s in low for s in SKIP_MARKERS):
            continue
        fam = next((i for i, f in enumerate(MODEL_FAMILIES) if low.startswith(f)), None)
        if fam is None:
            continue
        dated = bool(re.search(r"\d{4}-\d{2}-\d{2}", low))
        key = (fam, "nano" in low, "chat-latest" in low, -_version(low, MODEL_FAMILIES[fam]),
               "mini" in low, dated, len(low))
        if best is None or key < best[0]:
            best = (key, mid)
    return best[1] if best else None


def _is_model_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return "model" in s and any(k in s for k in ("not found", "does not exist", "not exist", "invalid",
                                                  "not supported", "no access", "unknown"))


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, base_url: str | None = None, model: str | None = None,
                 timeout: float = 90.0):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=timeout, max_retries=1)
        self._model = model
        self._candidates: list[str] = []
        self.model_note: str | None = None  # пояснение, как выбрана модель (или почему fallback)
        self._reasoning_ok = True

    @property
    def model_if_known(self) -> str | None:
        return self._model

    @property
    def model(self) -> str:
        if self._model is None:
            self._select_model()
        return self._model

    def _select_model(self) -> None:
        try:
            ids = [m.id for m in self.client.models.list()]
            chosen = pick_model(ids)
            if chosen:
                self._model = chosen
                self.model_note = f"выбрана автоматически из {len(ids)} доступных моделей"
                return
            self.model_note = "среди доступных моделей нет подходящих семейств; пробуем запасной список"
        except Exception as exc:
            self.model_note = f"не удалось получить список моделей ({type(exc).__name__}: {exc}); пробуем запасной список"
        self._candidates = list(FALLBACK_MODELS[1:])
        self._model = FALLBACK_MODELS[0]

    def _supports_reasoning(self) -> bool:
        m = self.model.lower()
        return self._reasoning_ok and (m.startswith("gpt-5") or re.match(r"o\d", m) is not None)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatReply:
        from openai import BadRequestError, NotFoundError, PermissionDeniedError

        while True:
            kwargs: dict = {"model": self.model, "messages": messages}
            if tools:
                kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
            if self._supports_reasoning():
                kwargs["reasoning_effort"] = "low"
            try:
                resp = self.client.chat.completions.create(**kwargs)
                break
            except (BadRequestError, NotFoundError, PermissionDeniedError) as exc:
                if "reasoning" in str(exc).lower() and "reasoning_effort" in kwargs:
                    self._reasoning_ok = False
                    continue
                if _is_model_error(exc) and self._candidates:
                    failed = self._model
                    self._model = self._candidates.pop(0)
                    self.model_note = f"модель {failed} недоступна, переключились на {self._model}"
                    continue
                raise
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            raw = fn.arguments or "{}"
            try:
                args = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                args = {"_invalid_json": raw}
            calls.append(ToolCall(id=tc.id, name=fn.name, arguments=args if isinstance(args, dict) else {},
                                  raw_arguments=raw))
        return ChatReply(content=msg.content, tool_calls=calls)


_PROVIDER: LLMProvider | None = None
_PROVIDER_LOADED = False


def get_provider() -> LLMProvider | None:
    """Провайдер по переменным окружения (.env); None, если ключ не задан."""
    global _PROVIDER, _PROVIDER_LOADED
    if _PROVIDER_LOADED:
        return _PROVIDER
    _load_env()
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        _PROVIDER = OpenAIProvider(api_key=key, base_url=os.getenv("OPENAI_BASE_URL") or None,
                                   model=os.getenv("OPENAI_MODEL") or None)
    _PROVIDER_LOADED = True
    return _PROVIDER


def llm_status() -> dict:
    """Для /api/health: без сетевых запросов."""
    p = get_provider()
    if p is None:
        return {"llm": False, "provider": None, "model": None}
    return {"llm": True, "provider": p.name, "model": getattr(p, "model_if_known", None) or None}

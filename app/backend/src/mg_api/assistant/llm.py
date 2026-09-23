from typing import Any, Protocol

import anthropic


class LLMUnavailable(Exception):
    pass


class LLMClient(Protocol):
    def create(self, *, system: str, tools: list[dict], messages: list[dict]) -> Any: ...


class AnthropicLLM:
    def __init__(self, api_key: str, model: str, timeout_s: float):
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=2)
        self._model = model

    def create(self, *, system: str, tools: list[dict], messages: list[dict]) -> Any:
        try:
            return self._client.beta.messages.create(
                model=self._model,
                max_tokens=16000,
                system=system,
                tools=tools,
                messages=messages,
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as e:
            raise LLMUnavailable("Превышен лимит запросов к модели, попробуйте позже") from e
        except anthropic.APIStatusError as e:
            raise LLMUnavailable(f"Модель недоступна (HTTP {e.status_code})") from e
        except anthropic.APIConnectionError as e:
            raise LLMUnavailable("Нет соединения с API модели") from e

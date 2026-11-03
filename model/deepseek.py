"""大模型客户端。

通过 OpenAI 兼容接口调用 DeepSeek，统一处理超时、重试和必填配置校验。
密钥与模型名来自环境变量，不写进代码。
"""
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)


class LLMConfigError(RuntimeError):
    """Raised when required LLM configuration is missing."""


class LLMRequestError(RuntimeError):
    """Raised when an LLM request fails after retries."""


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model_name: str
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    temperature: float | None
    max_tokens: int | None


def _get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise LLMConfigError(f"Missing required environment variable: {name}")
    return value


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise LLMConfigError(f"{name} must be an integer, got: {raw}") from exc


def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise LLMConfigError(f"{name} must be a number, got: {raw}") from exc


def _get_optional_float_env(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise LLMConfigError(f"{name} must be a number, got: {raw}") from exc


def _get_optional_int_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise LLMConfigError(f"{name} must be an integer, got: {raw}") from exc


def load_llm_config() -> LLMConfig:
    return LLMConfig(
        api_key=_get_required_env("DEEPSEEK_API_KEY"),
        base_url=_get_required_env("BASE_URL"),
        model_name=_get_required_env("MODEL_NAME"),
        timeout_seconds=_get_float_env("LLM_TIMEOUT_SECONDS", 60.0),
        max_retries=max(1, _get_int_env("LLM_MAX_RETRIES", 3)),
        retry_backoff_seconds=_get_float_env("LLM_RETRY_BACKOFF_SECONDS", 1.5),
        temperature=_get_optional_float_env("LLM_TEMPERATURE"),
        max_tokens=_get_optional_int_env("LLM_MAX_TOKENS"),
    )


def get_llm_status() -> dict[str, Any]:
    try:
        config = load_llm_config()
    except Exception as exc:
        return {
            "configured": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "configured": True,
        "base_url": config.base_url,
        "model_name": config.model_name,
        "timeout_seconds": config.timeout_seconds,
        "max_retries": config.max_retries,
        "retry_backoff_seconds": config.retry_backoff_seconds,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }


class My_model_client:
    def __init__(self):
        self.config: LLMConfig | None = None
        self.client: OpenAI | None = None

    def _init_client(self) -> None:
        self.config = load_llm_config()
        self.client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
        )

    def _ensure_client(self) -> tuple[OpenAI, LLMConfig]:
        if self.client is None or self.config is None:
            self._init_client()
        return self.client, self.config

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ):
        client, config = self._ensure_client()
        request: dict[str, Any] = {
            "model": config.model_name,
            "messages": messages,
            "stream": False,
        }

        resolved_temperature = (
            temperature if temperature is not None else config.temperature
        )
        resolved_max_tokens = max_tokens if max_tokens is not None else config.max_tokens
        if resolved_temperature is not None:
            request["temperature"] = resolved_temperature
        if resolved_max_tokens is not None:
            request["max_tokens"] = resolved_max_tokens
        request.update(kwargs)

        last_error: Exception | None = None
        for attempt in range(1, config.max_retries + 1):
            try:
                return client.chat.completions.create(**request)
            except Exception as exc:
                last_error = exc
                if attempt >= config.max_retries:
                    break
                sleep_seconds = config.retry_backoff_seconds * attempt
                logger.warning(
                    "LLM request failed on attempt %s/%s: %s",
                    attempt,
                    config.max_retries,
                    exc,
                )
                time.sleep(sleep_seconds)

        raise LLMRequestError(
            f"LLM request failed after {config.max_retries} attempts: {last_error}"
        ) from last_error

    def ask(self, query: str, system_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ]
        response = self.chat_completion(messages=messages)
        content = response.choices[0].message.content
        if content is None:
            raise LLMRequestError("LLM response content is empty")
        return content


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ds = My_model_client()
    result = ds.ask(query="你是什么模型", system_prompt="你是一个小可爱助手")
    logger.info("LLM response: %s", result)

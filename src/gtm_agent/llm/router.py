"""Provider-agnostic LLM router.

Maps the six pipeline roles to a provider + model with a fallback chain, configured via
the ``llm:`` block of ``tenant.yaml``. Built-in providers: Anthropic, Mistral, Google, and
any OpenAI-compatible endpoint (OpenAI, Ollama, imago.market) via a ``base_url``. A custom
provider registered through the LLMProvider plugin is resolved by name.

Every role shares one resilient call path: primary, then fallback if configured, each
retried once with a hint when the result comes back empty.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..log import get_logger
from .config import LLMConfig, ProviderConfig, RoleConfig

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.language_models.chat_models import BaseChatModel
    from pydantic import BaseModel

logger = get_logger(__name__)


class LLMRole(StrEnum):
    """Pipeline roles that map to a configured provider + model."""

    RESEARCH = "research"
    ANALYST = "analyst"
    SYNTHESIZER = "synthesizer"
    FACT_CHECK = "fact_check"
    QA_REVIEWER = "qa_reviewer"
    POLISH = "polish"


def is_transient_error(exc: BaseException) -> bool:
    """True if the exception chain looks transient and worth failing over for.

    Catches 429 capacity, network timeouts, 5xx, and exhausted upstream retries. Walks
    ``__cause__`` / ``__context__`` because tenacity / langchain wrap the original error.
    """
    import httpx

    try:
        from tenacity import RetryError

        retry_errors: tuple[type[BaseException], ...] = (RetryError,)
    except ImportError:
        retry_errors = ()

    timeout_excs = (
        httpx.ReadTimeout,
        httpx.ConnectTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
        httpx.NetworkError,
        TimeoutError,
    )

    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, httpx.HTTPStatusError):
            code = current.response.status_code
            if code == 429 or 500 <= code < 600:
                return True
        if isinstance(current, timeout_excs):
            return True
        if isinstance(current, retry_errors):
            return True
        # The typed 429/5xx/timeout checks above cover the real cases; keep only
        # high-signal tokens here, unlikely to appear in an unrelated error message
        # (e.g. a validation error echoing text that happens to say "timeout").
        msg = str(current).lower()
        if any(
            s in msg
            for s in (
                "rate limit",
                "rate_limit",
                "too many requests",
                "overloaded_error",
                "service_tier_capacity",
            )
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


class LLMRouter:
    """Builds and caches structured-output LLM clients per role from an LLMConfig."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._cache: dict[tuple[str, str, float, int, int, str, str], BaseChatModel] = {}

    def _role(self, role: LLMRole) -> RoleConfig:
        return getattr(self._config, role.value)

    def get_structured(
        self,
        role: LLMRole,
        schema: type[BaseModel],
        temperature: float = 0.0,
        *,
        fallback: bool = False,
    ) -> object:
        """Return a structured-output runnable bound to ``schema`` for ``role``."""
        rc = self._role(role)
        pc = rc.fallback if fallback else rc.primary
        if pc is None:
            msg = f"no fallback provider configured for role {role.value!r}"
            raise ValueError(msg)
        model = self._build(pc, temperature)
        if pc.provider == "mistral":
            return model.with_structured_output(schema, method="json_schema")
        return model.with_structured_output(schema)

    def chat_model(
        self, role: LLMRole, *, fallback: bool = False, temperature: float = 0.0
    ) -> BaseChatModel:
        """Return the raw chat model for ``role`` (for tool-calling agentic loops).

        Unlike ``call_resilient``, this path has no cross-provider fallback: an agentic
        tool-calling loop relies on the provider's own ``max_retries`` for transient errors.
        """
        rc = self._role(role)
        pc = rc.fallback if fallback else rc.primary
        if pc is None:
            msg = f"no fallback provider configured for role {role.value!r}"
            raise ValueError(msg)
        return self._build(pc, temperature)

    def _build(self, pc: ProviderConfig, temperature: float) -> BaseChatModel:
        key = (
            pc.provider,
            pc.model,
            temperature,
            pc.timeout,
            pc.max_tokens,
            pc.api_key_env,
            pc.base_url_env,
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        model = _build_chat_model(pc, temperature)
        self._cache[key] = model
        return model

    async def call_resilient(
        self,
        role: LLMRole,
        schema: type[BaseModel],
        messages: list[dict[str, str]],
        *,
        nonempty: Callable[[Any], bool],
        retry_hint: str = "",
        temperature: float = 0.0,
        label: str = "?",
    ) -> object | None:
        """Best-effort structured call with the full resilience ladder.

        Tries the primary, then the fallback if configured, each retried once with
        ``retry_hint`` when the result is "empty" (per ``nonempty``). Returns the first
        non-empty result, or ``None`` if every stage came back empty or transiently failed
        (callers treat ``None`` as "skip this node"). Non-transient errors propagate.
        """
        stages = [False, True] if self._role(role).fallback is not None else [False]
        for use_fallback in stages:
            chain = self.get_structured(role, schema, temperature, fallback=use_fallback)
            try:
                result = await chain.ainvoke(messages)  # type: ignore[attr-defined]
                if nonempty(result):
                    return result
                if retry_hint:
                    logger.warning(
                        "llm_empty_retrying", role=role.value, label=label, fallback=use_fallback
                    )
                    hinted = [*messages, {"role": "user", "content": retry_hint}]
                    result = await chain.ainvoke(hinted)  # type: ignore[attr-defined]
                    if nonempty(result):
                        return result
            except Exception as exc:  # noqa: BLE001
                if not is_transient_error(exc):
                    raise
                logger.warning(
                    "llm_stage_transient",
                    role=role.value,
                    label=label,
                    fallback=use_fallback,
                    error=str(exc)[:150],
                )
        return None


def _build_chat_model(pc: ProviderConfig, temperature: float) -> BaseChatModel:
    """Construct a LangChain chat model for one provider config."""
    api_key = os.environ.get(pc.key_env())

    if pc.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(  # type: ignore[call-arg]
            model=pc.model,
            temperature=temperature,
            anthropic_api_key=api_key,
            max_tokens=pc.max_tokens,
            default_request_timeout=pc.timeout,
            max_retries=pc.max_retries,
        )

    if pc.provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=pc.model,
            temperature=temperature,
            api_key=api_key,  # type: ignore[arg-type]
            base_url=os.environ.get(pc.base_url_env) or None,
            timeout=pc.timeout,
            max_retries=pc.max_retries,
        )

    if pc.provider == "mistral":
        try:
            from langchain_mistralai import ChatMistralAI  # type: ignore[import-not-found]
        except ImportError as err:
            msg = "install the 'mistral' extra: pip install 'go-to-market-agent[mistral]'"
            raise ImportError(msg) from err

        return ChatMistralAI(
            model=pc.model,
            temperature=temperature,
            mistral_api_key=api_key,
            timeout=pc.timeout,
            max_retries=pc.max_retries,
        )

    if pc.provider == "google":
        try:
            from langchain_google_genai import (  # type: ignore[import-not-found]
                ChatGoogleGenerativeAI,
                HarmBlockThreshold,
                HarmCategory,
            )
        except ImportError as err:
            msg = "install the 'google' extra: pip install 'go-to-market-agent[google]'"
            raise ImportError(msg) from err

        # Disable the built-in moderation: content safety is the pipeline's own concern,
        # and the built-in filter spuriously blocks benign research text.
        safety = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        return ChatGoogleGenerativeAI(
            model=pc.model,
            temperature=temperature,
            google_api_key=api_key,
            timeout=pc.timeout,
            max_retries=pc.max_retries,
            safety_settings=safety,
        )

    # Custom provider registered via the LLMProvider plugin.
    built = _build_plugin_provider(pc, temperature)
    if built is not None:
        return built

    msg = f"unknown provider: {pc.provider!r}"
    raise ValueError(msg)


def _build_plugin_provider(pc: ProviderConfig, temperature: float) -> BaseChatModel | None:
    """Resolve a provider registered through the LLMProvider plugin, or None."""
    from ..plugins.registry import all_of, load_entrypoint_plugins

    load_entrypoint_plugins()
    obj = all_of("provider").get(pc.provider)
    if obj is None:
        return None
    inst = obj() if isinstance(obj, type) else obj
    try:
        return inst.build(  # type: ignore[no-any-return]
            {
                "model": pc.model,
                "api_key_env": pc.key_env(),
                "base_url_env": pc.base_url_env,
                "temperature": temperature,
                "max_tokens": pc.max_tokens,
                "timeout": pc.timeout,
                "max_retries": pc.max_retries,
            }
        )
    except Exception as exc:
        msg = f"LLMProvider plugin {pc.provider!r} failed to build a chat model: {exc}"
        raise RuntimeError(msg) from exc

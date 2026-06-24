"""LLM router configuration.

Populated from the ``llm:`` block of ``tenant.yaml`` or ``default_llm_config()`` for the
demo/tests. Six roles, each mapping to a primary provider with an optional fallback:

  research      the supervisor/researcher agentic loop
  analyst       the six section analysts (facts-only)
  synthesizer   the three cross-section synthesizers
  fact_check    claim verification + credibility calibration
  qa_reviewer   the pre-publish LLM reviewer (can reject)
  polish        light narrative cleanup

`provider` is a string so a custom provider registered via the LLMProvider plugin can be
named here; the four built-ins are anthropic, openai (OpenAI-compatible), mistral, google.
"""

from __future__ import annotations

import os

from pydantic import BaseModel

ROLES = ("research", "analyst", "synthesizer", "fact_check", "qa_reviewer", "polish")

# Default env var holding each built-in provider's API key.
_DEFAULT_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "google": "GOOGLE_API_KEY",
}


class ProviderConfig(BaseModel):
    """One provider+model endpoint for a pipeline role."""

    provider: str  # anthropic | openai | mistral | google | <plugin name>
    model: str
    api_key_env: str = ""  # defaults to the provider's standard env var (built-ins only)
    base_url_env: str = "OPENAI_BASE_URL"  # only used by the openai-compatible provider
    max_tokens: int = 8192
    timeout: int = 120
    max_retries: int = 3

    def key_env(self) -> str:
        return self.api_key_env or _DEFAULT_KEY_ENV.get(self.provider, "")


class RoleConfig(BaseModel):
    """Primary + optional fallback provider for a single role."""

    primary: ProviderConfig
    fallback: ProviderConfig | None = None


class LLMConfig(BaseModel):
    """Role to provider mapping for the six pipeline roles."""

    research: RoleConfig
    analyst: RoleConfig
    synthesizer: RoleConfig
    fact_check: RoleConfig
    qa_reviewer: RoleConfig
    polish: RoleConfig


def default_llm_config() -> LLMConfig:
    """A runnable default (Anthropic-only) so the engine works with one ANTHROPIC_API_KEY.

    The example tenant's ``llm:`` block shows how to mix providers and add fallbacks. An
    OpenAI-compatible fallback (OpenAI / Ollama / imago.market) is wired automatically for
    the analyst and synthesizer roles when ``OPENAI_API_KEY`` is present.
    """
    sonnet = ProviderConfig(provider="anthropic", model="claude-sonnet-4-6")
    haiku = ProviderConfig(provider="anthropic", model="claude-haiku-4-5-20251001")
    openai_fallback = (
        ProviderConfig(provider="openai", model="gpt-4o-mini")
        if os.environ.get("OPENAI_API_KEY")
        else None
    )
    return LLMConfig(
        research=RoleConfig(primary=sonnet),
        analyst=RoleConfig(primary=sonnet, fallback=openai_fallback),
        synthesizer=RoleConfig(primary=sonnet, fallback=openai_fallback),
        fact_check=RoleConfig(primary=sonnet),
        qa_reviewer=RoleConfig(primary=sonnet),
        polish=RoleConfig(primary=haiku),
    )

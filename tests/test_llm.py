"""LLM router tests: config defaults, transient-error detection, plugin provider hook."""

from __future__ import annotations

import httpx

from gtm_agent.llm.config import ProviderConfig, default_llm_config
from gtm_agent.llm.router import LLMRole, _build_chat_model, is_transient_error
from gtm_agent.plugins import provider as provider_plugin


def test_default_config_has_six_roles() -> None:
    cfg = default_llm_config()
    for role in ("research", "analyst", "synthesizer", "fact_check", "qa_reviewer", "polish"):
        assert getattr(cfg, role).primary.provider == "anthropic"
    assert {r.value for r in LLMRole} == {
        "research",
        "analyst",
        "synthesizer",
        "fact_check",
        "qa_reviewer",
        "polish",
    }


def test_provider_key_env_default() -> None:
    assert ProviderConfig(provider="anthropic", model="m").key_env() == "ANTHROPIC_API_KEY"
    assert ProviderConfig(provider="mistral", model="m").key_env() == "MISTRAL_API_KEY"
    assert ProviderConfig(provider="custom", model="m", api_key_env="X_KEY").key_env() == "X_KEY"


def test_is_transient_error() -> None:
    resp = httpx.Response(429, request=httpx.Request("GET", "https://x.test"))
    assert is_transient_error(httpx.HTTPStatusError("rate", request=resp.request, response=resp))
    assert is_transient_error(TimeoutError("slow"))
    assert is_transient_error(ValueError("overloaded_error from upstream"))
    assert not is_transient_error(ValueError("a normal validation failure"))


def test_plugin_provider_hook_is_resolved() -> None:
    @provider_plugin("faux")
    class FauxProvider:
        name = "faux"

        def build(self, config: dict) -> object:
            return ("built", config["model"])

    built = _build_chat_model(ProviderConfig(provider="faux", model="m1"), 0.0)
    assert built == ("built", "m1")

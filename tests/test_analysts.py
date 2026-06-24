"""Analyst node tests: note filtering, competitor injection, fail-soft, output slot."""

from __future__ import annotations

from typing import Any

from gtm_agent.engine.nodes.analysts import (
    ANALYSTS,
    analyze_consumer,
    format_competitor_raw_block,
)
from gtm_agent.models import ConsumerSignals


class _FakeRouter:
    def __init__(self, result: Any = None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc

    async def call_resilient(self, role: Any, schema: Any, messages: Any, **kw: Any) -> Any:
        if self._exc is not None:
            raise self._exc
        return self._result


def _consumer() -> ConsumerSignals:
    return ConsumerSignals(
        conclusion="Demand is steady across the core audience.",
        audience_adoption="Adoption is rising.",
        seasonal_context="Q2 seasonality applies.",
    )


def test_registry_has_six_analysts() -> None:
    assert len(ANALYSTS) == 6
    assert "analyze_competitive" in ANALYSTS


async def test_analyst_returns_section_slot() -> None:
    state = {"notes": ["[consumer] demand looks healthy"], "period": "2026-04"}
    out = await analyze_consumer(state, None, router=_FakeRouter(result=_consumer()))
    assert isinstance(out["section_consumer"], ConsumerSignals)
    assert "notes_fallback_sections" not in out  # the note was tagged for this section


async def test_analyst_flags_corpus_fallback() -> None:
    state = {"notes": ["[other] unrelated note"], "period": "2026-04"}
    out = await analyze_consumer(state, None, router=_FakeRouter(result=_consumer()))
    assert out["notes_fallback_sections"] == ["section_consumer"]


async def test_analyst_no_notes_returns_empty() -> None:
    out = await analyze_consumer({"notes": [], "period": "2026-04"}, None, router=_FakeRouter())
    assert out == {}


async def test_analyst_is_failsoft_on_error() -> None:
    state = {"notes": ["[consumer] note"], "period": "2026-04"}
    out = await analyze_consumer(state, None, router=_FakeRouter(exc=ValueError("bad output")))
    assert out["error"] == ["analyst_section_consumer_failed"]


def test_competitor_raw_block_formats_metrics() -> None:
    block = format_competitor_raw_block(
        {"competitor_raw": {"acme": {"ig_followers_count": 1000, "active_ads_count": 5}}}
    )
    assert "acme" in block
    assert "followers=1000" in block
    assert format_competitor_raw_block({"competitor_raw": {}}) == ""

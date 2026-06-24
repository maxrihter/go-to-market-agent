"""Synthesizer tests: output slots, no-op on empty, stub + rescue fallbacks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from gtm_agent.engine.nodes.synthesizers import (
    synthesize_exec_summary,
    synthesize_scoreboard,
    synthesize_strategic_recommendations,
)
from gtm_agent.models import (
    CompetitiveLandscape,
    CompetitorProfile,
    ExecutiveSummary,
    MarketReport,
    Scoreboard,
    StrategicMove,
)


class _FakeRouter:
    def __init__(self, result: Any = None) -> None:
        self._result = result

    async def call_resilient(self, role: Any, schema: Any, messages: Any, **kw: Any) -> Any:
        return self._result


async def test_scoreboard_returns_slot(make_report: Callable[[str], MarketReport]) -> None:
    rep = make_report("2026-04")
    state = {"period": "2026-04", "section_consumer": rep.consumer_signals}
    out = await synthesize_scoreboard(state, None, router=_FakeRouter(result=rep.scoreboard))
    assert isinstance(out["section_scoreboard"], Scoreboard)


async def test_synth_noop_without_analyst_output() -> None:
    out = await synthesize_scoreboard({"period": "2026-04"}, None, router=_FakeRouter())
    assert out == {}


async def test_exec_summary_falls_back_to_stub(make_report: Callable[[str], MarketReport]) -> None:
    rep = make_report("2026-04")
    state = {"period": "2026-04", "section_consumer": rep.consumer_signals}
    out = await synthesize_exec_summary(state, None, router=_FakeRouter(result=None))
    assert isinstance(out["section_exec_summary"], ExecutiveSummary)
    assert out["section_exec_summary"].key_findings  # stub carries findings


async def test_strategic_rescue_from_competitive() -> None:
    move = StrategicMove(
        move_date=date(2026, 1, 1),
        move_type="launch",
        headline="Rival launched a competing product",
        source_url="https://news.realsite.io/a",
        source_name="News",
        so_what="It pressures our core segment",
        threat_level="p0",
    )
    prof = CompetitorProfile(name="Rival", country_hq="US", strategic_moves_recent=[move])
    state = {
        "period": "2026-04",
        "section_competitive": CompetitiveLandscape(global_players=[prof]),
    }
    out = await synthesize_strategic_recommendations(state, None, router=_FakeRouter(result=None))
    recs = out["section_strategic"].monthly_tactical
    assert recs and recs[0].evidence_section_refs  # rescue produced a sourced rec

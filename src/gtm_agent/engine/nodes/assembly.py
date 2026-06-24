"""Final assembly: build the MarketReport from the section state slots.

Collects sources for the appendix, fills any missing section with a minimal valid stub so a
single failed analyst cannot block the whole report, attaches the month-over-month diff,
and constructs the root MarketReport. Fail-soft: returns an ``error`` delta only if even the
stubbed report cannot be built.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ...log import get_logger
from ...models import (
    AppendixSection,
    BrandPositioning,
    CompetitiveLandscape,
    ConsumerSignals,
    ExecutiveSummary,
    GlobalMarketLandscape,
    MarketReport,
    MarketSizingPoint,
    RegionalMarketPulse,
    Scoreboard,
    SourceRef,
    StrategicRecommendations,
    TechnologyTrends,
)
from ...urls import is_fake_source_url

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

logger = get_logger(__name__)

_SECTION_SLOTS = (
    "section_global_market",
    "section_regional_pulse",
    "section_competitive",
    "section_brand_positioning",
    "section_consumer",
    "section_tech",
)


def _aggregate_sources(state: Any) -> list[SourceRef]:
    """Walk every section's sources, dedupe by URL, drop fakes, enrich from the curator."""
    curated = {
        str(s.url): s for s in (state.get("curated_sources") or []) if getattr(s, "url", None)
    }
    seen: set[str] = set()
    out: list[SourceRef] = []

    def _walk(obj: Any) -> None:
        if obj is None:
            return
        if isinstance(obj, SourceRef):
            url = str(obj.url) if obj.url else ""
            if not url or is_fake_source_url(url) or url in seen:
                return
            seen.add(url)
            enriched = obj
            if obj.credibility_tier == "unknown" and url in curated:
                c = curated[url]
                enriched = obj.model_copy(
                    update={
                        "credibility_score": c.credibility_score,
                        "credibility_tier": c.credibility_tier,
                        "publisher": obj.publisher or c.publisher,
                    }
                )
            out.append(enriched)
            return
        if isinstance(obj, list):
            for item in obj:
                _walk(item)
        elif isinstance(obj, BaseModel):
            for fname in type(obj).model_fields:
                _walk(getattr(obj, fname, None))

    for slot in _SECTION_SLOTS:
        _walk(state.get(slot))
    return out


# ---------------------------------------------------------------------------
# Minimal stubs for missing required sections
# ---------------------------------------------------------------------------


def _stub_sizing() -> MarketSizingPoint:
    return MarketSizingPoint(
        segment="data unavailable", size_value=0, year=datetime.now(tz=UTC).year, sources=[]
    )


def _stub_scoreboard(period: str) -> Scoreboard:
    return Scoreboard(
        period=period,
        bluf_bullets=["Scoreboard unavailable.", "See the sections.", "Data pending."],
        hero_kpis=[],
    )


def _stub_exec_summary() -> ExecutiveSummary:
    return ExecutiveSummary(
        situation="The executive summary was not generated; see the sections.",
        complication="See the competitive section for the period's dynamics.",
        resolution="See the recommendations section for direction.",
        key_findings=["[L] Summary unavailable; underlying analysis is in the sections."],
    )


_STUB_TEXT = "Data unavailable for this section this period."


def _stub_section(slot: str) -> Any:
    if slot == "section_global_market":
        return GlobalMarketLandscape(global_market_sizing=_stub_sizing(), primary_segment_sizing=[])
    if slot == "section_regional_pulse":
        return RegionalMarketPulse(conclusion=_STUB_TEXT)
    if slot == "section_competitive":
        return CompetitiveLandscape()
    if slot == "section_brand_positioning":
        return BrandPositioning(
            conclusion=_STUB_TEXT,
            quadrant_position="Position unavailable.",
            strengths=[],
            weaknesses=[],
            implications=[],
        )
    if slot == "section_consumer":
        return ConsumerSignals(
            conclusion=_STUB_TEXT, audience_adoption=_STUB_TEXT, seasonal_context=_STUB_TEXT
        )
    if slot == "section_tech":
        return TechnologyTrends(conclusion=_STUB_TEXT, trends=[])
    raise ValueError(slot)


async def assemble_final_report(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """Assemble the MarketReport from the section slots, stubbing any that are missing."""
    period = state.get("period", datetime.now(tz=UTC).strftime("%Y-%m"))
    sources = _aggregate_sources(state)
    appendix = AppendixSection(
        methodology="Agentic web research, multi-source enrichment, and LLM synthesis.",
        confidence_legend="[H] high, [M] medium, [L] low confidence.",
        all_sources_referenced=sources,
        what_changed_since_last_period=state.get("mom_narrative"),
        mom_diff_structured=state.get("mom_diff"),
    )
    try:
        report = MarketReport(
            report_id=f"report-{period}",
            period=period,
            period_type=state.get("period_type", "month"),
            language="en",
            scoreboard=state.get("section_scoreboard") or _stub_scoreboard(period),
            executive_summary=state.get("section_exec_summary") or _stub_exec_summary(),
            global_market=state.get("section_global_market")
            or _stub_section("section_global_market"),
            regional_pulse=state.get("section_regional_pulse")
            or _stub_section("section_regional_pulse"),
            competitive_landscape=state.get("section_competitive")
            or _stub_section("section_competitive"),
            brand_positioning=state.get("section_brand_positioning")
            or _stub_section("section_brand_positioning"),
            consumer_signals=state.get("section_consumer") or _stub_section("section_consumer"),
            technology_trends=state.get("section_tech") or _stub_section("section_tech"),
            strategic_recommendations=state.get("section_strategic") or StrategicRecommendations(),
            appendix=appendix,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("assembly_failed", error=str(exc)[:300])
        return {"error": [f"assembly_failed: {str(exc)[:150]}"]}

    logger.info("assembly_complete", report_id=report.report_id, sources=len(sources))
    return {"report": report}

"""LangGraph state for the report pipeline plus the research subgraph states.

Uses the override-reducer pattern (from open_deep_research): a state field accumulated
by parallel nodes uses `operator.add`, and a field that should be replaceable wholesale
accepts `{"type": "override", "value": X}`.
"""

from __future__ import annotations

import operator
from datetime import date
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langchain_core.messages import MessageLikeRepresentation  # noqa: TCH002 (runtime needed)
from pydantic import BaseModel, Field

from .report import (
    AppendixSection,
    BrandPositioning,
    CompetitiveLandscape,
    ConsumerSignals,
    ExecutiveSummary,
    GlobalMarketLandscape,
    MarketReport,
    MoMDiffStructured,
    QAVerdict,
    RegionalMarketPulse,
    Scoreboard,
    StrategicRecommendations,
    TechnologyTrends,
)
from .sections import ReportRef, SourceRef

# MessageLikeRepresentation must be a runtime import: LangGraph calls get_type_hints on
# the state class to bind reducers, which fails on TYPE_CHECKING-only imports.


def override_reducer(current: Any, new: Any) -> Any:
    """Accumulate by default; replace wholesale on `{"type": "override", "value": X}`."""
    if isinstance(new, dict) and new.get("type") == "override":
        return new.get("value", new)
    return operator.add(current, new)


# ---------------------------------------------------------------------------
# Research-delegation tool schemas
# ---------------------------------------------------------------------------


class ConductResearch(BaseModel):
    """A supervisor tool call delegating one bounded research task to a worker."""

    research_topic: str = Field(
        description=(
            "A single focused research topic, described in detail (at least a paragraph "
            "of context) so the researcher can operate without supervisor state."
        )
    )
    depth: Literal["quick", "standard", "deep"] = "standard"
    preferred_sources: list[str] = Field(default_factory=list)
    section_target: str = Field(
        description="Which report section the findings feed, e.g. 'Section 2 Global Market'."
    )


class ResearchComplete(BaseModel):
    """A researcher tool call signaling the task is done and findings are compressed."""


class FactCheck(BaseModel):
    """A tool call to cross-verify a claim against the source corpus."""

    claim: str = Field(description="A single factual claim to verify")
    required_min_sources: int = Field(default=2, ge=1, le=5)


# ---------------------------------------------------------------------------
# Top-level pipeline state
# ---------------------------------------------------------------------------


class MarketReportState(TypedDict):
    """Top-level LangGraph state for the report pipeline."""

    period: str  # "2026-04"
    quarter: str | None
    research_brief: NotRequired[str]
    section_briefs: NotRequired[dict[str, str]]
    supervisor_messages: Annotated[list[MessageLikeRepresentation], override_reducer]
    raw_notes: Annotated[list[str], override_reducer]
    notes: Annotated[list[str], override_reducer]

    curated_sources: NotRequired[list[SourceRef]]

    # Source enrichment output, keyed by competitor slug. A loose, source-shaped dict
    # (e.g. ig_followers_count, web_analytics, meta_ads, search_interest_*, app_store);
    # analysts map it selectively onto CompetitorProfile, never CompetitorProfile(**raw).
    competitor_raw: NotRequired[dict[str, dict[str, Any]]]

    # Dataclass results carried as `object` to avoid cross-imports.
    fact_check_report: NotRequired[object]
    validation_report: NotRequired[object]

    # Section outputs, populated by analysts + synthesizers.
    section_global_market: NotRequired[GlobalMarketLandscape]
    section_regional_pulse: NotRequired[RegionalMarketPulse]
    section_competitive: NotRequired[CompetitiveLandscape]
    section_brand_positioning: NotRequired[BrandPositioning]
    section_consumer: NotRequired[ConsumerSignals]
    section_tech: NotRequired[TechnologyTrends]
    section_scoreboard: NotRequired[Scoreboard]
    section_exec_summary: NotRequired[ExecutiveSummary]
    section_strategic: NotRequired[StrategicRecommendations]
    section_appendix: NotRequired[AppendixSection]

    report: NotRequired[MarketReport]

    # Publishing state.
    output_paths: NotRequired[dict[str, str]]
    qa_status: NotRequired[Literal["pending", "pass", "fail"]]

    prior_reports: NotRequired[list[ReportRef]]
    qa_verdict: NotRequired[QAVerdict]

    # Accumulating audit trails (parallel nodes append).
    qa_issues: Annotated[list[str], operator.add]
    error: Annotated[list[str], operator.add]
    notes_fallback_sections: Annotated[list[str], operator.add]

    mom_narrative: NotRequired[str]
    mom_diff: NotRequired[MoMDiffStructured]
    fake_source_urls: NotRequired[list[str]]
    prev_feedback_digest: NotRequired[str]
    polish_status: NotRequired[dict[str, str]]

    # Period metadata: nodes dispatch monthly vs annual paths off these.
    period_type: NotRequired[str]  # "month" / "quarter" / "annual"
    period_start: NotRequired[date]
    period_end: NotRequired[date]


# ---------------------------------------------------------------------------
# Research subgraph states
# ---------------------------------------------------------------------------


class ResearchSupervisorState(TypedDict):
    """State for the research supervisor subgraph."""

    research_brief: str
    section_briefs: dict[str, str]
    supervisor_messages: Annotated[list[MessageLikeRepresentation], override_reducer]
    notes: Annotated[list[str], override_reducer]
    research_iterations: NotRequired[int]
    section_coverage: NotRequired[dict[str, bool]]
    period_type: NotRequired[str]


class ResearcherState(TypedDict):
    """State for a single researcher subgraph (one per ConductResearch call)."""

    research_topic: str
    section_target: str
    depth: Literal["quick", "standard", "deep"]
    preferred_sources: list[str]
    researcher_messages: Annotated[list[MessageLikeRepresentation], override_reducer]
    tool_call_iterations: NotRequired[int]
    raw_findings: Annotated[list[str], override_reducer]
    compressed_findings: NotRequired[str]
    sources_collected: Annotated[list[SourceRef], override_reducer]

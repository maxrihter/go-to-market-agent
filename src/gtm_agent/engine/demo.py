"""Hermetic, no-keys demo runner: the showcase + the engine's end-to-end integration test.

Runs the FULL report graph with no API keys and no network. A DemoRouter returns canned,
mutually-consistent outputs (it never builds a provider client): its fake chat model drives
the research subgraph to completion, and its `call_resilient` returns canned section models.
A prior-month report is seeded into an in-memory store so the month-over-month sections show
real deltas. Output goes to output/<report_id>.md + .json.

The canned dataset is a fictional US fresh dog-food brand (Barkwell) and references real
public competitor names as illustrative examples only.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from langchain_core.messages import AIMessage

from ..config import BrandConfig, Settings
from ..llm.config import default_llm_config
from ..llm.router import LLMRouter
from ..log import get_logger
from ..models import (
    AppendixSection,
    BrandPositioning,
    CompetitiveLandscape,
    CompetitorProfile,
    ConsumerSignals,
    ExecutiveSummary,
    GlobalMarketLandscape,
    KPITile,
    MarketReport,
    MarketSizingPoint,
    QAVerdict,
    RegionalMarketPulse,
    Scoreboard,
    SourceRef,
    StrategicMove,
    StrategicRecommendation,
    StrategicRecommendations,
    TechnologyTrends,
    TechTrendItem,
    TectonicShift,
    TrendMaturity,
)
from .pipeline import run_pipeline

logger = get_logger(__name__)

_SECTION_TOKENS = (
    "global market",
    "regional",
    "competitive",
    "brand positioning",
    "consumer",
    "technology",
)
_SRC = SourceRef(
    title="Demo market study 2026",
    url="https://research.demo-source.io/dog-nutrition-2026",
    credibility_tier="tier_1",
    credibility_score=0.9,
)


# ---------------------------------------------------------------------------
# Canned section builders (the demo dataset)
# ---------------------------------------------------------------------------


def _scoreboard(period: str, market_value: str = "$2.4B") -> Scoreboard:
    return Scoreboard(
        period=period,
        bluf_bullets=[
            f"US fresh dog-food market hit {market_value}, up double digits YoY.",
            "The Farmer's Dog widened its lead on Instagram engagement.",
            "Subscription fatigue is emerging as a retention risk across the category.",
        ],
        hero_kpis=[
            KPITile(
                label="US fresh dog-food market",
                value=market_value,
                delta="+18%",
                delta_direction="up",
            ),
            KPITile(
                label="Top competitor followers", value="1.2M", delta="+6%", delta_direction="up"
            ),
            KPITile(
                label="Category ad intensity", value="High", delta="flat", delta_direction="flat"
            ),
        ],
    )


def _exec_summary() -> ExecutiveSummary:
    return ExecutiveSummary(
        situation="The US fresh, human-grade dog-food category keeps growing on DTC subscriptions.",
        complication="Incumbents push into vet-adjacent positioning, squeezing mid-market brands.",
        resolution="Lean into transparent sourcing and a vet-credibility wedge before incumbents.",
        key_findings=[
            "Fresh-food penetration is still under 5% of US dog owners. [Section 2, H]",
            "The Farmer's Dog leads engagement; Ollie is closing the gap. [Section 4, M]",
            "Regulatory scrutiny of pet-food health claims is rising. [Section 3, M]",
        ],
        tectonic_shifts=[
            TectonicShift(
                name="Vet-credibility land grab",
                narrative="Leaders are buying veterinary endorsements to justify premium pricing.",
                severity="high",
            )
        ],
        watch_list=[
            "Watch for an Ollie funding round; trigger: a press mention of a Series raise.",
            "Watch private-label fresh entering grocery; trigger: a major retailer SKU launch.",
        ],
        headline="Fresh dog food compounds while incumbents race for veterinary credibility.",
    )


def _global_market() -> GlobalMarketLandscape:
    total = MarketSizingPoint(
        segment="Global pet food",
        size_value=130,
        size_unit="billion",
        year=datetime.now(tz=UTC).year,
        cagr_percent=6.0,
        sources=[_SRC],
    )
    seg = MarketSizingPoint(
        segment="Fresh / human-grade dog food",
        size_value=12,
        size_unit="billion",
        year=datetime.now(tz=UTC).year,
        cagr_percent=20.0,
        sources=[_SRC],
    )
    return GlobalMarketLandscape(
        conclusion="Fresh is the fastest-growing slice of a large, steady pet-food market.",
        global_market_sizing=total,
        primary_segment_sizing=[seg],
    )


def _regional() -> RegionalMarketPulse:
    return RegionalMarketPulse(
        conclusion="The US leads fresh dog food, with rising health-claim scrutiny.",
    )


def _competitor(slug: str, name: str, followers: int, threat: str, move: str) -> CompetitorProfile:
    return CompetitorProfile(
        name=name,
        slug=slug,
        country_hq="US",
        ig_handle=slug,
        ig_followers_count=followers,
        ig_posts_last_30d=18,
        ig_avg_engagement_rate=0.032,
        ig_follower_growth_90d_pct=6.0,
        threat_level=threat,  # type: ignore[arg-type]
        data_completeness_pct=0.7,
        strengths=["Strong brand trust", "High content cadence"],
        cautions=["Premium price ceiling"],
        strategic_moves_recent=[
            StrategicMove(
                move_date=date(
                    datetime.now(tz=UTC).year, max(datetime.now(tz=UTC).month - 1, 1), 1
                ),
                move_type="campaign",
                headline=move,
                source_url="https://news.demo-source.io/pet-dtc",
                source_name="Demo Trade Press",
                so_what="Raises the bar on acquisition creative for the category.",
                threat_level="p1",
            )
        ],
    )


def _competitive(n: int = 3) -> CompetitiveLandscape:
    players = [
        _competitor(
            "thefarmersdog",
            "The Farmer's Dog",
            1_200_000,
            "direct",
            "Launched a vet-endorsement campaign.",
        ),
        _competitor("ollie", "Ollie", 480_000, "direct", "Expanded its fresh-bake line."),
        _competitor(
            "spotandtango",
            "Spot & Tango",
            210_000,
            "adjacent",
            "Pushed an UnKibble retargeting push.",
        ),
    ]
    return CompetitiveLandscape(
        conclusion="The Farmer's Dog leads; Ollie is the closest fast-follower on content.",
        global_players=players[:n],
        social_synthesis="Founder-led sourcing Reels outperform product shots across the set.",
    )


def _brand_positioning() -> BrandPositioning:
    return BrandPositioning(
        conclusion="Barkwell sits mid-market: a credible sourcing story but thin paid presence.",
        quadrant_position="Mid price, high transparency; under-invested in paid acquisition.",
        strengths=["Transparent sourcing", "Vet-formulated recipes"],
        weaknesses=["Small ad budget", "Lower brand awareness"],
        implications=[
            "Double down on the sourcing-transparency wedge",
            "Test founder-led Reels before incumbents saturate it",
        ],
    )


def _consumer() -> ConsumerSignals:
    return ConsumerSignals(
        conclusion="Demand is steady among millennial dog parents who research ingredients.",
        audience_adoption="Surveys show rising willingness to pay for vet-formulated fresh food.",
        seasonal_context="Adoption spikes at the new year and the autumn back-to-routine window.",
    )


def _technology() -> TechnologyTrends:
    today = date(datetime.now(tz=UTC).year, max(datetime.now(tz=UTC).month - 1, 1), 1)
    return TechnologyTrends(
        conclusion="AI nutrition and vet telehealth are the trends reshaping the category.",
        trends=[
            TechTrendItem(
                trend_name="AI nutrition personalization",
                trend_slug="ai-nutrition",
                description="Personalized portioning and recipes driven by a pet profile.",
                relevance_for_brand="A differentiator if paired with the sourcing story.",
                competitor_maturities=[
                    TrendMaturity(
                        trend_slug="ai-nutrition",
                        competitor_slug="thefarmersdog",
                        maturity_score=2,
                        observed_date=today,
                    ),
                    TrendMaturity(
                        trend_slug="ai-nutrition",
                        competitor_slug="ollie",
                        maturity_score=1,
                        observed_date=today,
                    ),
                ],
            ),
            TechTrendItem(
                trend_name="Embedded vet telehealth",
                trend_slug="vet-telehealth",
                description="In-app access to veterinary guidance bundled with the subscription.",
                relevance_for_brand="Supports the vet-credibility wedge.",
                competitor_maturities=[
                    TrendMaturity(
                        trend_slug="vet-telehealth",
                        competitor_slug="thefarmersdog",
                        maturity_score=1,
                        observed_date=today,
                    ),
                ],
            ),
        ],
    )


def _strategic() -> StrategicRecommendations:
    return StrategicRecommendations(
        conclusion="Defend the sourcing wedge and close the paid-acquisition gap.",
        monthly_tactical=[
            StrategicRecommendation(
                priority="P0",
                horizon="month",
                category="content",
                action="Ship a founder-led sourcing Reel series",
                rationale="Founder sourcing stories outperform across the set (Section 4).",
                effort_estimate="S",
                success_metric="Reel save-rate above the category median within 30 days.",
                confidence="H",
                impact=8,
                confidence_score=7,
                ease=7,
                evidence_section_refs=["Section 4"],
                competitor_move_refs=["https://news.demo-source.io/pet-dtc"],
            ),
            StrategicRecommendation(
                priority="P1",
                horizon="quarter",
                category="positioning",
                action="Stand up a vet-advisory credential program",
                rationale="Incumbents are racing for veterinary credibility (Section 1).",
                effort_estimate="M",
                success_metric="A published vet-advisory panel and claims review.",
                confidence="M",
                impact=7,
                confidence_score=6,
                ease=5,
                evidence_section_refs=["Section 1", "Section 4"],
                competitor_move_refs=["https://news.demo-source.io/pet-dtc"],
            ),
        ],
    )


def _canned(schema: type) -> Any:
    builders: dict[type, Any] = {
        Scoreboard: lambda: _scoreboard("2026-04"),
        ExecutiveSummary: _exec_summary,
        GlobalMarketLandscape: _global_market,
        RegionalMarketPulse: _regional,
        CompetitiveLandscape: _competitive,
        BrandPositioning: _brand_positioning,
        ConsumerSignals: _consumer,
        TechnologyTrends: _technology,
        StrategicRecommendations: _strategic,
        QAVerdict: lambda: QAVerdict(decision="approved", summary="Demo review: approved."),
    }
    builder = builders.get(schema)
    return builder() if builder else None


# ---------------------------------------------------------------------------
# Fake LLM (drives the research loop + returns canned structured output)
# ---------------------------------------------------------------------------


class _FakeChatModel:
    """A fake chat model: drives the research supervisor/researcher loop with no network."""

    def __init__(self, tool_names: tuple[str, ...] = ()) -> None:
        self._tool_names = tool_names

    def bind_tools(self, tools: list[Any]) -> _FakeChatModel:
        names = tuple(t.__name__ if isinstance(t, type) else getattr(t, "name", "") for t in tools)
        return _FakeChatModel(names)

    async def ainvoke(self, messages: list[Any], *args: Any, **kwargs: Any) -> AIMessage:
        if "ConductResearch" in self._tool_names:  # supervisor
            prior = any(
                getattr(m, "tool_calls", None) for m in messages if type(m).__name__ == "AIMessage"
            )
            if prior:
                return AIMessage(
                    content="", tool_calls=[{"name": "ResearchComplete", "args": {}, "id": "rc"}]
                )
            calls = [
                {
                    "name": "ConductResearch",
                    "args": {
                        "research_topic": f"Research {tok}",
                        "section_target": tok,
                        "depth": "quick",
                        "preferred_sources": [],
                    },
                    "id": f"cr{i}",
                }
                for i, tok in enumerate(_SECTION_TOKENS)
            ]
            return AIMessage(content="", tool_calls=calls)
        if self._tool_names:  # researcher: no tool calls -> go straight to compress
            return AIMessage(content="", tool_calls=[])
        return AIMessage(content="Demo finding: the fresh dog-food category grew this period.")


class DemoRouter(LLMRouter):
    """A router that never touches a provider: fake chat model + canned structured output."""

    def __init__(self) -> None:
        super().__init__(default_llm_config())

    def chat_model(self, role: Any, *, fallback: bool = False, temperature: float = 0.0) -> Any:
        return _FakeChatModel()

    async def call_resilient(self, role: Any, schema: type, messages: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        return _canned(schema)


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------


def _demo_settings() -> Settings:
    return Settings(
        brand=BrandConfig(
            name="Barkwell", region="US", description="Fresh, vet-formulated dog food sold direct."
        ),
        niche="fresh dog food",
    )


def _build_prior_report(period: str) -> MarketReport:
    """A canned prior-month report (slightly different) so MoM shows real deltas."""
    return MarketReport(
        report_id=f"report-{period}",
        period=period,
        scoreboard=_scoreboard(period, market_value="$2.0B"),
        executive_summary=_exec_summary(),
        global_market=_global_market(),
        regional_pulse=_regional(),
        competitive_landscape=_competitive(
            n=2
        ),  # one fewer competitor -> "new competitor" next period
        brand_positioning=_brand_positioning(),
        consumer_signals=_consumer(),
        technology_trends=_technology(),
        strategic_recommendations=_strategic(),
        appendix=AppendixSection(
            methodology="Demo prior report.",
            confidence_legend="[H]/[M]/[L].",
            all_sources_referenced=[_SRC],
        ),
    )


async def run_demo() -> MarketReport | None:
    """Run the full pipeline hermetically on canned data; return the rendered report."""
    from ..storage.store import Store

    settings = _demo_settings()
    store = Store(":memory:")
    store.save_report(_build_prior_report("2026-03"))  # seed prior month for the MoM diff
    logger.info("demo_start", brand=settings.brand.name)
    report = await run_pipeline(
        settings, month="2026-04", router=DemoRouter(), store=store, offline=True
    )
    store.close()
    return report

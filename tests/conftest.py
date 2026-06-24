"""Shared test fixtures: a minimal but valid MarketReport builder."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from gtm_agent.models import (
    AppendixSection,
    BrandPositioning,
    CompetitiveLandscape,
    ConsumerSignals,
    ExecutiveSummary,
    GlobalMarketLandscape,
    KPITile,
    MarketReport,
    MarketSizingPoint,
    RegionalMarketPulse,
    Scoreboard,
    StrategicRecommendations,
    TechnologyTrends,
)


def build_minimal_report(period: str = "2026-04") -> MarketReport:
    """A fully valid MarketReport with the smallest content that passes validation."""
    year = datetime.now(tz=UTC).year
    sizing = MarketSizingPoint(segment="Total market", size_value=10.0, year=year, sources=[])
    return MarketReport(
        report_id=f"report-{period}-demo",
        period=period,
        scoreboard=Scoreboard(
            period=period,
            bluf_bullets=["alpha", "beta", "gamma"],
            hero_kpis=[
                KPITile(label="Market size", value="$10B", delta="+5%", delta_direction="up")
            ],
        ),
        executive_summary=ExecutiveSummary(
            situation="The market is steady.",
            complication="A new entrant shifted the field.",
            resolution="Lean into the premium wedge.",
            key_findings=["finding one detail", "finding two detail"],
        ),
        global_market=GlobalMarketLandscape(
            global_market_sizing=sizing, primary_segment_sizing=[sizing]
        ),
        regional_pulse=RegionalMarketPulse(
            conclusion="Regional momentum holds steady this period."
        ),
        competitive_landscape=CompetitiveLandscape(),
        brand_positioning=BrandPositioning(
            conclusion="We sit mid-market with a clear value wedge.",
            quadrant_position="Middle of the price-quality map.",
            strengths=["fast onboarding"],
            weaknesses=["small ad budget"],
            implications=["scale paid carefully"],
        ),
        consumer_signals=ConsumerSignals(
            conclusion="Demand is steady across the core audience.",
            audience_adoption="Adoption is rising among younger buyers.",
            seasonal_context="Q2 brings a seasonal uptick.",
        ),
        technology_trends=TechnologyTrends(
            conclusion="AI dominates the product roadmap.", trends=[]
        ),
        strategic_recommendations=StrategicRecommendations(),
        appendix=AppendixSection(
            methodology="Agentic web research plus multi-source enrichment.",
            confidence_legend="H high, M medium, L low.",
            all_sources_referenced=[],
        ),
    )


@pytest.fixture
def make_report() -> Callable[[str], MarketReport]:
    """Return the minimal-report builder (call with an optional period)."""
    return build_minimal_report

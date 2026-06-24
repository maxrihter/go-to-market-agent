"""Output tests: report lowers to the IR and renders clean, well-formed Markdown."""

from __future__ import annotations

from collections.abc import Callable

from gtm_agent.integrations.output import render_markdown, to_render_model
from gtm_agent.models import CompetitorProfile, MarketReport, StrategicRecommendation


def test_to_render_model_has_all_sections(make_report: Callable[[str], MarketReport]) -> None:
    rm = to_render_model(make_report("2026-04"), brand_name="Acme")
    keys = {s.key for s in rm.sections}
    assert keys == {
        "executive_summary",
        "global_market",
        "regional_pulse",
        "competitive_landscape",
        "brand_positioning",
        "consumer_signals",
        "technology_trends",
        "strategic_recommendations",
        "appendix",
    }
    assert rm.title == "Acme: Market Intelligence"
    assert rm.kpis and rm.kpis[0].label == "Market size"


def test_render_markdown_structure(make_report: Callable[[str], MarketReport]) -> None:
    md = render_markdown(make_report("2026-04"), brand_name="Acme")
    assert md.startswith("# Acme: Market Intelligence")
    for heading in (
        "## Scoreboard",
        "## Executive summary",
        "## Competitive landscape",
        "## Strategic recommendations",
        "## Appendix",
    ):
        assert heading in md
    assert "Market size" in md


def test_render_markdown_has_no_em_dash(make_report: Callable[[str], MarketReport]) -> None:
    """The output voice forbids em-dashes."""
    md = render_markdown(make_report("2026-04"))
    assert "—" not in md


def test_markdown_escapes_pipes_and_newlines(make_report: Callable[[str], MarketReport]) -> None:
    report = make_report("2026-04")
    report.competitive_landscape.global_players.append(
        CompetitorProfile(name="Acme | Co\nInc", country_hq="US")
    )
    report.strategic_recommendations.monthly_tactical.append(
        StrategicRecommendation(
            priority="P0",
            horizon="month",
            category="content",
            action="Test A | B variant",
            rationale="because section 1",
            effort_estimate="S",
            success_metric="conversions up",
            evidence_section_refs=["S1"],
        )
    )
    md = render_markdown(report)
    # Card heading: newline collapsed (pipe is fine inside a heading).
    assert "### Acme | Co Inc" in md
    # Table cell: pipe escaped so the recommendations table stays well-formed.
    assert r"Test A \| B variant" in md
    # No stray newline split a table row mid-cell.
    assert "Acme | Co\nInc" not in md

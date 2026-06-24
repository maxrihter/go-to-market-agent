"""Assembly tests: full build, stub fill for missing sections, source aggregation, MoM."""

from __future__ import annotations

from collections.abc import Callable

from gtm_agent.engine.nodes.assembly import assemble_final_report
from gtm_agent.models import (
    GlobalMarketLandscape,
    MarketReport,
    MarketSizingPoint,
    MoMDiffStructured,
    SourceRef,
)


async def test_assembles_from_section_slots(make_report: Callable[[str], MarketReport]) -> None:
    rep = make_report("2026-04")
    state = {
        "period": "2026-04",
        "section_global_market": rep.global_market,
        "section_competitive": rep.competitive_landscape,
        "section_brand_positioning": rep.brand_positioning,
    }
    out = await assemble_final_report(state, None)
    assert isinstance(out["report"], MarketReport)
    assert out["report"].period == "2026-04"


async def test_stubs_missing_sections() -> None:
    out = await assemble_final_report({"period": "2026-04"}, None)
    report = out["report"]
    assert isinstance(report, MarketReport)  # all 10 sections stubbed into a valid report
    assert report.regional_pulse.conclusion  # stub text present


async def test_attaches_mom_diff() -> None:
    state = {
        "period": "2026-04",
        "mom_diff": MoMDiffStructured(is_first_period=True),
        "mom_narrative": "First period observed.",
    }
    out = await assemble_final_report(state, None)
    assert out["report"].appendix.mom_diff_structured.is_first_period is True
    assert out["report"].appendix.what_changed_since_last_period == "First period observed."


async def test_aggregates_real_sources_only() -> None:
    real = SourceRef(title="Real", url="https://research.realsite.io/report")
    fake = SourceRef(title="Fake", url="https://example.com/x")  # url normalized to "" by the model
    sizing = MarketSizingPoint(segment="Total", size_value=10, year=2026, sources=[real, fake])
    gm = GlobalMarketLandscape(global_market_sizing=sizing, primary_segment_sizing=[sizing])
    out = await assemble_final_report({"period": "2026-04", "section_global_market": gm}, None)
    urls = [s.url for s in out["report"].appendix.all_sources_referenced]
    assert "https://research.realsite.io/report" in urls
    assert "" not in urls and "https://example.com/x" not in urls

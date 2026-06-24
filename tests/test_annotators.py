"""Annotator tests: MoM diff, prior-metric no-op, persistence, HITL overrides."""

from __future__ import annotations

from collections.abc import Callable

from gtm_agent.engine.nodes.annotators import (
    compute_mom_node,
    enrich_with_prior_metrics_node,
    store_report_node,
)
from gtm_agent.engine.nodes.overrides import apply_overrides_node
from gtm_agent.models import MarketReport
from gtm_agent.storage.store import Store


async def test_mom_first_period() -> None:
    out = await compute_mom_node({"period": "2026-04"}, None, store=Store(":memory:"))
    assert out["mom_diff"].is_first_period is True


async def test_mom_diff_against_prior(make_report: Callable[[str], MarketReport]) -> None:
    store = Store(":memory:")
    store.save_report(make_report("2026-03"))
    rep = make_report("2026-04")
    state = {
        "period": "2026-04",
        "section_scoreboard": rep.scoreboard,
        "section_competitive": rep.competitive_landscape,
        "section_tech": rep.technology_trends,
    }
    out = await compute_mom_node(state, None, store=store)
    assert out["mom_diff"].is_first_period is False
    # Same KPI label present in both periods -> one tracked delta.
    assert any(d.label == "Market size" for d in out["mom_diff"].kpi_deltas)


async def test_store_report_persists(make_report: Callable[[str], MarketReport]) -> None:
    store = Store(":memory:")
    await store_report_node(
        {"report": make_report("2026-04"), "qa_status": "pending"}, None, store=store
    )
    assert store.fetch_previous_report("2026-05") is not None


async def test_store_report_skips_on_fail(make_report: Callable[[str], MarketReport]) -> None:
    store = Store(":memory:")
    await store_report_node(
        {"report": make_report("2026-04"), "qa_status": "fail"}, None, store=store
    )
    assert store.fetch_previous_report("2026-05") is None


async def test_prior_metrics_noop_without_section() -> None:
    out = await enrich_with_prior_metrics_node({"period": "2026-04"}, None, store=Store(":memory:"))
    assert out == {}


async def test_apply_overrides_fills_weak_field(make_report: Callable[[str], MarketReport]) -> None:
    store = Store(":memory:")
    store.upsert_override(
        "brand_positioning.sentiment_summary", "Sentiment improved notably across reviews."
    )
    report = make_report("2026-04")  # sentiment_summary is None (weak)
    out = await apply_overrides_node({"report": report}, None, store=store)
    assert out["report"].brand_positioning.sentiment_summary == (
        "Sentiment improved notably across reviews."
    )
    # Override is marked applied (not returned as active again).
    assert store.fetch_active_overrides()[0]["applied_to_reports"] == [report.report_id]


async def test_apply_overrides_reverts_invalid_value(
    make_report: Callable[[str], MarketReport],
) -> None:
    store = Store(":memory:")
    # A string override into a list field is invalid; it must be rejected and reverted.
    store.upsert_override("brand_positioning.strengths", "this is a string, not a list")
    report = make_report("2026-04")
    report.brand_positioning.strengths = []  # weak (empty) so the override is attempted
    await apply_overrides_node({"report": report}, None, store=store)
    assert report.brand_positioning.strengths == []  # reverted, payload not corrupted

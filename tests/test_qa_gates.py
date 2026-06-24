"""QA tests: deterministic gates, cross-ref validation, reviewer node + router."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gtm_agent.engine.nodes.assembly import assemble_final_report
from gtm_agent.engine.nodes.qa_gates import (
    pre_publish_qa_agent_node,
    qa_agent_decision_router,
    run_all_gates,
    validate_cross_references,
)
from gtm_agent.models import MarketReport, QAVerdict, StrategicRecommendation


class _FakeRouter:
    def __init__(self, result: Any = None) -> None:
        self._result = result

    async def call_resilient(self, *a: Any, **kw: Any) -> Any:
        return self._result


def _rec(
    category: str, action: str, *, move_refs: list[str] | None = None
) -> StrategicRecommendation:
    return StrategicRecommendation(
        priority="P1",
        horizon="month",
        category=category,  # type: ignore[arg-type]
        action=action,
        rationale="Because the analysis shows it.",
        effort_estimate="M",
        success_metric="A measurable outcome.",
        evidence_section_refs=["Section 4"],
        competitor_move_refs=move_refs or [],
    )


def test_clean_report_passes(make_report: Callable[[str], MarketReport]) -> None:
    passed, issues = run_all_gates(make_report("2026-04"))
    assert passed and not issues


def test_tautology_gate_fails(make_report: Callable[[str], MarketReport]) -> None:
    rep = make_report("2026-04")
    rep.strategic_recommendations.monthly_tactical.append(
        _rec("timing", "Conduct analysis of the market")
    )
    passed, issues = run_all_gates(rep)
    assert not passed and any("Tautological" in i for i in issues)


def test_evidence_chain_gate_fails(make_report: Callable[[str], MarketReport]) -> None:
    rep = make_report("2026-04")
    rep.strategic_recommendations.monthly_tactical.append(
        _rec("paid", "Launch a paid acquisition push")
    )
    passed, issues = run_all_gates(rep)
    assert not passed and any("competitor-move reference" in i for i in issues)


def test_forbidden_entity_gate_fails(make_report: Callable[[str], MarketReport]) -> None:
    rep = make_report("2026-04")  # brand_positioning.conclusion mentions "value wedge"
    passed, issues = run_all_gates(rep, forbidden_keywords=("value wedge",))
    assert not passed and any("Forbidden entity" in i for i in issues)


def test_validate_cross_references_ok(make_report: Callable[[str], MarketReport]) -> None:
    vr = validate_cross_references(make_report("2026-04"))
    assert vr.ok is True


async def test_content_floor_blocks_fully_stubbed_report() -> None:
    out = await assemble_final_report({"period": "2026-04"}, None)  # every section stubbed
    passed, issues = run_all_gates(out["report"])
    assert not passed and any("substantive content" in i for i in issues)


def test_decision_router() -> None:
    assert qa_agent_decision_router({"qa_verdict": QAVerdict(decision="rejected")}) == "reject"
    assert qa_agent_decision_router({"qa_verdict": QAVerdict(decision="approved")}) == "publish"
    assert qa_agent_decision_router({}) == "publish"


async def test_reviewer_node(make_report: Callable[[str], MarketReport]) -> None:
    out = await pre_publish_qa_agent_node(
        {"report": make_report("2026-04")}, None, router=_FakeRouter(QAVerdict(decision="approved"))
    )
    assert out["qa_verdict"].decision == "approved"


async def test_reviewer_defaults_to_approved_when_unavailable(
    make_report: Callable[[str], MarketReport],
) -> None:
    out = await pre_publish_qa_agent_node(
        {"report": make_report("2026-04")}, None, router=_FakeRouter(None)
    )
    assert out["qa_verdict"].decision == "approved"

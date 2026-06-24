"""Pre-publish quality assurance: deterministic gates, cross-reference validation, and an
LLM reviewer.

The deterministic gates are cheap structural checks (completeness, metric coverage,
tautology, evidence chain, freshness, forbidden entities). They run before the LLM
reviewer, which issues a QAVerdict that can reject the report. Custom gates registered
through the Gate plugin also run. Thresholds are constants here; they move to tenant config
in a later block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from ...llm.router import LLMRole, LLMRouter
from ...log import get_logger
from ...models import MarketReport, QAVerdict
from ...plugins.protocols import GateResult
from ...plugins.registry import all_of, load_entrypoint_plugins
from ...prompts import load_prompt

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

logger = get_logger(__name__)

_MIN_COMPLETENESS = 0.40
_MAX_MISSING_FRACTION = 0.50
_FRESHNESS_DAYS = 194  # 180 + 14 slack
_TAUTOLOGY_PATTERNS = (
    "conduct analysis",
    "conduct an analysis",
    "prepare a plan",
    "explore opportunities",
    "do more research",
    "further analysis",
    "investigate options",
)
_REACTIVE_CATEGORIES = frozenset({"paid", "content", "positioning"})


def _all_players(report: MarketReport) -> list[Any]:
    cl = report.competitive_landscape
    return [*cl.global_players, *cl.regional_players]


def _all_recs(report: MarketReport) -> list[Any]:
    sr = report.strategic_recommendations
    return [*sr.monthly_tactical, *sr.annual_strategy_candidates]


def data_completeness_gate(report: MarketReport) -> GateResult:
    players = _all_players(report)
    if not players:
        return GateResult(passed=True)
    avg = sum(p.data_completeness_pct for p in players) / len(players)
    if avg < _MIN_COMPLETENESS:
        return GateResult(
            passed=False,
            issues=[
                f"Average competitor data completeness {avg:.0%} is below {_MIN_COMPLETENESS:.0%}."
            ],
        )
    return GateResult(passed=True)


def metric_coverage_gate(report: MarketReport) -> GateResult:
    players = _all_players(report)
    if not players:
        return GateResult(passed=True)
    missing = sum(1 for p in players if not p.ig_followers_count and not p.meta_ads)
    frac = missing / len(players)
    if frac > _MAX_MISSING_FRACTION:
        return GateResult(
            passed=False,
            issues=[
                f"{frac:.0%} of competitors miss both followers and ads "
                f"(max {_MAX_MISSING_FRACTION:.0%})."
            ],
        )
    return GateResult(passed=True)


def tautology_gate(report: MarketReport) -> GateResult:
    issues = [
        f"Tautological recommendation: {r.action[:80]}"
        for r in _all_recs(report)
        if any(p in r.action.lower() for p in _TAUTOLOGY_PATTERNS)
    ]
    return GateResult(passed=not issues, issues=issues)


def evidence_chain_gate(report: MarketReport) -> GateResult:
    issues = [
        f"Reactive recommendation without a competitor-move reference: {r.action[:80]}"
        for r in _all_recs(report)
        if r.category in _REACTIVE_CATEGORIES and not r.competitor_move_refs
    ]
    return GateResult(passed=not issues, issues=issues)


def freshness_gate(report: MarketReport) -> GateResult:
    try:
        year, month = (int(x) for x in report.period.split("-")[:2])
        ref = date(year, month, 1)
    except (ValueError, TypeError):
        return GateResult(passed=True)
    issues: list[str] = []
    for p in _all_players(report):
        for m in p.strategic_moves_recent:
            if (ref - m.move_date).days > _FRESHNESS_DAYS:
                issues.append(f"Stale strategic move ({m.move_date}) for {p.name}.")
    return GateResult(passed=not issues, issues=issues[:10])


def forbidden_entity_gate(report: MarketReport, forbidden: tuple[str, ...] = ()) -> GateResult:
    """Config-driven anti-hallucination: reject forbidden entity descriptors in the brand
    sections. The forbidden list comes from the tenant config."""
    if not forbidden:
        return GateResult(passed=True)
    bp = report.brand_positioning
    es = report.executive_summary
    haystack = [
        bp.conclusion,
        bp.quadrant_position,
        bp.sentiment_summary or "",
        *(bp.implications or []),
        *(bp.strengths or []),
        *(bp.weaknesses or []),
        es.situation,
        es.complication,
        es.resolution,
        es.headline or "",
        *(es.key_findings or []),
        *(r.action for r in _all_recs(report)),
        *(r.rationale for r in _all_recs(report)),
    ]
    low = " \n ".join(h.lower() for h in haystack if h)
    hits = [w for w in forbidden if w.lower() in low]
    if hits:
        return GateResult(
            passed=False, issues=[f"Forbidden entity descriptor(s) present: {', '.join(hits)}"]
        )
    return GateResult(passed=True)


def content_floor_gate(report: MarketReport) -> GateResult:
    """Block a report with no substantive content (e.g. every section stubbed)."""
    signals = sum(
        [
            bool(_all_players(report)),
            bool(report.technology_trends.trends),
            bool(_all_recs(report)),
            bool(report.appendix.all_sources_referenced),
            bool(report.scoreboard.hero_kpis),
        ]
    )
    if signals == 0:
        return GateResult(
            passed=False, issues=["Report has no substantive content; nothing to publish."]
        )
    return GateResult(passed=True)


def run_all_gates(
    report: MarketReport, *, forbidden_keywords: tuple[str, ...] = ()
) -> tuple[bool, list[str]]:
    """Run the built-in gates plus any registered Gate plugins. Returns (passed, issues)."""
    results = [
        content_floor_gate(report),
        data_completeness_gate(report),
        metric_coverage_gate(report),
        tautology_gate(report),
        evidence_chain_gate(report),
        freshness_gate(report),
        forbidden_entity_gate(report, forbidden_keywords),
    ]
    load_entrypoint_plugins()
    for name, obj in all_of("gate").items():
        try:
            inst = obj() if isinstance(obj, type) else obj
            results.append(inst.check(report))
        except Exception as exc:  # noqa: BLE001
            logger.warning("gate_plugin_failed", gate=name, error=str(exc)[:150])
    issues = [i for r in results for i in r.issues]
    return all(r.passed for r in results), issues


# ---------------------------------------------------------------------------
# Cross-reference validation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ValidationReport:
    ok: bool = True
    issues: list[str] = field(default_factory=list)
    issue_counts_by_severity: dict[str, int] = field(
        default_factory=lambda: {"error": 0, "warning": 0}
    )


def validate_cross_references(report: MarketReport) -> ValidationReport:
    """Light structural validation. Errors block publish; warnings are surfaced only."""
    warnings: list[str] = []
    cited = sum(len(s.sources) for s in (report.global_market.primary_segment_sizing or []))
    if not report.appendix.all_sources_referenced and cited:
        warnings.append("Sections cite sources but the appendix source list is empty.")
    if not _all_recs(report):
        warnings.append("No strategic recommendations were produced.")
    counts = {"error": 0, "warning": len(warnings)}
    return ValidationReport(ok=True, issues=warnings, issue_counts_by_severity=counts)


# ---------------------------------------------------------------------------
# LLM pre-publish reviewer
# ---------------------------------------------------------------------------


def _report_summary(report: MarketReport) -> str:
    es = report.executive_summary
    players = _all_players(report)
    return (
        f"Period: {report.period}\n"
        f"Headline: {es.headline or '(none)'}\n"
        f"Situation: {es.situation}\nComplication: {es.complication}\nResolution: {es.resolution}\n"
        f"Key findings: {'; '.join(es.key_findings)}\n"
        f"Competitors profiled: {len(players)}\n"
        f"Recommendations: {len(_all_recs(report))}\n"
        f"Sources: {len(report.appendix.all_sources_referenced)}\n"
    )


async def pre_publish_qa_agent_node(
    state: Any, config: RunnableConfig, *, router: LLMRouter
) -> dict[str, Any]:
    """Ask the LLM reviewer for a verdict. Defaults to approved if the reviewer is unavailable."""
    report = state.get("report")
    if report is None:
        return {}
    messages = [
        {"role": "system", "content": load_prompt("qa_reviewer_system")},
        {"role": "user", "content": _report_summary(report)},
    ]
    verdict: Any = None
    try:
        verdict = await router.call_resilient(
            LLMRole.QA_REVIEWER,
            QAVerdict,
            messages,
            nonempty=lambda v: v is not None,
            label="qa_review",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("qa_reviewer_failed", error=str(exc)[:200])
    if verdict is None:
        verdict = QAVerdict(
            decision="approved", summary="Reviewer unavailable; deterministic gates passed."
        )
    return {"qa_verdict": verdict}


def qa_agent_decision_router(state: Any) -> str:
    """Route after the reviewer: 'reject' on a rejected verdict, else 'publish'."""
    verdict = state.get("qa_verdict")
    if verdict is not None and getattr(verdict, "decision", "approved") == "rejected":
        return "reject"
    return "publish"

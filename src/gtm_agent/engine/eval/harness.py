"""LLM-judge evaluation harness (`gtm eval`).

Scores a produced report on quality dimensions an analyst cares about: factual grounding,
section completeness, recommendation traceability, and clarity. Combines a deterministic
floor (the same QA gates the pipeline runs) with an LLM-judge score via the router. Works
offline (deterministic only) and adds the judge scores when an LLM key is available.

deepeval is an optional advanced-metrics backend (the [eval] extra); the core harness uses
the router and needs no extra install.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ...config import default_settings
from ...integrations.output import render_markdown
from ...llm.router import LLMRole, LLMRouter
from ...log import get_logger
from ...models import MarketReport
from ...prompts import load_prompt
from ..nodes.qa_gates import run_all_gates

if TYPE_CHECKING:
    from ...llm.router import LLMRouter as Router

logger = get_logger(__name__)


class EvalScores(BaseModel):
    """Per-dimension judge scores (1-5)."""

    grounding: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)
    traceability: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    notes: str = ""


def _latest_report_json() -> Path | None:
    outdir = Path("output")
    if not outdir.is_dir():
        return None
    jsons = sorted(outdir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsons[0] if jsons else None


async def run_eval(report: Path | None = None, *, router: Router | None = None) -> str:
    """Score a report (defaults to the latest in output/) and return a summary."""
    path = report or _latest_report_json()
    if path is None or not path.exists():
        msg = "No report JSON found; run `gtm run` or `gtm demo` first."
        raise FileNotFoundError(msg)

    rep = MarketReport.model_validate_json(path.read_text(encoding="utf-8"))
    passed, issues = run_all_gates(rep)
    players = rep.competitive_landscape.global_players + rep.competitive_landscape.regional_players
    lines = [
        f"Evaluation of {rep.report_id}",
        "",
        "Deterministic checks:",
        f"- gates: {'PASS' if passed else 'FAIL'} ({len(issues)} issue(s))",
        f"- sources cited: {len(rep.appendix.all_sources_referenced)}",
        f"- competitors profiled: {len(players)}",
        f"- recommendations: {len(rep.strategic_recommendations.monthly_tactical)}",
    ]
    for issue in issues[:5]:
        lines.append(f"  - {issue}")

    router = router or LLMRouter(default_settings().llm)
    scores: Any = None
    try:
        messages = [
            {"role": "system", "content": load_prompt("eval_judge_system")},
            {"role": "user", "content": render_markdown(rep)[:6000]},
        ]
        scores = await router.call_resilient(
            LLMRole.QA_REVIEWER,
            EvalScores,
            messages,
            nonempty=lambda s: s is not None,
            label="eval",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("eval_judge_failed", error=str(exc)[:200])

    if scores is not None:
        overall = (
            scores.grounding + scores.completeness + scores.traceability + scores.clarity
        ) / 4
        lines += [
            "",
            "LLM-judge scores (1-5):",
            f"- grounding: {scores.grounding}",
            f"- completeness: {scores.completeness}",
            f"- traceability: {scores.traceability}",
            f"- clarity: {scores.clarity}",
            f"- overall: {overall:.1f}",
            f"  {scores.notes}".rstrip(),
        ]
    else:
        lines += ["", "LLM-judge skipped (no key or unavailable); deterministic checks only."]
    return "\n".join(lines)

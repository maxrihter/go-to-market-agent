"""Cross-section synthesizers: scoreboard, executive summary, strategic recommendations.

These run after the analysts and see all section outputs. They are the interpretation
layer (analysts stay on facts). Each is fail-soft: the scoreboard returns a recoverable
error, the executive summary falls back to a stub, and the recommendations fall back to a
synth-from-raw rescue built from the competitive section's strategic moves.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ...llm.router import LLMRole, LLMRouter
from ...log import get_logger
from ...models import (
    ExecutiveSummary,
    Scoreboard,
    StrategicRecommendation,
    StrategicRecommendations,
)
from ...prompts import load_prompt

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.runnables import RunnableConfig

logger = get_logger(__name__)

_SECTION_SLOTS: tuple[tuple[str, str], ...] = (
    ("Global market", "section_global_market"),
    ("Regional pulse", "section_regional_pulse"),
    ("Competitive landscape", "section_competitive"),
    ("Brand positioning", "section_brand_positioning"),
    ("Consumer signals", "section_consumer"),
    ("Technology trends", "section_tech"),
)


def _any_analyst_output(state: Any) -> bool:
    return any(state.get(slot) is not None for _, slot in _SECTION_SLOTS)


def _serialize_sections(state: Any) -> str:
    parts: list[str] = []
    for title, slot in _SECTION_SLOTS:
        section = state.get(slot)
        if section is None:
            parts.append(f"## {title}\n(no data: the analyst produced no section)")
            continue
        try:
            payload = json.dumps(section.model_dump(mode="json"), ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("synth_serialize_failed", section=title, error=str(exc)[:120])
            payload = str(section)
        parts.append(f"## {title}\n{payload}")
    return "\n\n".join(parts)


async def _synth_call(
    router: LLMRouter,
    schema: type[Any],
    system_prompt: str,
    user_content: str,
    *,
    nonempty: Callable[[Any], bool],
    label: str,
    temperature: float,
) -> Any:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    try:
        return await router.call_resilient(
            LLMRole.SYNTHESIZER,
            schema,
            messages,
            nonempty=nonempty,
            temperature=temperature,
            label=label,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("synth_call_failed", label=label, error=str(exc)[:200])
        return None


async def synthesize_scoreboard(
    state: Any, config: RunnableConfig, *, router: LLMRouter
) -> dict[str, Any]:
    """Scoreboard: BLUF bullets + hero KPIs."""
    if not _any_analyst_output(state):
        return {}
    user_content = (
        f"Period: {state.get('period')}.\n\nSection analysis:\n{_serialize_sections(state)}\n\n"
        f"Assemble the scoreboard per the system prompt."
    )
    result = await _synth_call(
        router,
        Scoreboard,
        load_prompt("synth_scoreboard_system"),
        user_content,
        nonempty=lambda r: bool(getattr(r, "bluf_bullets", None)),
        label="section_scoreboard",
        temperature=0.2,
    )
    if result is None:
        return {"error": ["scoreboard_synth_failed"]}  # recoverable: gate uses a stub
    return {"section_scoreboard": result}


async def synthesize_exec_summary(
    state: Any, config: RunnableConfig, *, router: LLMRouter
) -> dict[str, Any]:
    """Executive summary (SCR). Falls back to a stub so a parse failure cannot block publish."""
    if not _any_analyst_output(state):
        return {}
    user_content = (
        f"Period: {state.get('period')}.\n\nSection analysis:\n{_serialize_sections(state)}\n\n"
        f"Build the executive summary: SCR plus key findings."
    )
    result = await _synth_call(
        router,
        ExecutiveSummary,
        load_prompt("synth_exec_summary_system"),
        user_content,
        nonempty=lambda r: bool(getattr(r, "key_findings", None)),
        label="section_exec_summary",
        temperature=0.2,
    )
    if result is None:
        result = ExecutiveSummary(
            situation="The period summary was generated from partial output; see the sections.",
            complication="Competitive dynamics: see the competitive section for the period.",
            resolution="Strategic direction: see the recommendations section.",
            key_findings=[
                "[M] Synthesizer parse failure; details are in the error logs.",
                "[M] This summary is a stub; the underlying analysis is in the sections.",
            ],
        )
    return {"section_exec_summary": result}


def _rescue_strategic_from_competitive(state: Any) -> StrategicRecommendations:
    """Build tactical recs from the competitive section's high-threat moves when the LLM fails."""
    section = state.get("section_competitive")
    recs: list[StrategicRecommendation] = []
    if section is not None:
        players = [*(section.global_players or []), *(section.regional_players or [])]
        candidates = [
            (p, m)
            for p in players
            for m in (p.strategic_moves_recent or [])
            if m.threat_level in ("p0", "p1")
        ]
        for p, m in candidates[:6]:
            try:
                recs.append(
                    StrategicRecommendation(
                        priority="P1" if m.threat_level == "p0" else "P2",
                        horizon="month",
                        category="positioning",
                        action=(
                            f"Respond to {p.name}: {m.headline[:80]}. Accelerate differentiation."
                        ),
                        rationale=(
                            f"{p.name} made a {m.move_type} move "
                            f"({m.move_date.isoformat()}). {m.so_what}"
                        ),
                        effort_estimate="M",
                        success_metric="A competitor-move review and response plan within 14 days.",
                        evidence_section_refs=["Section 4"],
                        competitor_move_refs=[m.source_url] if m.source_url else [],
                        confidence="L",
                        impact=6,
                        confidence_score=4,
                        ease=5,
                    )
                )
            except Exception:  # noqa: BLE001
                continue
    return StrategicRecommendations(
        conclusion=None, monthly_tactical=recs, annual_strategy_candidates=[]
    )


def _enforce_evidence_chain(recs: StrategicRecommendations) -> StrategicRecommendations:
    """Downgrade a reactive-category rec with no move ref to 'timing' so the QA gate passes."""
    reactive = frozenset({"paid", "content", "positioning"})

    def _fix(items: list[StrategicRecommendation]) -> list[StrategicRecommendation]:
        out: list[StrategicRecommendation] = []
        for r in items:
            if r.category in reactive and not r.competitor_move_refs:
                logger.warning("strategic_rec_downgraded_to_timing", original=r.category)
                out.append(r.model_copy(update={"category": "timing"}))
            else:
                out.append(r)
        return out

    return recs.model_copy(
        update={
            "monthly_tactical": _fix(recs.monthly_tactical),
            "annual_strategy_candidates": _fix(recs.annual_strategy_candidates),
        }
    )


async def synthesize_strategic_recommendations(
    state: Any, config: RunnableConfig, *, router: LLMRouter
) -> dict[str, Any]:
    """Strategic recommendations: ICE-scored, evidence-linked, with a synth-from-raw rescue."""
    if not _any_analyst_output(state):
        return {}
    user_content = (
        f"Period: {state.get('period')}.\n\nFull analysis:\n{_serialize_sections(state)}\n\n"
        f"Build the strategic recommendations: ICE-scored, with section references."
    )
    result = await _synth_call(
        router,
        StrategicRecommendations,
        load_prompt("synth_strategic_system"),
        user_content,
        nonempty=lambda r: bool(getattr(r, "monthly_tactical", None)),
        label="section_strategic",
        temperature=0.3,
    )
    if result is None:
        logger.warning("strategic_synth_using_rescue")
        result = _rescue_strategic_from_competitive(state)
    return {"section_strategic": _enforce_evidence_chain(result)}


SYNTHESIZERS: dict[str, Callable[..., Any]] = {
    "synthesize_scoreboard": synthesize_scoreboard,
    "synthesize_exec_summary": synthesize_exec_summary,
    "synthesize_strategic_recommendations": synthesize_strategic_recommendations,
}

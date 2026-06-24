"""Section analysts: six facts-only nodes built from one factory.

Each analyst filters the research notes for its section, calls the LLM (analyst role) for a
structured section model via the resilient router path, and returns one state slot. The
competitive analyst additionally injects the enriched competitor data so the model copies
real numbers instead of fabricating them.

Analysts describe observed state only; the synthesizers own interpretation. Nodes are
fail-soft: on an LLM/validation failure they return an ``error`` delta and leave the
section empty, so one section cannot abort the whole report.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ...llm.router import LLMRole, LLMRouter
from ...log import get_logger
from ...models import (
    BrandPositioning,
    CompetitiveLandscape,
    ConsumerSignals,
    GlobalMarketLandscape,
    RegionalMarketPulse,
    TechnologyTrends,
)
from ...prompts import load_prompt

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.runnables import RunnableConfig

logger = get_logger(__name__)

_MAX_NOTES_CHARS = 40_000  # keep the per-section payload under context limits


def _filter_notes_for_section(notes: list[str], section_target: str) -> tuple[str, bool]:
    """Return (joined_notes, fell_back_to_full_corpus).

    Notes are tagged ``[section_target]`` by the supervisor. Match on that tag; fall back
    to the full corpus when nothing matches (research is still useful). Truncate to keep
    the payload bounded.
    """
    target = section_target.lower()
    matched = [n for n in notes if target in n.lower()[:200]]
    fell_back = not matched
    joined = "\n\n---\n\n".join(matched or notes)
    if len(joined) > _MAX_NOTES_CHARS:
        joined = joined[:_MAX_NOTES_CHARS] + "\n\n[... truncated due to context limit]"
    return joined, fell_back


def format_competitor_raw_block(state: Any) -> str:
    """Format the enriched competitor data for the competitive analyst to copy verbatim."""
    raw = state.get("competitor_raw") or {}
    if not raw:
        return ""
    fields = [
        ("followers", "ig_followers_count"),
        ("posts_30d", "ig_posts_last_30d"),
        ("ER", "ig_avg_engagement_rate"),
        ("growth_90d_pct", "ig_follower_growth_90d_pct"),
        ("web_visits", "monthly_visits"),
        ("active_ads", "active_ads_count"),
        ("ios_rating", "ios_rating"),
        ("search_interest", "search_interest_direction"),
    ]
    lines = ["## Enriched competitor data (copy these numbers verbatim, do not invent):"]
    for slug, data in raw.items():
        parts = [f"{label}={data[key]}" for label, key in fields if data.get(key) is not None]
        lines.append(f"- {slug}: {', '.join(parts) if parts else 'no enriched metrics'}")
    return "\n".join(lines) + "\n\n"


def _build_user_content(state: Any, augmented: str, notes: str) -> str:
    period = state.get("period", "")
    year = period[:4] if len(period) >= 4 else str(datetime.now(tz=UTC).year)
    return (
        f"Reporting period: {period}. Treat this as the current state of the market.\n"
        f"Cite data from {year} or the prior year; if fresh numbers are missing, write "
        f"'[data unavailable]' rather than using older figures. A sizing year must be the "
        f"current or prior year.\n\n"
        f"{augmented}"
        f"Research findings:\n{notes}\n\n"
        f"Build the section per the rules in the system prompt."
    )


_RETRY_HINT = (
    "The previous attempt did not validate. Return ALL required schema fields, do not "
    "truncate the output, and keep every claim sourced."
)


def _make_analyst(
    section_key: str,
    section_target: str,
    schema: type[BaseModel],
    prompt_name: str,
    *,
    context_augmenter: Callable[[Any], str] | None = None,
) -> Callable[..., Any]:
    """Build an async LangGraph node that produces one section model."""

    async def _node(state: Any, config: RunnableConfig, *, router: LLMRouter) -> dict[str, Any]:
        notes = state.get("notes", [])
        if not notes:
            logger.warning("analyst_no_notes", section=section_key)
            return {}

        filtered, fell_back = _filter_notes_for_section(notes, section_target)
        augmented = context_augmenter(state) if context_augmenter is not None else ""
        system_prompt = load_prompt(prompt_name)
        user_content = _build_user_content(state, augmented, filtered)

        result: Any = None
        for attempt in range(2):
            content = user_content if attempt == 0 else f"{user_content}\n\n---\n{_RETRY_HINT}"
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ]
            try:
                result = await router.call_resilient(
                    LLMRole.ANALYST,
                    schema,
                    messages,
                    nonempty=lambda r: r is not None,
                    label=section_key,
                )
                break
            except Exception as exc:  # noqa: BLE001 (fail-soft per section)
                logger.warning(
                    "analyst_attempt_failed",
                    section=section_key,
                    attempt=attempt,
                    error=str(exc)[:200],
                )

        if result is None:
            logger.error("analyst_failed", section=section_key)
            return {"error": [f"analyst_{section_key}_failed"]}

        logger.info("analyst_section_complete", section=section_key)
        out: dict[str, Any] = {section_key: result}
        if fell_back:
            out["notes_fallback_sections"] = [section_key]
        return out

    return _node


analyze_global_market = _make_analyst(
    "section_global_market", "global market", GlobalMarketLandscape, "analyst_global_market_system"
)
analyze_regional_pulse = _make_analyst(
    "section_regional_pulse", "regional", RegionalMarketPulse, "analyst_regional_pulse_system"
)
analyze_competitive = _make_analyst(
    "section_competitive",
    "competitive",
    CompetitiveLandscape,
    "analyst_competitive_system",
    context_augmenter=format_competitor_raw_block,
)
analyze_brand_positioning = _make_analyst(
    "section_brand_positioning",
    "brand positioning",
    BrandPositioning,
    "analyst_brand_positioning_system",
)
analyze_consumer = _make_analyst(
    "section_consumer", "consumer", ConsumerSignals, "analyst_consumer_system"
)
analyze_tech = _make_analyst("section_tech", "technology", TechnologyTrends, "analyst_tech_system")

# Graph-node-name -> node. The graph binds the router via functools.partial.
ANALYSTS: dict[str, Callable[..., Any]] = {
    "analyze_global_market": analyze_global_market,
    "analyze_regional_pulse": analyze_regional_pulse,
    "analyze_competitive": analyze_competitive,
    "analyze_brand_positioning": analyze_brand_positioning,
    "analyze_consumer": analyze_consumer,
    "analyze_tech": analyze_tech,
}

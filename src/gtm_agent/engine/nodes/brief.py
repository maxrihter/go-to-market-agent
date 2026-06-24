"""Research brief: turn the tenant config into a research brief + per-section briefs.

Deterministic (no LLM): it seeds the research supervisor with one brief per report section,
keyed by the section tokens the analysts filter on. An LLM brief writer is an EXTENDING seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ...config import Settings


async def write_brief(state: Any, config: RunnableConfig, *, settings: Settings) -> dict[str, Any]:
    """Produce research_brief + section_briefs from the tenant config."""
    brand = settings.brand
    region = brand.region or "global"
    niche = settings.niche or "the brand's market"
    period = state.get("period", "")

    section_briefs = {
        "global market": (
            f"Research the global {niche} market for the period around {period}: size, growth, "
            f"CAGR, and the leading segments, with sources."
        ),
        "regional": (
            f"Research the {region} {niche} market: regional sizing, funding events, and "
            f"regulatory changes in the period, with sources."
        ),
        "competitive": (
            f"Research the competitive landscape in {niche}: the main players, their recent "
            f"strategic moves, funding, and positioning."
        ),
        "brand positioning": (
            f"Research how {brand.name} is positioned in {niche} relative to competitors: "
            f"strengths, weaknesses, and market perception."
        ),
        "consumer": (
            f"Research consumer and audience signals in {niche} for {region}: adoption trends, "
            f"search interest, surveys, and seasonal context."
        ),
        "technology": (
            f"Research the technology and product trends shaping {niche}: emerging categories "
            f"and how competitors are adopting them."
        ),
    }
    research_brief = (
        f"Monthly market-intelligence research for {brand.name} ({region}) in {niche}, "
        f"period {period}. Gather sourced, current evidence for every section below."
    )
    return {"research_brief": research_brief, "section_briefs": section_briefs}

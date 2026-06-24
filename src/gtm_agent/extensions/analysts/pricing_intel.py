"""Example Analyst plugin: a dedicated Pricing Intelligence section.

Copy this file to add a 7th report section. Registered under the `analyst` kind as
"pricing_intel" with a new section key. The assembler renders any registered section.

Worked example: the `analyze` body is left for you.
"""

from __future__ import annotations

from typing import Any

from ...plugins import analyst


@analyst("pricing_intel")
class PricingIntelAnalyst:
    """Writes a facts-only section on competitor pricing moves and packaging."""

    name = "pricing_intel"
    section_key = "section_pricing_intel"

    async def analyze(self, ctx: Any) -> Any:
        """Return a populated pricing-intel section model (or None to skip).

        `ctx` exposes the research notes, the enriched watchlist, and the LLM router.
        """
        # ADD: define a Pydantic section model for pricing intelligence,
        # ADD: write a prompt, and call ctx.router.call_resilient("analyst", ...).
        raise NotImplementedError("finish PricingIntelAnalyst.analyze for your use case")

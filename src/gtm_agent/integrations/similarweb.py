"""SimilarWeb-style web analytics via an Apify actor (APIFY_TOKEN). Fail-soft.

Returns monthly visits, bounce rate, and traffic-source mix per domain. The actor id is
configurable; tune it for your Apify plan.
"""

from __future__ import annotations

from typing import Any

from ..log import get_logger
from .apify_client import fetch_dataset, run_actor

logger = get_logger(__name__)

_ACTOR = "tri_angle/fast-similarweb-scraper"


async def fetch_web_analytics(domains: list[str], *, token: str) -> dict[str, dict[str, Any]]:
    """Return {domain: {monthly_visits, bounce_rate_pct, traffic_sources_pct}} for `domains`."""
    domains = [d for d in domains if d]
    if not domains or not token:
        return {}
    try:
        dataset_id = await run_actor(token, _ACTOR, {"websites": domains})
        items = await fetch_dataset(token, dataset_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("similarweb_failed", error=str(exc)[:200])
        return {}

    out: dict[str, dict[str, Any]] = {}
    for it in items:
        domain = (it.get("name") or it.get("domain") or "").lower()
        if not domain:
            continue
        out[domain] = {
            "monthly_visits": it.get("totalVisits") or it.get("estimatedMonthlyVisits"),
            "bounce_rate_pct": it.get("bounceRate"),
            "traffic_sources_pct": it.get("trafficSources") or {},
        }
    return out

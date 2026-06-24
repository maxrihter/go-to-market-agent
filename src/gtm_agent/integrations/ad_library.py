"""Meta Ad Library signal via an Apify actor (APIFY_TOKEN). Fail-soft.

Returns a per-brand active-ad count plus creative themes and platforms. The actor id and
input shape are configurable; tune them for your Apify plan.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..log import get_logger
from .apify_client import fetch_dataset, run_actor

logger = get_logger(__name__)

_ACTOR = "apify/facebook-ads-scraper"


async def fetch_competitor_ads(brands: list[str], *, token: str) -> list[dict[str, Any]]:
    """Return [{advertiser, ad_count, creative_themes, platforms}] for `brands`."""
    if not brands or not token:
        return []
    try:
        dataset_id = await run_actor(
            token, _ACTOR, {"searchTerms": brands, "resultsLimit": 50, "activeStatus": "active"}
        )
        items = await fetch_dataset(token, dataset_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ad_library_failed", error=str(exc)[:200])
        return []

    by_advertiser: dict[str, dict[str, Any]] = {}
    for it in items:
        advertiser = it.get("pageName") or it.get("advertiser") or it.get("searchTerm") or ""
        if not advertiser:
            continue
        entry = by_advertiser.setdefault(
            advertiser,
            {"advertiser": advertiser, "ad_count": 0, "_themes": Counter(), "_platforms": set()},
        )
        entry["ad_count"] += 1
        if theme := (it.get("adText") or it.get("body") or "")[:40]:
            entry["_themes"][theme] += 1
        for plat in it.get("publisherPlatform", []) or []:
            entry["_platforms"].add(plat)

    out: list[dict[str, Any]] = []
    for entry in by_advertiser.values():
        themes = [t for t, _ in entry.pop("_themes").most_common(3)]
        platforms = sorted(entry.pop("_platforms"))
        out.append({**entry, "creative_themes": themes, "platforms": platforms})
    return out

"""DataForSEO SERP signal (paid, DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD). Fail-soft.

Fetches SERP positions for a keyword set and maps which competitor domains rank, producing
a keyword-overlap signal. Part of the optional paid-SEO source set.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..log import get_logger

logger = get_logger(__name__)

_BASE = "https://api.dataforseo.com/v3/serp/google/organic/live/regular"


async def fetch_serp_positions(
    keywords: list[str], *, location_name: str = "United States", language_code: str = "en"
) -> dict[str, list[str]]:
    """Return {keyword: [ranking_domain, ...]} for the keyword set, or {} without creds."""
    login = os.environ.get("DATAFORSEO_LOGIN", "")
    password = os.environ.get("DATAFORSEO_PASSWORD", "")
    keywords = [k for k in keywords if k]
    if not (login and password) or not keywords:
        return {}
    out: dict[str, list[str]] = {}
    payload = [
        {"keyword": kw, "location_name": location_name, "language_code": language_code, "depth": 20}
        for kw in keywords
    ]
    try:
        async with httpx.AsyncClient(timeout=30.0, auth=(login, password)) as client:
            resp = await client.post(_BASE, json=payload)
        if resp.status_code >= 400:
            return {}
        for task in resp.json().get("tasks", []):
            for result in task.get("result", []) or []:
                kw = result.get("keyword", "")
                domains = [
                    item.get("domain", "")
                    for item in result.get("items", []) or []
                    if item.get("domain")
                ]
                if kw:
                    out[kw] = domains
    except Exception as exc:  # noqa: BLE001
        logger.warning("dataforseo_failed", error=str(exc)[:200])
    return out


def compute_keyword_overlap(
    serp: dict[str, list[str]], competitor_domains: dict[str, str]
) -> dict[str, dict[str, Any]]:
    """Map {slug: {ranking_keywords: [...], rank_count: n}} from SERP positions."""
    out: dict[str, dict[str, Any]] = {}
    for slug, domain in competitor_domains.items():
        if not domain:
            continue
        ranked = [kw for kw, domains in serp.items() if any(domain in d for d in domains)]
        if ranked:
            out[slug] = {"ranking_keywords": ranked, "rank_count": len(ranked)}
    return out

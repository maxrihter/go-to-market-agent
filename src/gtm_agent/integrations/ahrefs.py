"""Ahrefs SEO snapshot (paid, AHREFS_API_KEY). Fail-soft: returns {} without a key.

Part of the optional paid-SEO source set; documented in .env.example.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..log import get_logger

logger = get_logger(__name__)

_BASE = "https://api.ahrefs.com/v3/site-explorer/metrics"


async def fetch_ahrefs_batch(domains: list[str]) -> dict[str, dict[str, Any]]:
    """Return {domain: {domain_rating, referring_domains, organic_traffic_monthly}}."""
    api_key = os.environ.get("AHREFS_API_KEY", "")
    domains = [d for d in domains if d]
    if not api_key or not domains:
        return {}
    out: dict[str, dict[str, Any]] = {}
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=25.0, headers=headers) as client:
            for domain in domains:
                resp = await client.get(_BASE, params={"target": domain, "mode": "domain"})
                if resp.status_code >= 400:
                    continue
                m = resp.json().get("metrics", {})
                out[domain] = {
                    "domain_rating": m.get("domain_rating"),
                    "referring_domains": m.get("refdomains"),
                    "organic_traffic_monthly": m.get("org_traffic"),
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("ahrefs_failed", error=str(exc)[:200])
    return out

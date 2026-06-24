"""Wayback Machine CDX signal (free, no key): count of new captured URLs in the last 30 days.

A rough proxy for site/landing-page activity. Fail-soft: returns None on any problem.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from ..log import get_logger

logger = get_logger(__name__)

_CDX_URL = "http://web.archive.org/cdx/search/cdx"


async def fetch_landing_pages_new_30d(domain: str) -> int | None:
    """Count distinct URLs first captured in the last 30 days for `domain`."""
    if not domain:
        return None
    since = (datetime.now(tz=UTC) - timedelta(days=30)).strftime("%Y%m%d")
    params = {
        "url": f"{domain}/*",
        "output": "json",
        "from": since,
        "fl": "original",
        "collapse": "urlkey",
        "limit": "500",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(_CDX_URL, params=params)
        if resp.status_code >= 400:
            return None
        rows = resp.json()
        # First row is the header.
        return max(len(rows) - 1, 0) if isinstance(rows, list) else None
    except Exception as exc:  # noqa: BLE001
        logger.info("wayback_failed", domain=domain, error=str(exc)[:150])
        return None

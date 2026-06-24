"""YouTube channel stats via the Data API v3 (free quota, GOOGLE_API_KEY). Fail-soft.

Resolves each @handle to a channel and returns subscriber / video / view counts.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..log import get_logger

logger = get_logger(__name__)

_BASE = "https://www.googleapis.com/youtube/v3"


async def fetch_channel_stats(handles: list[str]) -> dict[str, dict[str, Any]]:
    """`handles` like ['@brand']; returns {handle: {subscriber_count, video_count, view_count}}."""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key or not handles:
        return {}
    out: dict[str, dict[str, Any]] = {}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for handle in handles:
                params = {"part": "statistics", "forHandle": handle.lstrip("@"), "key": api_key}
                resp = await client.get(f"{_BASE}/channels", params=params)
                if resp.status_code >= 400:
                    continue
                items = resp.json().get("items", [])
                if not items:
                    continue
                stats = items[0].get("statistics", {})
                out[handle] = {
                    "subscriber_count": int(stats.get("subscriberCount", 0) or 0),
                    "video_count": int(stats.get("videoCount", 0) or 0),
                    "view_count": int(stats.get("viewCount", 0) or 0),
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("youtube_failed", error=str(exc)[:200])
    return out

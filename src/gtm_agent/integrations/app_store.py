"""App Store + Google Play signals (free): ratings and review counts.

iOS via the public iTunes lookup API (httpx, no key); Android via the optional
google-play-scraper library. Fail-soft per app.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..log import get_logger

logger = get_logger(__name__)

_ITUNES_LOOKUP = "https://itunes.apple.com/lookup"


async def _ios(app_id: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_ITUNES_LOOKUP, params={"id": app_id})
        results = resp.json().get("results", []) if resp.status_code < 400 else []
        if not results:
            return {}
        r = results[0]
        return {
            "ios_rating": r.get("averageUserRating"),
            "ios_rating_count": r.get("userRatingCount"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("itunes_lookup_failed", app_id=app_id, error=str(exc)[:120])
        return {}


def _android(package: str) -> dict[str, Any]:
    try:
        from google_play_scraper import app  # type: ignore[import-untyped]
    except ImportError:
        return {}
    try:
        data = app(package)
        return {"android_rating": data.get("score"), "android_rating_count": data.get("ratings")}
    except Exception as exc:  # noqa: BLE001
        logger.info("google_play_failed", package=package, error=str(exc)[:120])
        return {}


async def fetch_app_snapshots(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """`entries` items: {slug, ios_app_id?, android_package?} -> {slug: {ratings...}}."""
    out: dict[str, dict[str, Any]] = {}
    for e in entries:
        slug = e.get("slug")
        if not slug:
            continue
        snap: dict[str, Any] = {}
        if e.get("ios_app_id"):
            snap.update(await _ios(str(e["ios_app_id"])))
        if e.get("android_package"):
            snap.update(_android(str(e["android_package"])))
        if snap:
            out[slug] = snap
    return out

"""Google Trends signal via pytrends (free, no key). Fail-soft: returns {} on any problem.

pytrends is a core dependency, but it is an unofficial scraper that rate-limits; every call
is wrapped so a failure degrades to empty rather than aborting enrichment.
"""

from __future__ import annotations

from typing import Any

from ..log import get_logger

logger = get_logger(__name__)


def _direction(values: list[float]) -> tuple[str, float, float]:
    """Return (direction, half-over-half change %, average interest)."""
    if not values:
        return "flat", 0.0, 0.0
    avg = sum(values) / len(values)
    mid = len(values) // 2
    first = values[:mid] or values
    second = values[mid:] or values
    a = sum(first) / len(first)
    b = sum(second) / len(second)
    change = ((b - a) / a * 100.0) if a else 0.0
    direction = "rising" if change > 5 else "falling" if change < -5 else "flat"
    return direction, round(change, 1), round(avg, 1)


def fetch_brand_interest_deltas(keywords: list[str], *, geo: str = "") -> dict[str, dict[str, Any]]:
    """Per-keyword interest direction + half-over-half delta over the last 90 days."""
    if not keywords:
        return {}
    try:
        from pytrends.request import TrendReq  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("pytrends_missing")
        return {}
    out: dict[str, dict[str, Any]] = {}
    try:
        client = TrendReq(hl="en-US", tz=0)
        # pytrends allows up to 5 keywords per request.
        for i in range(0, len(keywords), 5):
            batch = keywords[i : i + 5]
            client.build_payload(batch, timeframe="today 3-m", geo=geo)
            frame = client.interest_over_time()
            for kw in batch:
                if kw in getattr(frame, "columns", []):
                    series = [float(v) for v in frame[kw].tolist()]
                    direction, change, avg = _direction(series)
                    out[kw] = {
                        "trend_direction": direction,
                        "half_change_pct": change,
                        "avg_interest": avg,
                    }
    except Exception as exc:  # noqa: BLE001
        logger.warning("google_trends_failed", error=str(exc)[:200])
    return out

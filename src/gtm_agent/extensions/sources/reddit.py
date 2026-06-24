"""Example Source plugin: Reddit competitor-mention signal.

Copy this file, finish `fetch`, and you have a new data source the enrichment phase
will fold in automatically. Registered under the `source` kind as "reddit".

This is a worked example, not a finished connector: the `fetch` body is left for you.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...plugins import source


@source("reddit")
class RedditSource:
    """Pulls per-brand subreddit mention volume + sentiment over the period."""

    name = "reddit"

    async def fetch(self, query: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return ``{slug: {"reddit_mentions_30d": int, "reddit_sentiment": float}}``.

        `query` carries the watchlist entries (slug + brand name + keywords) and the
        period window. Fail soft: return ``{}`` on any error so the report still renders.
        """
        # ADD: call the Reddit API (e.g. PRAW or pushshift-style), aggregate mentions
        # ADD: per watchlist slug for the period window, and score sentiment.
        raise NotImplementedError("finish RedditSource.fetch for your use case")

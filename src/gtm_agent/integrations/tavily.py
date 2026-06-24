"""Tavily web-research client (the research loop's search backbone).

A generic search interface: callers (the research supervisor/researcher) build the queries
from config; this module runs them and normalizes the response. Free tier is ~1000
credits/month (one basic search = one credit). Fail-soft: returns empty results without a
key, and skips a failed query rather than aborting the batch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ..log import get_logger

logger = get_logger(__name__)

_MAX_QUERY_CHARS = 395  # Tavily rejects queries over 400 chars


@dataclass(slots=True)
class SearchResult:
    """Normalized result of one search query."""

    query: str
    findings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    dated_sources: list[dict[str, Any]] = field(default_factory=list)
    relevance: str = "low"


def _extract(response: Any) -> list[Any]:
    if hasattr(response, "results"):
        return response.results
    if isinstance(response, dict):
        return response.get("results", [])
    return []


async def _search_one(
    client: Any,
    query: str,
    *,
    include_domains: list[str] | None,
    max_results: int,
    depth: str,
    start_date: str | None,
    end_date: str | None,
) -> SearchResult:
    if len(query) > _MAX_QUERY_CHARS:
        query = query[:_MAX_QUERY_CHARS].rsplit(" ", 1)[0] + "..."
    kwargs: dict[str, Any] = {"query": query, "search_depth": depth, "max_results": max_results}
    if include_domains:
        kwargs["include_domains"] = include_domains
    if start_date:
        kwargs["start_date"] = start_date
    if end_date:
        kwargs["end_date"] = end_date

    response = await client.search(**kwargs)
    findings: list[str] = []
    sources: list[str] = []
    dated: list[dict[str, Any]] = []
    for r in _extract(response):
        if hasattr(r, "title"):
            title, snippet, url = r.title or "", (r.content or "")[:300], r.url or ""
            pub = getattr(r, "published_date", None) or ""
        else:
            title = r.get("title") or ""
            snippet = (r.get("content") or "")[:300]
            url = r.get("url") or ""
            pub = r.get("published_date") or ""
        if title or snippet:
            findings.append(f"{title}: {snippet}" if title else snippet)
        if url:
            domain = url.split("//")[-1].split("/")[0].replace("www.", "")
            sources.append(domain)
            dated.append({"url": url, "title": title, "domain": domain, "published_date": pub})
    return SearchResult(
        query=query,
        findings=findings,
        sources=sources,
        dated_sources=dated,
        relevance="high" if findings else "low",
    )


async def search(
    queries: list[str],
    *,
    include_domains: list[str] | None = None,
    max_results: int = 3,
    depth: str = "basic",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[SearchResult]:
    """Run a batch of search queries. Returns one SearchResult per query that succeeded."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        logger.warning("tavily_skipped", reason="TAVILY_API_KEY not set")
        return []

    from tavily import AsyncTavilyClient  # type: ignore[import-untyped]

    client = AsyncTavilyClient(api_key=api_key)
    results: list[SearchResult] = []
    for q in queries:
        try:
            results.append(
                await _search_one(
                    client,
                    q,
                    include_domains=include_domains,
                    max_results=max_results,
                    depth=depth,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("tavily_query_failed", query=q[:100], error=str(exc)[:150])
    logger.info("tavily_research_complete", queries_total=len(queries), queries_ok=len(results))
    return results

"""Research tools for the researcher agent: web search and page fetch.

Each tool is ``@tool``-decorated for LLM tool-calling. The researcher discovers them via
``get_research_tools()`` and invokes them through structured tool calls. Results carry
source attribution so compressed findings keep their citation chain.

To add a tool (reviews, news API, an internal feed), write another ``@tool`` function and
add it to ``get_research_tools()``; see docs/EXTENDING.md.

Safety: tool outputs pass through a configurable blocklist before being returned. The
blocklist is empty by default and wired from the tenant config at pipeline start.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from typing import Any

import httpx
from langchain_core.tools import tool

from ...integrations import tavily
from ...log import get_logger

logger = get_logger(__name__)

_SAFETY_BLOCKLIST: set[str] = set()
_OFFLINE = False


def set_safety_blocklist(words: Iterable[str]) -> None:
    """Set the research-content blocklist (called at pipeline start from config)."""
    global _SAFETY_BLOCKLIST
    _SAFETY_BLOCKLIST = {w.lower() for w in words if w}


def set_offline(offline: bool) -> None:
    """Block live HTTP in tools (the hermetic demo sets this so web_fetch never dials out)."""
    global _OFFLINE
    _OFFLINE = offline


def _sanitize_text(text: str, context: str) -> str:
    """Redact text that hits the blocklist; return it unchanged otherwise."""
    if not _SAFETY_BLOCKLIST:
        return text
    low = text.lower()
    hits = [w for w in _SAFETY_BLOCKLIST if w in low]
    if hits:
        logger.warning("research_tool_sanitized", context=context, matched=hits[:3])
        return "[REDACTED: blocked content detected by the safety gate]"
    return text


@tool
async def tavily_search(
    query: str,
    preferred_domains: list[str] | None = None,
    max_results: int = 5,
) -> dict[str, Any]:
    """Web search via Tavily.

    Args:
        query: A natural-language search query.
        preferred_domains: Restrict to these domains (high-signal sources), or None.
        max_results: Maximum results to return (1-10).

    Returns:
        ``{findings: [str], sources: [domain], query: str}``; each finding is safety-scanned.
    """
    try:
        results = await tavily.search(
            [query], include_domains=preferred_domains, max_results=max_results
        )
        if not results:
            return {"findings": [], "sources": [], "query": query, "error": "no_results"}
        r = results[0]
        findings = [_sanitize_text(f, f"tavily:{query[:40]}") for f in r.findings][:max_results]
        return {"findings": findings, "sources": r.sources[:max_results], "query": query}
    except Exception as exc:  # noqa: BLE001
        logger.warning("tavily_tool_failed", query=query[:50], error=str(exc)[:150])
        return {"findings": [], "sources": [], "query": query, "error": str(exc)[:200]}


@tool
async def web_fetch(url: str, max_chars: int = 3000) -> dict[str, Any]:
    """Fetch a URL and extract its text (no JavaScript). Use to follow up a search result.

    Args:
        url: An absolute URL (https recommended).
        max_chars: Truncate extracted text to this many characters.

    Returns:
        ``{url, status, content, error?}``; content is safety-scanned.
    """
    if _OFFLINE:
        return {"url": url, "status": 0, "content": "", "error": "offline"}
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "go-to-market-agent/0.1"},
        ) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            return {"url": url, "status": resp.status_code, "content": "", "error": "http_error"}
        raw = resp.text
        if "<html" in raw.lower():
            raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
            raw = re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=re.DOTALL | re.IGNORECASE)
            raw = re.sub(r"<[^>]+>", " ", raw)
            raw = re.sub(r"\s+", " ", raw).strip()
        return {
            "url": url,
            "status": resp.status_code,
            "content": _sanitize_text(raw[:max_chars], url),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_fetch_failed", url=url[:80], error=str(exc)[:150])
        return {"url": url, "status": 0, "content": "", "error": str(exc)[:200]}


def get_research_tools() -> list[Any]:
    """Tools the researcher agent binds to its LLM."""
    return [tavily_search, web_fetch]


def scrub_duplicate_tool_calls(messages: list[Any]) -> list[Any]:
    """Strip duplicate ``additional_kwargs.tool_calls`` from AIMessages.

    Some provider integrations populate both ``AIMessage.tool_calls`` and
    ``additional_kwargs["tool_calls"]``, which can double the announced tool-call count on
    the next request. Harmless for providers that do not; keeps the canonical
    ``.tool_calls`` as the single source of truth.
    """
    scrubbed: list[Any] = []
    for msg in messages:
        ak = getattr(msg, "additional_kwargs", None)
        if type(msg).__name__ == "AIMessage" and isinstance(ak, dict) and ak.get("tool_calls"):
            clean = {k: v for k, v in ak.items() if k != "tool_calls"}
            try:
                msg = msg.model_copy(update={"additional_kwargs": clean})
            except Exception:  # noqa: BLE001
                msg.additional_kwargs = clean  # type: ignore[attr-defined]
        scrubbed.append(msg)
    return scrubbed


async def execute_tools_parallel(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run multiple tool calls concurrently; per-call failures return ``{error: ...}``."""
    tools_by_name = {t.name: t for t in get_research_tools()}

    async def _invoke(call: dict[str, Any]) -> dict[str, Any]:
        name = call.get("name", "")
        args = call.get("args", {})
        tool_fn = tools_by_name.get(name)
        if tool_fn is None:
            return {"error": f"unknown tool: {name}", "name": name}
        # LLMs sometimes emit {"urls": [...]} for web_fetch; normalize to a single url.
        if name == "web_fetch" and "url" not in args and isinstance(args.get("urls"), list):
            urls = args["urls"]
            if urls:
                args = {**args, "url": urls[0]}
                args.pop("urls", None)
                logger.info("web_fetch_args_normalized", using=str(args["url"])[:80])
        try:
            result = await tool_fn.ainvoke(args)
            return {"name": name, "args": args, "result": result}
        except Exception as exc:  # noqa: BLE001
            logger.warning("tool_invoke_failed", tool=name, error=str(exc)[:200])
            return {"name": name, "args": args, "error": str(exc)[:200]}

    return await asyncio.gather(*[_invoke(call) for call in tool_calls])

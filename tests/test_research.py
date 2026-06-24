"""Research subgraph tests: graphs compile, tools behave, safety + scrub work."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from gtm_agent.engine.research import build_supervisor_graph
from gtm_agent.engine.research.researcher import build_researcher_graph
from gtm_agent.engine.research.tools import (
    _sanitize_text,
    execute_tools_parallel,
    get_research_tools,
    scrub_duplicate_tool_calls,
    set_offline,
    set_safety_blocklist,
)
from gtm_agent.llm.config import default_llm_config
from gtm_agent.llm.router import LLMRouter


def _router() -> LLMRouter:
    return LLMRouter(default_llm_config())


def test_graphs_compile() -> None:
    # Compiling builds the topology; no LLM call happens here.
    assert build_researcher_graph(_router()) is not None
    assert build_supervisor_graph(_router()) is not None


def test_research_tools_registry() -> None:
    names = {t.name for t in get_research_tools()}
    assert names == {"tavily_search", "web_fetch"}


def test_scrub_duplicate_tool_calls() -> None:
    msg = AIMessage(content="", additional_kwargs={"tool_calls": [{"id": "x"}]})
    out = scrub_duplicate_tool_calls([msg])
    assert "tool_calls" not in out[0].additional_kwargs


def test_safety_blocklist_redacts() -> None:
    set_safety_blocklist([])
    assert _sanitize_text("a clean sentence", "ctx") == "a clean sentence"
    set_safety_blocklist(["forbidden"])
    assert "REDACTED" in _sanitize_text("this is forbidden material", "ctx")
    set_safety_blocklist([])  # reset so other tests are unaffected


async def test_execute_tools_parallel_unknown_tool() -> None:
    res = await execute_tools_parallel([{"name": "nope", "args": {}}])
    assert res[0]["error"].startswith("unknown tool")


async def test_tavily_tool_is_failsoft_without_key() -> None:
    # No TAVILY_API_KEY in the test env -> the search returns empty, the tool stays soft.
    res = await execute_tools_parallel([{"name": "tavily_search", "args": {"query": "q"}}])
    assert res[0]["result"]["query"] == "q"
    assert res[0]["result"]["findings"] == []


async def test_web_fetch_offline_guard_blocks_network() -> None:
    set_offline(True)
    try:
        res = await execute_tools_parallel(
            [{"name": "web_fetch", "args": {"url": "https://example.invalid/x"}}]
        )
        assert res[0]["result"]["error"] == "offline"
    finally:
        set_offline(False)

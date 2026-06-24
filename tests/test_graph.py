"""Graph wiring tests: compile, brief, gate routing, render (offline, no LLM)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from gtm_agent.config import default_settings
from gtm_agent.engine.graph import (
    _gate_router,
    build_report_graph,
    pre_publish_gate,
    render_report,
)
from gtm_agent.engine.nodes.brief import write_brief
from gtm_agent.llm.config import default_llm_config
from gtm_agent.llm.router import LLMRouter
from gtm_agent.models import MarketReport
from gtm_agent.storage.store import Store


def test_graph_compiles() -> None:
    graph = build_report_graph(
        default_settings(), LLMRouter(default_llm_config()), Store(":memory:")
    )
    assert graph is not None


async def test_write_brief_keys_match_analyst_sections() -> None:
    out = await write_brief({"period": "2026-04"}, None, settings=default_settings())
    assert set(out["section_briefs"]) == {
        "global market",
        "regional",
        "competitive",
        "brand positioning",
        "consumer",
        "technology",
    }
    assert out["research_brief"]


async def test_pre_publish_gate_passes_clean(make_report: Callable[[str], MarketReport]) -> None:
    out = await pre_publish_gate(
        {"report": make_report("2026-04")}, None, settings=default_settings()
    )
    assert out["qa_status"] == "pending"


async def test_pre_publish_gate_fails_without_report() -> None:
    out = await pre_publish_gate({}, None, settings=default_settings())
    assert out["qa_status"] == "fail"


def test_gate_router() -> None:
    assert _gate_router({"qa_status": "fail"}) == "fail"
    assert _gate_router({"qa_status": "pending"}) == "pass"


async def test_render_writes_files(
    make_report: Callable[[str], MarketReport], tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    report = make_report("2026-04")
    out = await render_report({"report": report}, None, settings=default_settings())
    assert (tmp_path / "output" / f"{report.report_id}.md").exists()
    assert (tmp_path / "output" / f"{report.report_id}.json").exists()
    assert out["qa_status"] == "pass"


pytestmark = pytest.mark.filterwarnings("ignore")

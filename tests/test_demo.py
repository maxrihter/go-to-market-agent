"""Demo test: the full graph runs hermetically (no keys, no network) and renders a report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gtm_agent.engine.demo import run_demo
from gtm_agent.models import MarketReport


async def test_demo_runs_end_to_end_hermetically(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    report = await run_demo()
    assert isinstance(report, MarketReport)
    # Rich, not stubbed.
    assert report.competitive_landscape.global_players
    assert report.technology_trends.trends
    assert report.strategic_recommendations.monthly_tactical
    # Month-over-month diff was computed against the seeded prior period.
    assert report.appendix.mom_diff_structured is not None
    assert report.appendix.mom_diff_structured.is_first_period is False
    # The report was rendered to disk.
    assert (tmp_path / "output" / "report-2026-04.md").exists()

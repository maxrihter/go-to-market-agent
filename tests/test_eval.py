"""Eval harness tests: deterministic floor + LLM-judge path, offline-safe."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from gtm_agent.engine.eval.harness import EvalScores, run_eval
from gtm_agent.models import MarketReport


class _FakeRouter:
    def __init__(self, result: Any = None) -> None:
        self._result = result

    async def call_resilient(self, *a: Any, **kw: Any) -> Any:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _write_report(tmp_path: Path, make_report: Callable[[str], MarketReport]) -> Path:
    outdir = tmp_path / "output"
    outdir.mkdir()
    path = outdir / "report-2026-04.json"
    path.write_text(make_report("2026-04").model_dump_json(), encoding="utf-8")
    return path


async def test_eval_with_judge(tmp_path: Path, make_report: Callable[[str], MarketReport]) -> None:
    path = _write_report(tmp_path, make_report)
    scores = EvalScores(grounding=4, completeness=3, traceability=4, clarity=5, notes="Solid.")
    out = await run_eval(path, router=_FakeRouter(scores))
    assert "LLM-judge scores" in out
    assert "overall: 4.0" in out


async def test_eval_deterministic_only_when_judge_unavailable(
    tmp_path: Path, make_report: Callable[[str], MarketReport]
) -> None:
    path = _write_report(tmp_path, make_report)
    out = await run_eval(path, router=_FakeRouter(None))
    assert "Deterministic checks" in out
    assert "LLM-judge skipped" in out


async def test_eval_no_report_raises(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        await run_eval(None, router=_FakeRouter(None))

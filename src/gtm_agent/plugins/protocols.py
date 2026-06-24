"""Extension-point protocols.

Each protocol is the contract a plugin satisfies. They are intentionally small and
use loose payload types (`Any` / mappings) so a plugin author depends on the contract,
not on the engine's internal models. Plugins receive the engine's context objects but
only need the few attributes documented here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Small result containers (kept dependency-free)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GateResult:
    """Outcome of a single QA gate."""

    passed: bool
    issues: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EmitResult:
    """Where an output adapter wrote the report (a path or a URL)."""

    location: str
    detail: str | None = None


# ---------------------------------------------------------------------------
# The six extension points
# ---------------------------------------------------------------------------


@runtime_checkable
class Source(Protocol):
    """A data connector that enriches the report with one signal family.

    Examples: Instagram profiles, Meta Ad Library, Google Trends, Reddit, reviews.
    """

    name: str

    async def fetch(self, query: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return a slug-keyed mapping of enrichment data. Fail soft (return {})."""
        ...


@runtime_checkable
class Analyst(Protocol):
    """Writes one facts-only report section from the research notes."""

    name: str
    section_key: str

    async def analyze(self, ctx: Any) -> Any:
        """Return a populated section model (or None to skip the section)."""
        ...


@runtime_checkable
class Synthesizer(Protocol):
    """Interprets the analyst sections into a cross-cutting output."""

    name: str

    async def synthesize(self, ctx: Any) -> Any:
        """Return a synthesized section (scoreboard, exec summary, recommendations…)."""
        ...


@runtime_checkable
class Gate(Protocol):
    """A pre-publish quality gate. May be deterministic or LLM-backed."""

    name: str

    def check(self, report: Any) -> GateResult:
        """Inspect the assembled report and return pass/fail with issues."""
        ...


@runtime_checkable
class OutputAdapter(Protocol):
    """Emits the report in one format (markdown, html, notion, slack, pdf…)."""

    name: str

    async def emit(self, render_model: Any, *, dest: str | None = None) -> EmitResult:
        """Render + write the report. Return where it landed."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """Builds a chat model for the router from a provider config."""

    name: str

    def build(self, config: Mapping[str, Any]) -> Any:
        """Return a LangChain-compatible chat model instance."""
        ...


KINDS: Sequence[str] = (
    "source",
    "analyst",
    "synthesizer",
    "gate",
    "output",
    "provider",
)

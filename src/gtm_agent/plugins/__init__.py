"""Plugin system: protocols + a registry for extending the engine.

Six extension points let you add capability without forking the core:
Source, Analyst, Synthesizer, Gate, OutputAdapter, and LLMProvider. Register a
bundled example with a decorator, or ship a third-party package that advertises
entry points under the `gtm_agent.*` groups (see docs/EXTENDING.md).
"""

from __future__ import annotations

from .registry import (
    all_of,
    analyst,
    format_registry,
    gate,
    get,
    load_entrypoint_plugins,
    output,
    provider,
    register,
    source,
    synthesizer,
)

__all__ = [
    "all_of",
    "analyst",
    "format_registry",
    "gate",
    "get",
    "load_entrypoint_plugins",
    "output",
    "provider",
    "register",
    "source",
    "synthesizer",
]

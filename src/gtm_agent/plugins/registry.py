"""Plugin registry + discovery.

Two ways to register an extension:

1. Decorator (bundled examples / in-tree plugins):

       from gtm_agent.plugins import source

       @source("reddit")
       class RedditSource:
           name = "reddit"
           async def fetch(self, query): ...

2. Entry points (third-party pip packages). A package advertises, in its
   pyproject, an entry point under the matching `gtm_agent.<kind>s` group:

       [project.entry-points."gtm_agent.sources"]
       reddit = "my_pkg.reddit:RedditSource"

   `load_entrypoint_plugins()` imports and registers them automatically.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from importlib import metadata
from typing import Any, TypeVar

from ..log import get_logger
from .protocols import KINDS

logger = get_logger(__name__)

T = TypeVar("T")

# kind -> {name -> object/class}
_REGISTRY: dict[str, dict[str, Any]] = {kind: {} for kind in KINDS}

# kind -> entry-point group name
_GROUP = {kind: f"gtm_agent.{kind}s" for kind in KINDS}

# Bundled example plugins that self-register on import.
_BUILTIN_MODULES = (
    "gtm_agent.extensions.sources.reddit",
    "gtm_agent.extensions.analysts.pricing_intel",
    "gtm_agent.extensions.outputs.slack",
)

_loaded = False


def register(kind: str, name: str | None = None) -> Callable[[T], T]:
    """Decorator: register a plugin object/class under `kind`.

    `name` defaults to the object's `name` attribute.
    """
    if kind not in _REGISTRY:
        msg = f"unknown plugin kind {kind!r}; expected one of {tuple(KINDS)}"
        raise ValueError(msg)

    def wrap(obj: T) -> T:
        key = name or getattr(obj, "name", None)
        if not key:
            msg = f"{obj!r} needs an explicit name or a `name` attribute"
            raise ValueError(msg)
        if key in _REGISTRY[kind]:
            logger.warning("plugin_override", kind=kind, name=key)
        _REGISTRY[kind][key] = obj
        return obj

    return wrap


# Convenience decorators, one per kind.
def source(name: str | None = None) -> Callable[[T], T]:
    return register("source", name)


def analyst(name: str | None = None) -> Callable[[T], T]:
    return register("analyst", name)


def synthesizer(name: str | None = None) -> Callable[[T], T]:
    return register("synthesizer", name)


def gate(name: str | None = None) -> Callable[[T], T]:
    return register("gate", name)


def output(name: str | None = None) -> Callable[[T], T]:
    return register("output", name)


def provider(name: str | None = None) -> Callable[[T], T]:
    return register("provider", name)


def get(kind: str, name: str) -> Any:
    """Return one registered plugin, or raise KeyError."""
    return _REGISTRY[kind][name]


def all_of(kind: str) -> dict[str, Any]:
    """Return a copy of every plugin registered under `kind`."""
    return dict(_REGISTRY[kind])


def _load_builtins() -> None:
    for mod in _BUILTIN_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001 (a broken example must not break the registry)
            logger.warning("builtin_plugin_load_failed", module=mod, error=str(exc)[:200])


def load_entrypoint_plugins() -> None:
    """Load bundled examples + any third-party plugins advertised via entry points.

    Idempotent: safe to call more than once. A plugin that fails to import is
    logged and skipped, never fatal.
    """
    global _loaded
    if _loaded:
        return
    _load_builtins()
    for kind, group in _GROUP.items():
        try:
            entries = metadata.entry_points(group=group)
        except Exception as exc:  # noqa: BLE001
            logger.warning("entrypoint_scan_failed", group=group, error=str(exc)[:200])
            continue
        for ep in entries:
            try:
                obj = ep.load()
                register(kind, ep.name)(obj)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "entrypoint_plugin_load_failed", group=group, name=ep.name, error=str(exc)[:200]
                )
    _loaded = True


def format_registry() -> str:
    """Human-readable summary of every registered plugin (for `gtm plugins list`)."""
    if not _loaded:
        load_entrypoint_plugins()
    lines: list[str] = []
    for kind in KINDS:
        names = sorted(_REGISTRY[kind])
        lines.append(f"{kind}s ({len(names)}):")
        if names:
            lines.extend(f"  - {n}" for n in names)
        else:
            lines.append("  (none registered)")
    return "\n".join(lines)

"""Smoke tests: the package imports, the CLI builds, and the plugin registry works."""

from __future__ import annotations

import gtm_agent
from gtm_agent.cli import app
from gtm_agent.plugins.registry import all_of, format_registry, load_entrypoint_plugins


def test_version() -> None:
    assert gtm_agent.__version__


def test_cli_app_builds() -> None:
    assert app is not None


def test_bundled_plugins_register() -> None:
    load_entrypoint_plugins()
    assert "reddit" in all_of("source")
    assert "pricing_intel" in all_of("analyst")
    assert "slack" in all_of("output")


def test_format_registry_lists_kinds() -> None:
    text = format_registry()
    for kind in ("sources", "analysts", "synthesizers", "gates", "outputs", "providers"):
        assert kind in text

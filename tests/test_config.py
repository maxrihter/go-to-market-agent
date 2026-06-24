"""Config tests: the example tenant validates, the YAML loader round-trips, errors are clean."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from gtm_agent.config import Settings, default_settings, load_settings
from gtm_agent.templates import example_tenant_yaml


def test_default_settings_is_barkwell() -> None:
    s = default_settings()
    assert s.brand.name == "Barkwell"
    assert s.brand.region == "US"
    assert len(s.watchlist) >= 3
    assert s.niche


def test_example_tenant_validates() -> None:
    s = Settings.model_validate(yaml.safe_load(example_tenant_yaml()))
    assert {w.slug for w in s.watchlist} >= {"thefarmersdog", "ollie"}


def test_load_settings_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "tenant.yaml"
    p.write_text(example_tenant_yaml(), encoding="utf-8")
    s = load_settings(p)
    assert s.brand.name == "Barkwell"
    assert s.forbidden_keywords  # carried through


def test_load_settings_invalid_raises_clean(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("brand: {}\n", encoding="utf-8")  # brand.name missing
    with pytest.raises(RuntimeError):
        load_settings(p)

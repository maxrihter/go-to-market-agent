"""Tenant configuration.

`Settings` is the single keystone object the whole engine reads from: brand facts, the
competitor watchlist, niche, region, safety lists, and LLM routing. It defines the model
the engine reads, plus a runnable default so the engine (and the demo) can run end to end.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from .llm.config import LLMConfig, default_llm_config


class BrandConfig(BaseModel):
    """The brand the report is written for."""

    name: str
    region: str | None = None
    report_language: str = "en"
    description: str = ""


class WatchEntry(BaseModel):
    """One competitor on the enrichment watchlist."""

    slug: str
    name: str
    ig_handle: str | None = None
    website_domain: str | None = None
    ios_app_id: str | None = None
    youtube_handle: str | None = None


class Settings(BaseModel):
    """Root tenant configuration."""

    brand: BrandConfig
    niche: str = ""
    watchlist: list[WatchEntry] = Field(default_factory=list)
    forbidden_keywords: list[str] = Field(default_factory=list)
    safety_blocklist: list[str] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=default_llm_config)
    extra: dict = Field(default_factory=dict)


def load_settings(path: Path) -> Settings:
    """Load + validate a tenant.yaml into `Settings`.

    Raises FileNotFoundError if the file is missing and RuntimeError (with a clean message)
    if the YAML does not satisfy the schema.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        msg = f"Invalid tenant config {path}: {exc}"
        raise RuntimeError(msg) from exc


def default_settings() -> Settings:
    """The bundled example tenant (Barkwell) as `Settings` (single source with the YAML)."""
    from .templates import example_tenant_yaml

    return Settings.model_validate(yaml.safe_load(example_tenant_yaml()))

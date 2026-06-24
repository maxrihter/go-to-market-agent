"""Output adapters: a neutral RenderModel IR plus per-format emitters."""

from __future__ import annotations

from .markdown import render_markdown
from .render_model import RenderModel, to_render_model

__all__ = ["RenderModel", "render_markdown", "to_render_model"]

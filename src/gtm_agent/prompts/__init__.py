"""Prompt loading.

Prompts are plain-text files co-located in this package directory (so they ship in the
wheel). They are concrete and human-readable, in English, with ``# ADD: your ...`` bullets
marking what an integrator customizes for their own brand / region / niche.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@cache
def load_prompt(name: str) -> str:
    """Return the text of the co-located ``{name}.txt`` prompt."""
    path = _DIR / f"{name}.txt"
    if not path.is_file():
        msg = f"prompt not found: {path}"
        raise FileNotFoundError(msg)
    return path.read_text(encoding="utf-8")

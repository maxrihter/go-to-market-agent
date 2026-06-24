"""Optional FastAPI server (the `[server]` extra).

A thin HTTP trigger over the same pipeline the CLI runs. Disabled unless FastAPI is
installed: `pip install "go-to-market-agent[server]"`. The trigger itself is an
extension seam left to implement.
"""

from __future__ import annotations

from typing import Any


def create_app() -> Any:
    """Build the FastAPI app. Imported lazily so the core install needs no FastAPI."""
    raise NotImplementedError("the [server] HTTP trigger is an extension seam; implement it here")

"""LangGraph checkpointer factory.

The report graph is long and calls paid APIs, so runs should be resumable: a crash
should not force re-running every node (and re-spending). For a real run we use a SQLite
saver keyed to a local file; the demo and tests use an in-memory saver.

Postgres resumability is available behind the [postgres] extra by swapping in
``AsyncPostgresSaver`` here.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def get_checkpointer(db_path: str | None = None) -> Any:
    """Return a checkpointer.

    `db_path` None or ``":memory:"`` gives an in-memory saver (demo / tests). A real
    path gives a resumable SQLite saver backed by that file.
    """
    if not db_path or db_path == ":memory:":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(db_path, check_same_thread=False)
    return SqliteSaver(conn)

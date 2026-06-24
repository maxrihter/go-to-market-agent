"""Human-in-the-loop overrides: apply operator corrections over weak report fields.

Operators record corrections (see templates/corrections.example.yaml) keyed by a dotted
attribute path into the report (e.g. ``regional_pulse.conclusion``). After assembly, this
node applies each active override where the current value is empty or weak, then marks it
applied so it is not re-applied indefinitely. Deeper list/slug-addressed paths are an
EXTENDING seam; this node handles attribute paths.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from ...log import get_logger
from ...storage.store import should_apply_override

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ...storage.store import Store

logger = get_logger(__name__)


def _resolve(report: Any, path: str) -> tuple[Any, str] | None:
    """Return (parent_object, leaf_attr) for a dotted attribute path, or None."""
    parts = path.split(".")
    obj = report
    for part in parts[:-1]:
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    leaf = parts[-1]
    if not hasattr(obj, leaf):
        return None
    return obj, leaf


async def apply_overrides_node(
    state: Any, config: RunnableConfig, *, store: Store
) -> dict[str, Any]:
    """Apply active overrides onto the assembled report; mark each applied."""
    report = state.get("report")
    if report is None:
        return {}
    try:
        overrides = store.fetch_active_overrides()
    except Exception as exc:  # noqa: BLE001
        logger.warning("overrides_fetch_failed", error=str(exc)[:200])
        return {}
    if not overrides:
        return {}

    applied = 0
    for ov in overrides:
        path = ov.get("section_key", "")
        value = ov.get("override_value", "")
        resolved = _resolve(report, path)
        if resolved is None:
            logger.info("override_path_unresolved", path=path)
            continue
        parent, leaf = resolved
        current = getattr(parent, leaf, None)
        if not should_apply_override(value, current):
            continue
        # Apply, then re-validate; revert if the value violates the schema (setattr skips
        # Pydantic validation, so an override could otherwise corrupt the payload).
        try:
            setattr(parent, leaf, value)
            type(parent).model_validate(parent.model_dump(warnings=False))
        except Exception as exc:  # noqa: BLE001
            with contextlib.suppress(Exception):
                setattr(parent, leaf, current)
            logger.warning("override_rejected_invalid", path=path, error=str(exc)[:150])
            continue
        store.mark_override_applied(ov["id"], report.report_id)
        applied += 1

    if applied:
        logger.info("overrides_applied", count=applied)
    return {"report": report}

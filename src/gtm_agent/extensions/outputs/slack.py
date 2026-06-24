"""Example OutputAdapter plugin: post a report teaser to Slack.

Copy this file to add a new output format. Registered under the `output` kind as "slack".
Worked example: the `emit` body is left for you.
"""

from __future__ import annotations

from typing import Any

from ...plugins import output
from ...plugins.protocols import EmitResult


@output("slack")
class SlackOutput:
    """Posts the report's executive summary + top recommendations to a Slack webhook."""

    name = "slack"

    async def emit(self, render_model: Any, *, dest: str | None = None) -> EmitResult:
        """Send a teaser to `dest` (or SLACK_WEBHOOK_URL). Return the channel/URL.

        `render_model` is the neutral RenderModel IR, so you choose what to summarize.
        """
        # ADD: build Slack blocks from render_model.kpis + the exec-summary section,
        # ADD: POST them to the webhook with httpx.
        raise NotImplementedError("finish SlackOutput.emit for your use case")

"""Band task-state events.

Band exposes a typed `send_event(message_type="task")` channel that renders as
task progress in the UI and — unlike chat — needs no @mention, so it never trips
the 422 resync race. We emit one per pipeline stage so the multi-agent
coordination is visible as first-class Band state, not just chat messages.

Keep `stage` strings short and free of the Architect's done-markers (e.g.
"## Test Results", "## Auto-Fix") so they can't false-trigger the wait loop.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


async def emit_task(tools: Any, agent: str, stage: str, **metadata: Any) -> None:
    """Emit a Band 'task' progress event. Best-effort: never raises."""
    try:
        await tools.send_event(
            content=f"{agent}: {stage}",
            message_type="task",
            metadata={"agent": agent, "stage": stage, **metadata},
        )
    except Exception:  # noqa: BLE001 - telemetry must never break the pipeline
        log.debug("emit_task failed for %s/%s", agent, stage, exc_info=True)

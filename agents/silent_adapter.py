"""SilentAdapter — a no-op Band adapter for the Architect agent.

The Architect's active role is played entirely by architect_handler.py via
REST calls. The persistent Agent process just needs to stay connected without
reacting to any room messages (doing so causes 422 resync loops).
"""

from __future__ import annotations

from typing import Any

from band.core.protocols import AgentToolsProtocol
from band.core.simple_adapter import SimpleAdapter
from band.core.types import PlatformMessage


class SilentAdapter(SimpleAdapter[Any]):
    SUPPORTED_EMIT = frozenset()
    SUPPORTED_CAPABILITIES = frozenset()

    def __init__(self) -> None:
        super().__init__(history_converter=None)

    async def on_message(
        self,
        msg: PlatformMessage,
        tools: AgentToolsProtocol,
        history: Any,
        participants_msg: str | None,
        contacts_msg: str | None,
        *,
        is_session_bootstrap: bool,
        room_id: str,
    ) -> None:
        pass

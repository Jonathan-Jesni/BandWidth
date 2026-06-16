"""EchoAdapter — a minimal Band adapter that echoes peers' messages.

Step 1 of the BandWidth build: proves the Band plumbing (rooms, messaging,
mentions, typed events) before any LLM or GitHub logic is added. Each agent
running this adapter will:

  * ignore its own messages and the bootstrap replay (no echo storms),
  * reply to a peer's message by @mentioning that peer,
  * on seeing the word "verdict", also emit a typed `task` event carrying a
    dummy {"flag": "Pass"} — the same channel the real Reviewer will later use
    to broadcast Pass/Blocker.
"""

from __future__ import annotations

import logging
from typing import Any

from band.core.protocols import AgentToolsProtocol
from band.core.simple_adapter import SimpleAdapter
from band.core.types import PlatformMessage

logger = logging.getLogger(__name__)


class EchoAdapter(SimpleAdapter[Any]):
    SUPPORTED_EMIT = frozenset()
    SUPPORTED_CAPABILITIES = frozenset()

    def __init__(self) -> None:
        super().__init__(history_converter=None)
        # Only acknowledge the first (Architect's seed) message per room.
        # This prevents re-echoing the Reviewer's review and stops echo storms.
        self._greeted_rooms: set[str] = set()

    def _self_id(self) -> str | None:
        # Agent.start() sets this attribute on the adapter before processing.
        return getattr(self, "_band_agent_id", None)

    def _peer_mentions(self, tools: AgentToolsProtocol) -> list[str]:
        """Handles of every participant except this agent."""
        self_id = self._self_id()
        mentions: list[str] = []
        for p in tools.participants:
            if self_id and p.get("id") == self_id:
                continue
            handle = p.get("handle") or p.get("name")
            if handle:
                mentions.append(handle)
        return mentions

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
        logger.info(
            "[%s] on_message: type=%r sender=%r content=%r",
            self.agent_name, msg.message_type, msg.sender_id, msg.content[:60],
        )
        # Don't react to our own messages — that's an infinite echo loop.
        if self._self_id() and msg.sender_id == self._self_id():
            return
        # Skip Band event subtypes (tool_call, tool_result, thought, error, task).
        _EVENT_TYPES = {"tool_call", "tool_result", "thought", "error", "task"}
        if msg.message_type in _EVENT_TYPES:
            return
        # Only acknowledge the first message per room (the Architect's seed).
        # Prevents re-echoing the Reviewer's review and avoids echo storms.
        if room_id in self._greeted_rooms:
            return
        self._greeted_rooms.add(room_id)

        mentions = self._peer_mentions(tools)
        if not mentions:
            logger.warning("[%s] no peers to mention; skipping reply", self.agent_name)
            return

        await tools.send_message(
            f"[{self.agent_name}] heard: {msg.content}",
            mentions=mentions,
        )

        # Prove the typed-event ("shared state") channel works.
        if "verdict" in (msg.content or "").lower():
            await tools.send_event(
                content=f"{self.agent_name} verdict: Pass",
                message_type="task",
                metadata={"flag": "Pass", "by": self.agent_name},
            )

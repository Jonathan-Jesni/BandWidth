"""ReviewerAdapter — LLM-powered code reviewer.

Triggers once per room when it sees the Architect's PR context message
(identified by "## Diff summary"). Calls DeepSeek V4 Pro via Featherless to
produce a structured review, posts it to the room, and emits a `task`
event with the verdict flag ("Pass" or "Blocker") for the Tester to act on.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import openai

from band.core.protocols import AgentToolsProtocol
from band.core.simple_adapter import SimpleAdapter
from band.core.types import PlatformMessage

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a senior code reviewer. Given a PR title, description, and diff, output:
1. A bullet list of specific issues found (bugs, security problems, style violations).
   Mark each [BLOCKER] or [MINOR].
   If there are no issues, write "- No issues found."
2. A final verdict line — exactly one of:
   Verdict: Pass
   Verdict: Blocker

Be concise. Max 600 words. Do not repeat the diff back."""


class ReviewerAdapter(SimpleAdapter[Any]):
    SUPPORTED_EMIT = frozenset()
    SUPPORTED_CAPABILITIES = frozenset()

    def __init__(self) -> None:
        super().__init__(history_converter=None)
        self._reviewed_rooms: set[str] = set()
        self._client = openai.OpenAI(
            api_key=os.environ["FEATHERLESS_API_KEY"],
            base_url="https://api.featherless.ai/v1",
        )
        self._model = "deepseek-ai/DeepSeek-V4-Pro"

    def _self_id(self) -> str | None:
        return getattr(self, "_band_agent_id", None)

    def _peer_mentions(self, tools: AgentToolsProtocol) -> list[str]:
        self_id = self._self_id()
        return [
            p.get("handle") or p.get("name")
            for p in tools.participants
            if p.get("id") != self_id and (p.get("handle") or p.get("name"))
        ]

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
        # Only fire once per room.
        if room_id in self._reviewed_rooms:
            return
        # Skip own messages and non-chat events.
        if self._self_id() and msg.sender_id == self._self_id():
            return
        _EVENT_TYPES = {"tool_call", "tool_result", "thought", "error", "task"}
        if msg.message_type in _EVENT_TYPES:
            return
        # Only act on the Architect's PR context message.
        if "## Diff summary" not in (msg.content or ""):
            return

        self._reviewed_rooms.add(room_id)
        log.info("[Reviewer] PR context received in room %s — calling LLM", room_id)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": msg.content},
                ],
            )
            review_text = response.choices[0].message.content.strip()
        except Exception:
            log.exception("[Reviewer] LLM call failed")
            review_text = "Review failed — LLM error. Verdict: Pass"

        flag = "Blocker" if "Verdict: Blocker" in review_text else "Pass"
        log.info("[Reviewer] Verdict: %s", flag)

        mentions = self._peer_mentions(tools)
        if not mentions:
            log.warning("[Reviewer] no peers to mention; posting review anyway via event")
        else:
            await tools.send_message(
                f"## Code Review\n\n{review_text}",
                mentions=mentions,
            )

        # Emit the typed verdict event — this is what the Tester watches.
        await tools.send_event(
            content=f"Review verdict: {flag}",
            message_type="task",
            metadata={"flag": flag, "by": self.agent_name},
        )

"""ReviewerAdapter — LLM-powered code reviewer.

Triggers once per room when it sees the Architect's PR context message
(identified by "## Diff summary"). Calls DeepSeek V4 Pro via Featherless to
produce a structured review, posts it (mentioning only the silent Architect),
then sends a second direct message to only the Tester with the verdict.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import openai

import config
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

    def _architect_mention(self, tools: AgentToolsProtocol) -> list[str]:
        """Mention only the Architect for the review post — it's a SilentAdapter,
        so it never races on the message."""
        try:
            architect_id = config.architect().agent_id
        except Exception:
            architect_id = None
        mentions = [
            p.get("handle") or p.get("name")
            for p in tools.participants
            if p.get("id") == architect_id and (p.get("handle") or p.get("name"))
        ]
        # Fallback so send_message always has ≥1 mention (e.g. solo-test room).
        return mentions or self._peer_mentions(tools)

    def _tester_mention(self, tools: AgentToolsProtocol) -> list[str]:
        """Mention only the Tester for the verdict notification — separate message
        so only one active agent receives each message (avoids 422 race)."""
        self_id = self._self_id()
        try:
            architect_id = config.architect().agent_id
        except Exception:
            architect_id = None
        return [
            p.get("handle") or p.get("name")
            for p in tools.participants
            if p.get("id") not in (self_id, architect_id)
            and (p.get("handle") or p.get("name"))
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

        arch_mentions = self._architect_mention(tools)
        if not arch_mentions:
            log.warning("[Reviewer] no Architect to mention — skipping review post")
        else:
            await tools.send_message(
                f"## Code Review\n\n{review_text}",
                mentions=arch_mentions,
            )

        # Deliver verdict directly to the Tester via a dedicated chat message.
        # send_event is NOT delivered as an actionable message by the platform,
        # so we use a second send_message with only the Tester as recipient.
        tester_mentions = self._tester_mention(tools)
        if tester_mentions:
            await tools.send_message(
                f"## Verdict\n{flag}",
                mentions=tester_mentions,
            )
            log.info("[Reviewer] Verdict notification sent to Tester")

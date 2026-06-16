"""TesterAdapter — QA and docs agent.

Watches for the Reviewer's verdict notification message (contains "## Verdict").
On "Pass", fetches the PR context from room history and calls DeepSeek-V4-Pro
via Featherless to generate unit test descriptions and documentation suggestions.
On "Blocker", posts an acknowledgment and waits for the next cycle.
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

_EVENT_TYPES = {"tool_call", "tool_result", "thought", "error", "task"}

_TESTER_SYSTEM_PROMPT = """\
You are a QA engineer and technical writer. Given a PR diff and description, output:
1. A list of unit test cases to write — for each, give the function/method name and
   a one-sentence description of what it should assert.
2. Any documentation that should be added or updated (docstrings, README sections, etc.).
Be concise. Max 500 words."""


class TesterAdapter(SimpleAdapter[Any]):
    SUPPORTED_EMIT = frozenset()
    SUPPORTED_CAPABILITIES = frozenset()

    def __init__(self) -> None:
        super().__init__(history_converter=None)
        self._tested_rooms: set[str] = set()
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

    def _reviewer_mention(self, tools: AgentToolsProtocol) -> list[str]:
        """Mention only the Reviewer (not self, not the Architect). Avoids the
        422 race that a multi-mention output message would re-create between the
        silent Architect and the Reviewer.
        """
        self_id = self._self_id()
        try:
            architect_id = config.architect().agent_id
        except Exception:
            architect_id = None
        mentions = [
            p.get("handle") or p.get("name")
            for p in tools.participants
            if p.get("id") not in (self_id, architect_id)
            and (p.get("handle") or p.get("name"))
        ]
        # Fallback so send_message always has ≥1 mention.
        return mentions or self._peer_mentions(tools)

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
        if room_id in self._tested_rooms:
            return
        # Skip internal SDK event types.
        if msg.message_type in _EVENT_TYPES:
            return
        # Only react to the Reviewer's verdict notification.
        content = msg.content or ""
        if "## Verdict" not in content:
            return

        if "Blocker" in content:
            flag = "Blocker"
        elif "Pass" in content:
            flag = "Pass"
        else:
            return

        self._tested_rooms.add(room_id)
        log.info("[Tester] Verdict '%s' received in room %s", flag, room_id)

        mentions = self._reviewer_mention(tools)
        if not mentions:
            log.warning("[Tester] no peers to mention — skipping reply")
            return

        if flag == "Blocker":
            await tools.send_message(
                "Blocker detected — skipping test generation. Waiting for fixes.",
                mentions=mentions,
            )
            return

        # Fetch room history to find the Architect's PR context message.
        pr_context: str | None = None
        try:
            ctx = await tools.fetch_room_context(room_id=room_id, page_size=20)
            pr_context = next(
                (
                    m.get("content", "")
                    for m in ctx.get("data", [])
                    if "## Diff summary" in (m.get("content") or "")
                ),
                None,
            )
        except Exception:
            log.warning("[Tester] could not fetch room context; using event content")

        user_content = pr_context or "(no PR context available)"

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": _TESTER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            )
            test_output = response.choices[0].message.content.strip()
        except Exception:
            log.exception("[Tester] LLM call failed")
            test_output = "Test generation failed — LLM error."

        await tools.send_message(
            f"## Tests & Docs\n\n{test_output}",
            mentions=mentions,
        )
        log.info("[Tester] Tests & docs posted to room %s", room_id)

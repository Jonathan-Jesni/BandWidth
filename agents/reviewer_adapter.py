"""ReviewerAdapter — LLM-powered code reviewer.

Primary flow: triggers once per room on the Architect's PR context message
("## Diff summary"), calls DeepSeek V4 Pro via Featherless for a structured JSON
review, posts it (mentioning only the silent Architect), then routes the verdict
to exactly one downstream agent:
  - Pass    → mention only the Tester.
  - Blocker → mention only the Engineer.
Mentioning a single active recipient avoids the 422 resync race.

Secondary flow (bi-directional sync): on a "## Question" message relayed from a
human's GitHub comment, it answers with "## Answer" (mentioning the Architect).
"""

from __future__ import annotations

import json
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

# Force the LLM to output strict JSON for the review.
_SYSTEM_PROMPT = """\
You are a senior code reviewer. Given a PR title, description, and diff, output ONLY valid JSON matching exactly this schema:
{
  "issues": "A bullet list of specific issues found (bugs, security problems, style violations). Mark each [BLOCKER] or [MINOR]. If no issues, write '- No issues found.'",
  "verdict": "Pass" or "Blocker"
}

Be concise. Max 600 words. Do not repeat the diff back."""

_ANSWER_SYSTEM_PROMPT = """\
You are the senior code reviewer who reviewed this pull request. A human has
asked a follow-up question about your review. Using the PR context and your
earlier review in the conversation, answer the question directly and concisely
(max 250 words). Plain prose — no JSON."""


class ReviewerAdapter(SimpleAdapter[Any]):
    SUPPORTED_EMIT = frozenset()
    SUPPORTED_CAPABILITIES = frozenset()

    def __init__(self) -> None:
        super().__init__(history_converter=None)
        self._reviewed_rooms: set[str] = set()
        self._answered: set[str] = set()
        self._client = openai.OpenAI(
            api_key=os.environ["FEATHERLESS_API_KEY"],
            base_url="https://api.featherless.ai/v1",
        )
        self._model = "deepseek-ai/DeepSeek-V4-Pro"

    # --- identity / mention helpers ------------------------------------- #
    def _self_id(self) -> str | None:
        return getattr(self, "_band_agent_id", None)

    def _peer_mentions(self, tools: AgentToolsProtocol) -> list[str]:
        self_id = self._self_id()
        return [
            p.get("handle") or p.get("name")
            for p in tools.participants
            if p.get("id") != self_id and (p.get("handle") or p.get("name"))
        ]

    def _mention_for(self, tools: AgentToolsProtocol, agent_id: str | None) -> list[str]:
        """Resolve a single participant's mention by agent_id."""
        if not agent_id:
            return []
        return [
            p.get("handle") or p.get("name")
            for p in tools.participants
            if p.get("id") == agent_id and (p.get("handle") or p.get("name"))
        ]

    def _architect_mention(self, tools: AgentToolsProtocol) -> list[str]:
        """Mention only the (silent) Architect — it never races on a message."""
        try:
            architect_id = config.architect().agent_id
        except Exception:
            architect_id = None
        return self._mention_for(tools, architect_id) or self._peer_mentions(tools)

    def _verdict_mention(self, tools: AgentToolsProtocol, flag: str) -> list[str]:
        """Route the verdict to exactly one downstream agent by id."""
        try:
            target_id = (
                config.engineer().agent_id if flag == "Blocker"
                else config.tester().agent_id
            )
        except Exception:
            target_id = None
        return self._mention_for(tools, target_id)

    # --- main entrypoint ------------------------------------------------ #
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
        if self._self_id() and msg.sender_id == self._self_id():
            return
        if msg.message_type in _EVENT_TYPES:
            return

        content = msg.content or ""

        # Bi-directional sync: answer a relayed human question.
        if "## Question" in content:
            await self._answer_question(msg, tools, room_id)
            return

        # Primary review trigger (once per room).
        if "## Diff summary" not in content or room_id in self._reviewed_rooms:
            return
        self._reviewed_rooms.add(room_id)
        await self._review(content, tools, room_id)

    # --- review --------------------------------------------------------- #
    async def _review(
        self, content: str, tools: AgentToolsProtocol, room_id: str
    ) -> None:
        log.info("[Reviewer] PR context received in room %s — calling LLM", room_id)
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=4096,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
            )
            parsed = json.loads(response.choices[0].message.content.strip())
            review_text = parsed.get("issues", "No issues found.")
            flag = parsed.get("verdict", "Pass")
        except Exception:
            log.exception("[Reviewer] LLM call or JSON parsing failed")
            review_text = "Review failed — LLM error or invalid JSON."
            flag = "Pass"

        if flag not in ("Pass", "Blocker"):
            flag = "Pass"
        log.info("[Reviewer] Verdict: %s", flag)

        arch_mentions = self._architect_mention(tools)
        if arch_mentions:
            await tools.send_message(
                f"## Code Review\n\n{review_text}", mentions=arch_mentions
            )
        else:
            log.warning("[Reviewer] no Architect to mention — skipping review post")

        # Deliver the verdict to exactly one downstream agent (one active
        # recipient → no 422 race). send_event is not actionable, so use a
        # second send_message.
        verdict_mentions = self._verdict_mention(tools, flag)
        if verdict_mentions:
            await tools.send_message(f"## Verdict\n{flag}", mentions=verdict_mentions)
            log.info("[Reviewer] Verdict '%s' routed downstream", flag)
        else:
            log.warning("[Reviewer] no downstream agent to mention for '%s'", flag)

    # --- question answering --------------------------------------------- #
    async def _answer_question(
        self, msg: PlatformMessage, tools: AgentToolsProtocol, room_id: str
    ) -> None:
        if msg.id in self._answered:
            return
        self._answered.add(msg.id)
        log.info("[Reviewer] answering human question in room %s", room_id)

        # Pull the PR context + prior review for grounding.
        context_blob = ""
        try:
            ctx = await tools.fetch_room_context(room_id=room_id, page_size=100)
            parts = [
                (m.get("content") or "")
                for m in reversed(ctx.get("data", []))
                if any(
                    marker in (m.get("content") or "")
                    for marker in ("## Diff summary", "## Code Review")
                )
            ]
            context_blob = "\n\n".join(parts)[:6000]
        except Exception:
            log.warning("[Reviewer] could not fetch context for question")

        question = (msg.content or "").replace("## Question", "").strip()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
                    {"role": "user", "content": f"{context_blob}\n\nQuestion:\n{question}"},
                ],
            )
            answer = response.choices[0].message.content.strip()
        except Exception:
            log.exception("[Reviewer] answer LLM call failed")
            answer = "Sorry — I could not generate an answer (LLM error)."

        mentions = self._architect_mention(tools)
        if mentions:
            await tools.send_message(f"## Answer\n\n{answer}", mentions=mentions)
            log.info("[Reviewer] answer posted to room %s", room_id)

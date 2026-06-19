"""DocumenterAdapter — final synthesis agent.

Sits silently in each Band review room and waits for the pipeline to finish:
  - ``## Test Results`` / ``## Tests & Docs``  → successful convergence
  - ``## Escalated for Human Review``           → agents hit their limit

On either trigger it reads the full room history (via the Architect's
credentials, for the same visibility reason the Tester/Engineer use), asks the
LLM for a polished PR summary or escalation handover document, and posts:

    ## Final PR Documentation
    <LLM-generated prose>

The Architect waits for that marker as its terminal signal, then pushes the
transcript (including this summary) to GitHub and updates the PR description.
"""

from __future__ import annotations

import logging
from typing import Any

import config
from agents import llm
from agents.architect_handler import fetch_room_context_as_architect
from agents.events import emit_task
from agents.markers import DOCUMENTER_DONE_MARKER
from band.core.protocols import AgentToolsProtocol
from band.core.simple_adapter import SimpleAdapter
from band.core.types import PlatformMessage

log = logging.getLogger(__name__)

_EVENT_TYPES = {"tool_call", "tool_result", "thought", "error", "task"}

_PASS_MARKERS = ("## Test Results", "## Tests & Docs")
_ESCALATION_MARKER = "## Escalated for Human Review"

# ---- LLM prompts -----------------------------------------------------------

_SUMMARY_SYSTEM = """\
You are a senior engineering lead writing the final summary for a pull request
that was reviewed and fixed autonomously by an AI multi-agent system (BandWidth).
Given the full transcript of the review room, write a concise, professional
PR description in markdown with these sections:

## Summary of Changes
One paragraph describing what code was changed and why.

## Bug Found
What specific bug or issue the Reviewer identified.

## Fix Applied
How the Engineer resolved it.

## Test Coverage
What the Tester verified (or recommended).

Be factual, terse, and professional. Max 300 words total."""

_ESCALATION_SYSTEM = """\
You are a senior engineering lead writing an escalation handover document for a
pull request that an AI multi-agent system (BandWidth) could not fully resolve.
Given the full transcript of the review room, write a concise, professional
escalation report in markdown with these sections:

## What Was Attempted
What the automated Engineer tried to fix, and how many times.

## Why It Was Escalated
The specific blocker(s) the Reviewer kept flagging and why they require a
human decision (e.g. a product/semantic call, ambiguous requirements).

## Recommended Next Steps
Concrete actions a human engineer should take to close this PR.

Be factual, terse, and professional. Max 300 words total."""

# Marker text that the Architect waits for (must NOT match any other message).
DONE_MARKER = DOCUMENTER_DONE_MARKER


class DocumenterAdapter(SimpleAdapter[Any]):
    SUPPORTED_EMIT = frozenset()
    SUPPORTED_CAPABILITIES = frozenset()

    def __init__(self) -> None:
        super().__init__(history_converter=None)
        self._documented_rooms: set[str] = set()
        self._client, self._model = llm.build(config.provider_for("documenter"))

    def _self_id(self) -> str | None:
        return getattr(self, "_band_agent_id", None)

    def _architect_mention(self, tools: AgentToolsProtocol) -> list[str]:
        """Report back to the silent Architect (single inactive recipient)."""
        try:
            architect_id = config.architect().agent_id
        except Exception:
            architect_id = None
        self_id = self._self_id()
        mentions = [
            p.get("handle") or p.get("name")
            for p in tools.participants
            if p.get("id") == architect_id and (p.get("handle") or p.get("name"))
        ]
        return mentions or [
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
        if room_id in self._documented_rooms:
            return
        if msg.message_type in _EVENT_TYPES:
            return

        content = msg.content or ""

        is_pass = any(marker in content for marker in _PASS_MARKERS)
        is_escalation = _ESCALATION_MARKER in content

        if not (is_pass or is_escalation):
            return

        self._documented_rooms.add(room_id)
        outcome = "escalated" if is_escalation else "passed"
        log.info("[Documenter] Pipeline %s in room %s — generating docs", outcome, room_id)
        await emit_task(tools, "Documenter", f"documenting:{outcome}")

        # Read the full room transcript through the Architect's credentials.
        transcript = ""
        try:
            ctx = await fetch_room_context_as_architect(room_id)
            messages = list(reversed(ctx.get("data", [])))  # oldest-first
            parts = []
            for m in messages:
                if m.get("message_type") in _EVENT_TYPES:
                    continue
                sender = m.get("sender_name") or m.get("sender_id", "Agent")
                body = (m.get("content") or "").strip()
                if body:
                    parts.append(f"**{sender}:**\n{body}")
            transcript = "\n\n---\n\n".join(parts)
        except Exception:
            log.warning("[Documenter] could not fetch room context; using empty transcript")

        system_prompt = _ESCALATION_SYSTEM if is_escalation else _SUMMARY_SYSTEM
        doc = llm.complete_text(
            self._client,
            self._model,
            system_prompt,
            transcript or "(no transcript available)",
            max_tokens=800,
        )

        if not doc or not doc.strip():
            doc = (
                "Escalation handover: the automated review pipeline reached its "
                "attempt limit. A human engineer should inspect the PR."
                if is_escalation
                else "The automated review pipeline completed successfully."
            )

        message = f"{DOCUMENTER_DONE_MARKER}\n\n{doc.strip()}"
        mentions = self._architect_mention(tools)
        if mentions:
            await tools.send_message(message, mentions=mentions)
        else:
            await tools.send_message(message)

        await emit_task(tools, "Documenter", "documented", outcome=outcome, model=self._model)
        log.info("[Documenter] Final documentation posted to room %s", room_id)

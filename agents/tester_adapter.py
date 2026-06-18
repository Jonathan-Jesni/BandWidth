"""TesterAdapter — QA and docs agent.

Watches for the Reviewer's "## Verdict" message. On "Pass":
  - If ENABLE_TEST_EXECUTION is set: asks the LLM for a self-contained pytest
    file, writes the PR's modified source files + that test into a temp dir,
    runs real pytest in a sandboxed subprocess, and posts "## Test Results"
    with the actual pass/fail output.
  - Otherwise (default): generates unit-test descriptions + doc suggestions and
    posts "## Tests & Docs".
"""

from __future__ import annotations

import logging
import os
from typing import Any

import openai

import config
from agents import llm, test_runner
from agents.architect_handler import fetch_room_context_as_architect
from agents.room_payload import parse_files
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

_EXEC_SYSTEM_PROMPT = """\
You are a QA engineer. You are given the full source of the files changed in a
pull request. Write a SINGLE self-contained pytest test module that imports those
modules by their module name (filename without .py, top-level) and tests their
public behavior. Output ONLY valid JSON matching this schema:
{
  "test_code": "the complete contents of a pytest file (Python source)",
  "explanation": "one or two sentences on what the tests cover"
}
Rules: import only the provided modules and the standard library; do not access
the network or filesystem; keep it runnable as-is."""


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

    def _architect_mention(self, tools: AgentToolsProtocol) -> list[str]:
        """Report results to the silent Architect (one inactive recipient → no race)."""
        try:
            architect_id = config.architect().agent_id
        except Exception:
            architect_id = None
        mentions = [
            p.get("handle") or p.get("name")
            for p in tools.participants
            if p.get("id") == architect_id and (p.get("handle") or p.get("name"))
        ]
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
        if room_id in self._tested_rooms:
            return
        if msg.message_type in _EVENT_TYPES:
            return
        content = msg.content or ""
        if "## Verdict" not in content:
            return
        # The Engineer handles Blocker; the Tester only acts on Pass.
        if "Pass" not in content:
            return

        self._tested_rooms.add(room_id)
        log.info("[Tester] Pass verdict received in room %s", room_id)

        mentions = self._architect_mention(tools)
        if not mentions:
            log.warning("[Tester] no peers to mention — skipping reply")
            return

        # Fetch the Architect's PR context message (carries diff + source payload).
        # Read as the Architect — the opening mentions only the Reviewer, so it is
        # invisible to the Tester's own credentials.
        pr_context = ""
        source_files: dict[str, str] = {}
        try:
            ctx = await fetch_room_context_as_architect(room_id)
            for m in ctx.get("data", []):
                c = m.get("content") or ""
                if "## Diff summary" in c:
                    pr_context = c
                    source_files = parse_files(c)
                    break
        except Exception:
            log.warning("[Tester] could not fetch room context")

        if config.enable_test_execution() and source_files:
            await self._run_real_tests(source_files, pr_context, tools, mentions, room_id)
        else:
            await self._describe_tests(pr_context, tools, mentions, room_id)

    # --- real execution path -------------------------------------------- #
    async def _run_real_tests(
        self,
        source_files: dict[str, str],
        pr_context: str,
        tools: AgentToolsProtocol,
        mentions: list[str],
        room_id: str,
    ) -> None:
        files_blob = "\n\n".join(
            f"# === {path} ===\n{content}" for path, content in source_files.items()
        )
        parsed = llm.complete_json(
            self._client, self._model, _EXEC_SYSTEM_PROMPT, files_blob, max_tokens=4096
        )
        test_code = str(parsed.get("test_code") or "")
        explanation = parsed.get("explanation", "")

        if not test_code.strip():
            await self._describe_tests(pr_context, tools, mentions, room_id)
            return

        returncode, output = test_runner.run_pytest(source_files, test_code)
        status = "✅ PASSED" if returncode == 0 else (
            "⚠️ NO TESTS COLLECTED" if returncode == 5 else "❌ FAILED"
        )
        message = (
            f"## Test Results\n\n"
            f"**{status}** (pytest exit code {returncode})\n\n"
            f"{explanation}\n\n"
            f"```\n{output}\n```\n\n"
            f"<details><summary>Generated test</summary>\n\n"
            f"```python\n{test_code}\n```\n</details>"
        )
        await tools.send_message(message, mentions=mentions)
        log.info("[Tester] Real test results posted (exit %d) to room %s", returncode, room_id)

    # --- description-only fallback -------------------------------------- #
    async def _describe_tests(
        self,
        pr_context: str,
        tools: AgentToolsProtocol,
        mentions: list[str],
        room_id: str,
    ) -> None:
        test_output = llm.complete_text(
            self._client,
            self._model,
            _TESTER_SYSTEM_PROMPT,
            pr_context or "(no PR context available)",
            max_tokens=2048,
        ) or "Test generation failed — LLM error."

        await tools.send_message(f"## Tests & Docs\n\n{test_output}", mentions=mentions)
        log.info("[Tester] Tests & docs posted to room %s", room_id)

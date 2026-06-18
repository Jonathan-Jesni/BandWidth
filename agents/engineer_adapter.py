"""EngineerAdapter — autonomous remediation agent.

Triggers on a "Blocker" verdict. Reads the blockers from the Reviewer's review
and the full source of the changed files (embedded by the Architect), asks the
LLM for whole-file rewrites that fix the blockers, and pushes them as a commit
directly to the PR head branch via the GitHub Contents API. That commit fires a
`synchronize` webhook, which kicks off a fresh review cycle automatically.

Gated behind ENABLE_AUTO_FIX (default off): pushing commits needs a write-scoped
token and mutates the author's branch.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import config
from agents import llm
from agents.architect_handler import (
    _GITHUB_API,
    _github_request,
    fetch_room_context_as_architect,
)
from agents.events import emit_task
from agents.room_payload import parse_files, parse_meta
from band.core.protocols import AgentToolsProtocol
from band.core.simple_adapter import SimpleAdapter
from band.core.types import PlatformMessage

log = logging.getLogger(__name__)

_EVENT_TYPES = {"tool_call", "tool_result", "thought", "error", "task"}
_MAX_ATTEMPTS = 1  # auto-fix pushes per (repo, pr) per process — guards push→sync loops

_ENGINEER_SYSTEM_PROMPT = """\
You are a senior software engineer. You are given a code review listing BLOCKER
issues and the full source of the changed files. Fix ONLY the blocking issues,
making the smallest correct change. Output ONLY valid JSON matching this schema:
{
  "edits": [{"path": "<file path exactly as given>", "new_content": "<the COMPLETE new file content>"}],
  "commit_message": "<concise commit message>"
}
Rules: return the entire file content for each edited file (not a diff); only
include files you actually changed; preserve unrelated code exactly. Also REMOVE
any comment that is now inaccurate because of your fix (e.g. a "BUG:"/"TODO" note
describing a problem you just resolved) — leaving it makes the reviewer re-flag it."""


class EngineerAdapter(SimpleAdapter[Any]):
    SUPPORTED_EMIT = frozenset()
    SUPPORTED_CAPABILITIES = frozenset()

    def __init__(self) -> None:
        super().__init__(history_converter=None)
        self._handled_rooms: set[str] = set()
        self._fix_attempts: dict[tuple[str, str], int] = {}
        self._client, self._model = llm.build(config.provider_for("engineer"))

    def _self_id(self) -> str | None:
        return getattr(self, "_band_agent_id", None)

    def _architect_mention(self, tools: AgentToolsProtocol) -> list[str]:
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
        if mentions:
            return mentions
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
        if room_id in self._handled_rooms:
            return
        if msg.message_type in _EVENT_TYPES:
            return
        content = msg.content or ""
        if "## Verdict" not in content or "Blocker" not in content:
            return

        self._handled_rooms.add(room_id)
        log.info("[Engineer] Blocker verdict received in room %s", room_id)
        await emit_task(tools, "Engineer", "fixing", model=self._model)

        mentions = self._architect_mention(tools)

        if not config.enable_auto_fix():
            await self._post(
                tools, mentions,
                "## Auto-Fix Failed\n\nAuto-fix is disabled (set ENABLE_AUTO_FIX=1 to enable).",
            )
            return

        # Gather PR context: metadata, source files, and the blocker review.
        # Read as the Architect — the opening message mentions only the Reviewer,
        # so it is invisible to the Engineer's own credentials.
        meta: dict[str, str] = {}
        sources: dict[str, str] = {}
        review = ""
        try:
            ctx = await fetch_room_context_as_architect(room_id)
            for m in ctx.get("data", []):
                c = m.get("content") or ""
                if "## Diff summary" in c:
                    meta = parse_meta(c)
                    sources = parse_files(c)
                if "## Code Review" in c and not review:
                    review = c
        except Exception:
            log.exception("[Engineer] could not read room context")

        head_repo = meta.get("head_repo") or meta.get("repo")
        branch = meta.get("branch")
        repo = meta.get("repo", "")
        pr = meta.get("pr", "")
        if not (head_repo and branch and sources):
            await self._post(
                tools, mentions,
                "## Auto-Fix Failed\n\nMissing branch metadata or source files — cannot patch.",
            )
            return

        key = (repo, pr)
        if self._fix_attempts.get(key, 0) >= _MAX_ATTEMPTS:
            await self._post(
                tools, mentions,
                "## Auto-Fix Failed\n\nStill blocked after an auto-fix attempt — manual review needed.",
            )
            return

        token = config.github_token()
        try:
            edits, commit_message = self._generate_fix(review, sources)
        except Exception:
            log.exception("[Engineer] fix-generation LLM call failed")
            await self._post(tools, mentions, "## Auto-Fix Failed\n\nCould not generate a fix (LLM error).")
            return

        if not edits:
            await self._post(tools, mentions, "## Auto-Fix Failed\n\nThe model proposed no file changes.")
            return

        self._fix_attempts[key] = self._fix_attempts.get(key, 0) + 1
        pushed: list[str] = []
        if not isinstance(edits, list):
            edits = []
        for edit in edits:
            if not isinstance(edit, dict):
                log.warning("[Engineer] skipping malformed edit entry %r", edit)
                continue
            path = edit.get("path", "")
            new_content = edit.get("new_content", "")
            if not path or path not in sources:
                log.warning("[Engineer] skipping edit to unknown path %r", path)
                continue
            try:
                self._push_file(head_repo, branch, path, new_content, commit_message, token)
                pushed.append(path)
            except Exception:
                log.exception("[Engineer] failed to push %s", path)

        if pushed:
            files_list = "\n".join(f"- `{p}`" for p in pushed)
            await self._post(
                tools, mentions,
                f"## Auto-Fix\n\nPushed a fix commit to `{branch}` "
                f"({commit_message}):\n{files_list}\n\n"
                f"A new review cycle will start automatically.",
            )
            await emit_task(tools, "Engineer", "pushed", files=len(pushed), branch=branch, model=self._model)
            log.info("[Engineer] pushed %d file(s) to %s@%s", len(pushed), head_repo, branch)
        else:
            await emit_task(tools, "Engineer", "fix:failed")
            await self._post(tools, mentions, "## Auto-Fix Failed\n\nNo files could be pushed.")

    # --- helpers -------------------------------------------------------- #
    def _generate_fix(
        self, review: str, sources: dict[str, str]
    ) -> tuple[list[dict], str]:
        files_blob = "\n\n".join(
            f"# === {path} ===\n{content}" for path, content in sources.items()
        )
        user = f"{review}\n\n## Source files\n{files_blob}"
        parsed = llm.complete_json(
            self._client, self._model, _ENGINEER_SYSTEM_PROMPT, user, max_tokens=8192
        )
        edits = parsed.get("edits", []) or []
        commit_message = parsed.get("commit_message", "BandWidth auto-fix")
        return edits, commit_message

    def _push_file(
        self,
        head_repo: str,
        branch: str,
        path: str,
        new_content: str,
        commit_message: str,
        token: str,
    ) -> None:
        """Commit a whole-file replacement to the PR branch via the Contents API."""
        url = f"{_GITHUB_API}/repos/{head_repo}/contents/{path}"
        # Need the current blob sha to update an existing file.
        get_resp = _github_request("GET", url, token, params={"ref": branch})
        sha = get_resp.json().get("sha")
        body = {
            "message": commit_message,
            "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        _github_request("PUT", url, token, json=body)

    async def _post(
        self, tools: AgentToolsProtocol, mentions: list[str], text: str
    ) -> None:
        if not mentions:
            log.warning("[Engineer] no one to mention — skipping post")
            return
        await tools.send_message(text, mentions=mentions)

"""Architect handler — triggered by GitHub webhooks, drives the Band review room.

For a PR event this module:
  1. Fetches the PR's changed files (diff summary + full source) from GitHub.
  2. Creates a Band room as the Architect agent.
  3. Adds the Reviewer, Tester, and Engineer agents as participants.
  4. Posts the PR context + diff summary + embedded source payload.
  5. Waits for a terminal message, then posts the full transcript back to GitHub.

For a PR-comment event (`handle_issue_comment`) it routes a human's question
into the existing room and posts the Reviewer's answer back to GitHub.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time

import requests

import config
from agents import llm
from agents.events import emit_task
from agents.room_payload import build_files, build_meta, strip_payload
from band import AgentTools
from band.platform import BandLink

log = logging.getLogger(__name__)

_EVENT_SUBTYPES = {"tool_call", "tool_result", "thought", "error", "task"}

_PLAN_SYSTEM_PROMPT = """\
You are the planning architect for an automated code review. Given a PR's diff
summary and the list of changed files, output ONLY valid JSON:
{
  "risk": "low | medium | high",
  "focus": "the 1-3 files or areas reviewers should scrutinize most",
  "strategy": "one or two sentences on what the review should prioritize"
}
Be terse and concrete."""

_GITHUB_API = "https://api.github.com"
_DIFF_CAP = 4000  # chars of human-readable diff summary
_SOURCE_TOTAL_CAP = 30_000  # chars of embedded full source across all files
_SOURCE_FILE_CAP = 12_000  # chars of embedded full source per file
_COMMENT_CAP = 65_000  # GitHub hard limit is 65536; leave headroom
_TESTER_DONE_MARKERS = (
    "## Tests & Docs",
    "## Test Results",
    "## Auto-Fix",
    "## Auto-Fix Failed",
    "Blocker detected",
)
_ROOM_MARKER_RE = re.compile(r"<!--\s*bandwidth-room:([^\s>]+)\s*-->")

# Source files large enough to embed must still look like text we can run/patch.
_TEXT_EXTS = (
    ".py", ".txt", ".md", ".cfg", ".ini", ".toml", ".json", ".yaml", ".yml",
    ".js", ".ts", ".html", ".css", ".sh",
)


# --------------------------------------------------------------------------- #
# GitHub REST helpers
# --------------------------------------------------------------------------- #
def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_request(
    method: str,
    url: str,
    token: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    max_retries: int = 3,
) -> requests.Response:
    """Hardened GitHub API call: retries on 5xx and secondary rate limits.

    Never logs the token. Raises requests.HTTPError on a non-2xx final response.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.request(
                method,
                url,
                headers=_gh_headers(token),
                json=json,
                params=params,
                timeout=15,
            )
        except requests.RequestException as exc:
            last_exc = exc
            log.warning(
                "GitHub %s %s: network error (attempt %d/%d): %s",
                method, url, attempt, max_retries, exc,
            )
            time.sleep(min(2 ** attempt, 8))
            continue

        # Secondary rate limit / abuse detection or transient server errors.
        if resp.status_code in (429, 500, 502, 503, 504) or (
            resp.status_code == 403 and "rate limit" in resp.text.lower()
        ):
            retry_after = resp.headers.get("Retry-After")
            delay = int(retry_after) if (retry_after or "").isdigit() else min(2 ** attempt, 8)
            log.warning(
                "GitHub %s %s: %d (attempt %d/%d), retrying in %ds",
                method, url, resp.status_code, attempt, max_retries, delay,
            )
            time.sleep(delay)
            continue

        if not resp.ok:
            log.error(
                "GitHub %s %s failed: %d %s",
                method, url, resp.status_code, resp.text[:500],
            )
            resp.raise_for_status()
        return resp

    if last_exc:
        raise last_exc
    raise RuntimeError(f"GitHub {method} {url}: exhausted retries")


def _fetch_pr_files(repo: str, pr_number: int, token: str) -> list[dict]:
    """Return the raw list of changed-file objects from the PR files endpoint."""
    url = f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}/files"
    resp = _github_request("GET", url, token, params={"per_page": 100})
    return resp.json()


def _diff_summary(files: list[dict]) -> str:
    """Build a compact, human-readable diff summary from the PR files."""
    lines: list[str] = []
    total = 0
    for f in files:
        header = f"+{f.get('additions', 0)} -{f.get('deletions', 0)}  {f['filename']}"
        lines.append(header)
        total += len(header) + 1
        patch = f.get("patch", "")
        if patch and total < _DIFF_CAP:
            chunk = patch[: _DIFF_CAP - total]
            lines.append(chunk)
            total += len(chunk)
        if total >= _DIFF_CAP:
            lines.append("… (diff truncated)")
            break
    return "\n".join(lines) if lines else "(no changed files)"


def _fetch_modified_sources(
    head_repo: str, head_ref: str, files: list[dict], token: str
) -> dict[str, str]:
    """Fetch full source of changed text files from the PR head branch.

    Returns {path: content}, capped per-file and in total. Removed files and
    non-text/oversized files are skipped.
    """
    sources: dict[str, str] = {}
    total = 0
    for f in files:
        path = f["filename"]
        if f.get("status") == "removed":
            continue
        if not path.lower().endswith(_TEXT_EXTS):
            continue
        if total >= _SOURCE_TOTAL_CAP:
            break
        try:
            url = f"{_GITHUB_API}/repos/{head_repo}/contents/{path}"
            resp = _github_request("GET", url, token, params={"ref": head_ref})
            data = resp.json()
        except Exception:
            log.warning("Could not fetch source for %s; skipping", path)
            continue
        if data.get("encoding") != "base64" or "content" not in data:
            continue
        try:
            content = base64.b64decode(data["content"]).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            log.warning("Source for %s is not UTF-8 text; skipping", path)
            continue
        if len(content) > _SOURCE_FILE_CAP:
            continue
        sources[path] = content
        total += len(content)
    return sources


def _plan(diff_summary: str, sources: dict[str, str]) -> str:
    """Run the Architect's planning step on the AI/ML-API model (cross-model).

    Triages the change and sets a review strategy, rendered as a `## Plan` block.
    Optional + best-effort: returns "" if the provider/LLM is unavailable.
    """
    try:
        client, model = llm.build(config.provider_for("architect"))
    except Exception:
        log.warning("Planner: no usable provider — skipping plan")
        return ""
    files_list = ", ".join(sources.keys()) or "(no source embedded)"
    user = f"## Diff summary\n{diff_summary}\n\nChanged files: {files_list}"
    parsed = llm.complete_json(client, model, _PLAN_SYSTEM_PROMPT, user, max_tokens=400)
    if not parsed:
        return ""
    risk = str(parsed.get("risk", "") or "unknown").strip()
    focus = str(parsed.get("focus", "") or "").strip()
    strategy = str(parsed.get("strategy", "") or "").strip()
    lines = [f"## Plan\n", f"- **Risk:** {risk}"]
    if focus:
        lines.append(f"- **Focus:** {focus}")
    if strategy:
        lines.append(f"- **Strategy:** {strategy}")
    lines.append(f"- _Planned by {model} (cross-model)._")
    return "\n".join(lines)


def _post_github_comment(repo: str, pr_number: int, token: str, body: str) -> None:
    if len(body) > _COMMENT_CAP:
        body = body[:_COMMENT_CAP] + "\n\n…(comment truncated)"
    url = f"{_GITHUB_API}/repos/{repo}/issues/{pr_number}/comments"
    _github_request("POST", url, token, json={"body": body})


_bot_login: str | None = None


def _bot_login_name(token: str) -> str | None:
    """Return (and cache) the authenticated user's login, for self-comment guards."""
    global _bot_login
    if _bot_login is None:
        try:
            resp = _github_request("GET", f"{_GITHUB_API}/user", token)
            _bot_login = resp.json().get("login")
        except Exception:
            log.warning("Could not resolve bot login; self-comment guard weakened")
            _bot_login = ""
    return _bot_login or None


# --------------------------------------------------------------------------- #
# Band room helpers
# --------------------------------------------------------------------------- #
def _architect_tools(room_id: str) -> tuple[AgentTools, AgentTools]:
    """Return (roomless_tools, room_tools) connected as the Architect."""
    architect = config.architect()
    link = BandLink(
        agent_id=architect.agent_id,
        api_key=architect.api_key,
        ws_url=config.BAND_WS_URL,
        rest_url=config.BAND_REST_URL,
    )
    rest = link.rest
    return AgentTools("", rest, []), AgentTools(room_id, rest, [])


async def fetch_room_context_as_architect(room_id: str, *, page_size: int = 100) -> dict:
    """Fetch room context using the Architect's credentials.

    The opening message mentions only the Reviewer (to avoid the 422 race), and
    Band hides non-mentioned messages from other agents. So the Tester and
    Engineer cannot see the diff/source payload with their own credentials —
    they read it through the Architect, who authored it. Single home for that
    workaround.
    """
    _, tools = _architect_tools(room_id)
    return await tools.fetch_room_context(room_id=room_id, page_size=page_size)


async def _wait_for_marker(
    tools: AgentTools,
    room_id: str,
    markers: tuple[str, ...],
    *,
    timeout: int = 300,
    interval: int = 5,
    baseline: int = 0,
) -> bool:
    """Poll the room until any `markers` string appears in a message.

    `baseline` lets callers ignore markers already present before they started
    (used so a fresh question waits for a *new* answer).
    """
    for _ in range(timeout // interval):
        await asyncio.sleep(interval)
        try:
            ctx = await tools.fetch_room_context(room_id=room_id, page_size=100)
            hits = sum(
                1
                for m in ctx.get("data", [])
                if any(marker in (m.get("content") or "") for marker in markers)
            )
            if hits > baseline:
                return True
        except Exception:
            pass
    return False


def _format_transcript(messages: list[dict]) -> str:
    lines = ["## BandWidth AI Review\n"]
    for m in messages:
        if m.get("message_type") in _EVENT_SUBTYPES:
            continue  # keep task/telemetry events out of the GitHub transcript
        sender = m.get("sender_name") or m.get("sender_id", "Agent")
        content = strip_payload(m.get("content") or "")
        if not content:
            continue
        lines.append(f"### {sender}\n{content}\n")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# PR event entrypoint
# --------------------------------------------------------------------------- #
async def handle_pr_event(payload: dict) -> None:
    """Create a Band review room seeded with the PR diff + source. Called from webhook."""
    try:
        repo = payload["repository"]["full_name"]
        pr = payload["pull_request"]
        pr_number = pr["number"]
        pr_title = pr["title"]
        pr_body = (pr.get("body") or "").strip()
        pr_url = pr["html_url"]
        head = pr.get("head", {})
        head_ref = head.get("ref", "")
        head_repo = (head.get("repo") or {}).get("full_name") or repo

        log.info("Handling PR #%d: %s (%s)", pr_number, pr_title, repo)

        token = config.github_token()
        files = _fetch_pr_files(repo, pr_number, token)
        diff_summary = _diff_summary(files)
        sources = _fetch_modified_sources(head_repo, head_ref, files, token)
        log.info("PR #%d: embedded %d source file(s)", pr_number, len(sources))

        # Planning stage: the Architect triages the change on the AI/ML-API model.
        plan = _plan(diff_summary, sources)
        plan_block = f"{plan}\n\n" if plan else ""

        # Build the opening message (human-readable + hidden machine payload).
        body_snippet = (
            pr_body[:400] + ("…" if len(pr_body) > 400 else "")
            if pr_body else "(no description)"
        )
        opening = (
            f"{build_meta(repo=repo, pr=pr_number, head_repo=head_repo, branch=head_ref)}\n"
            f"PR #{pr_number}: {pr_title}\n"
            f"{pr_url}\n\n"
            f"{body_snippet}\n\n"
            f"{plan_block}"
            f"## Diff summary\n"
            f"{diff_summary}\n\n"
            f"{build_files(sources)}\n"
            f"@Reviewer: please review."
        )

        architect = config.architect()
        reviewer = config.reviewer()
        tester = config.tester()
        engineer = config.engineer()

        roomless, _ = _architect_tools("")
        room_id = await roomless.create_chatroom()
        log.info("PR #%d: Created room %s", pr_number, room_id)

        tools = AgentTools(room_id, roomless.rest, [])
        for creds in (reviewer, tester, engineer):
            result = await tools.add_participant(creds.agent_id)
            log.info("PR #%d: Added %s: %s", pr_number, creds.name, result.get("status"))

        # Mention ONLY the Reviewer — it's the only agent that acts on the
        # opening. Mentioning multiple active agents risks the 422 resync race.
        await tools.get_participants()
        mentions = [
            p.get("handle") or p.get("name")
            for p in tools.participants
            if p.get("id") == reviewer.agent_id and (p.get("handle") or p.get("name"))
        ]
        log.info("PR #%d: Mentioning %s", pr_number, mentions)

        # Give agents time to join and complete their initial sync.
        await asyncio.sleep(3)

        await emit_task(tools, "Architect", "planned", files=len(sources))
        await tools.send_message(opening, mentions=mentions)
        await emit_task(tools, "Architect", "seeded:awaiting-review")
        log.info("PR #%d: Opening message posted to room %s", pr_number, room_id)

        # Wait for a terminal message, then post the full transcript to GitHub.
        log.info("PR #%d: Waiting for the pipeline to finish...", pr_number)
        finished = await _wait_for_marker(tools, room_id, _TESTER_DONE_MARKERS)
        if not finished:
            log.warning("PR #%d: pipeline timed out — posting partial transcript", pr_number)

        ctx = await tools.fetch_room_context(room_id=room_id, page_size=100)
        messages = list(reversed(ctx.get("data", [])))  # context is newest-first
        comment_body = _format_transcript(messages)
        comment_body += f"\n\n<!-- bandwidth-room:{room_id} -->"
        _post_github_comment(repo, pr_number, token, comment_body)
        log.info("PR #%d: GitHub comment posted", pr_number)

    except Exception:
        log.exception("architect_handler: failed to handle PR event")


# --------------------------------------------------------------------------- #
# Issue-comment entrypoint (bi-directional human-in-the-loop)
# --------------------------------------------------------------------------- #
def _find_room_id(repo: str, pr_number: int, token: str) -> str | None:
    """Find the room id embedded in the most recent BandWidth PR comment."""
    url = f"{_GITHUB_API}/repos/{repo}/issues/{pr_number}/comments"
    resp = _github_request("GET", url, token, params={"per_page": 100})
    room_id: str | None = None
    for comment in resp.json():  # oldest-first; keep the last match
        m = _ROOM_MARKER_RE.search(comment.get("body") or "")
        if m:
            room_id = m.group(1)
    return room_id


async def handle_issue_comment(payload: dict) -> None:
    """Route a human's PR comment into the Band room and post the answer back."""
    try:
        issue = payload.get("issue", {})
        if "pull_request" not in issue:
            return  # plain issue comment, not on a PR
        comment = payload.get("comment", {})
        body = (comment.get("body") or "").strip()
        author = (comment.get("user") or {}).get("login", "")
        repo = payload["repository"]["full_name"]
        pr_number = issue["number"]

        token = config.github_token()

        # Loop guard: never react to our own comments or to BandWidth-authored text.
        sentinels = ("<!-- bandwidth-room", "## BandWidth", "BandWidth Reviewer", "## Question")
        if any(s in body for s in sentinels):
            return
        if author and author == _bot_login_name(token):
            return
        if not body:
            return

        room_id = _find_room_id(repo, pr_number, token)
        if not room_id:
            log.info("PR #%d: no BandWidth room found for comment — ignoring", pr_number)
            return

        log.info("PR #%d: relaying human question into room %s", pr_number, room_id)
        roomless, tools = _architect_tools(room_id)

        await tools.get_participants()
        reviewer = config.reviewer()
        mentions = [
            p.get("handle") or p.get("name")
            for p in tools.participants
            if p.get("id") == reviewer.agent_id and (p.get("handle") or p.get("name"))
        ]
        if not mentions:
            log.warning("PR #%d: Reviewer not in room — cannot relay question", pr_number)
            return

        # Count existing answers so we wait for a *new* one.
        ctx = await tools.fetch_room_context(room_id=room_id, page_size=100)
        baseline = sum(
            1 for m in ctx.get("data", []) if "## Answer" in (m.get("content") or "")
        )

        await asyncio.sleep(3)
        await tools.send_message(
            f"## Question (from @{author})\n\n{body}", mentions=mentions
        )

        got = await _wait_for_marker(
            tools, room_id, ("## Answer",), timeout=90, baseline=baseline
        )
        if not got:
            log.warning("PR #%d: no answer from Reviewer in time", pr_number)
            return

        ctx = await tools.fetch_room_context(room_id=room_id, page_size=100)
        answer = next(
            (
                (m.get("content") or "")
                for m in ctx.get("data", [])  # newest-first
                if "## Answer" in (m.get("content") or "")
            ),
            "",
        ).replace("## Answer", "").strip()

        _post_github_comment(
            repo, pr_number, token, f"**BandWidth Reviewer:**\n\n{answer}"
        )
        log.info("PR #%d: answer posted back to GitHub", pr_number)

    except Exception:
        log.exception("architect_handler: failed to handle issue comment")

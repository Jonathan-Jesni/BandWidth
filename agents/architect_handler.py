"""Architect handler — triggered by GitHub webhook, sets up the Band review room.

When a PR is opened/updated, this module:
  1. Fetches the PR diff from the GitHub API.
  2. Creates a Band room as the Architect agent.
  3. Adds the Reviewer and Tester agents as participants.
  4. Posts the PR context + diff summary as the opening message.
"""

from __future__ import annotations

import asyncio
import logging

import requests

import config
from band import AgentTools
from band.platform import BandLink

log = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_DIFF_CAP = 4000  # chars; Band message size limit is generous but keep it readable


def _fetch_pr_files(repo: str, pr_number: int, token: str) -> str:
    """Return a compact diff summary for all changed files in the PR."""
    url = f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}/files"
    resp = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
    )
    resp.raise_for_status()
    files = resp.json()

    lines: list[str] = []
    total = 0
    for f in files:
        header = f"+{f.get('additions', 0)} -{f.get('deletions', 0)}  {f['filename']}"
        lines.append(header)
        total += len(header) + 1
        patch = f.get("patch", "")
        if patch and total < _DIFF_CAP:
            budget = _DIFF_CAP - total
            chunk = patch[:budget]
            lines.append(chunk)
            total += len(chunk)
        if total >= _DIFF_CAP:
            lines.append("… (diff truncated)")
            break

    return "\n".join(lines) if lines else "(no changed files)"


async def handle_pr_event(payload: dict) -> None:
    """Create a Band review room seeded with the PR diff. Called from webhook handler."""
    try:
        repo = payload["repository"]["full_name"]
        pr = payload["pull_request"]
        pr_number = pr["number"]
        pr_title = pr["title"]
        pr_body = (pr.get("body") or "").strip()
        pr_url = pr["html_url"]

        log.info("Handling PR #%d: %s (%s)", pr_number, pr_title, repo)

        token = config.github_token()
        diff_summary = _fetch_pr_files(repo, pr_number, token)

        # Build the opening message.
        body_snippet = pr_body[:400] + ("…" if len(pr_body) > 400 else "") if pr_body else "(no description)"
        opening = (
            f"PR #{pr_number}: {pr_title}\n"
            f"{pr_url}\n\n"
            f"{body_snippet}\n\n"
            f"## Diff summary\n"
            f"{diff_summary}\n\n"
            f"@Reviewer: please review. @Tester: stand by."
        )

        # Connect as Architect and create the room.
        architect = config.architect()
        reviewer = config.reviewer()
        tester = config.tester()

        link = BandLink(
            agent_id=architect.agent_id,
            api_key=architect.api_key,
            ws_url=config.BAND_WS_URL,
            rest_url=config.BAND_REST_URL,
        )
        rest = link.rest

        room_id = await AgentTools("", rest, []).create_chatroom()
        log.info("PR #%d: Created room %s", pr_number, room_id)

        tools = AgentTools(room_id, rest, [])
        for creds in (reviewer, tester):
            result = await tools.add_participant(creds.agent_id)
            log.info("PR #%d: Added %s: %s", pr_number, creds.name, result.get("status"))

        # Refresh participant cache so mention handles resolve correctly.
        await tools.get_participants()
        mentions = [
            p.get("handle") or p.get("name")
            for p in tools.participants
            if p.get("id") != architect.agent_id and (p.get("handle") or p.get("name"))
        ]
        log.info("PR #%d: Mentioning %s", pr_number, mentions)

        # Give agents time to join and complete their initial sync.
        await asyncio.sleep(3)

        await tools.send_message(opening, mentions=mentions)
        log.info("PR #%d: Opening message posted to room %s", pr_number, room_id)

    except Exception:
        log.exception("architect_handler: failed to handle PR event")

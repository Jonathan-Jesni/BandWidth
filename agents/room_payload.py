"""Shared helpers for the machine-readable payload the Architect embeds in the
opening Band message.

The opening message carries two HTML-comment blocks (invisible in rendered
GitHub markdown) so downstream agents can act without re-querying GitHub:

    <!-- bandwidth-meta repo=owner/repo pr=4 head_repo=owner/repo branch=feature/x -->
    <!--BANDWIDTH-FILES-START-->{"path/to/file.py": "<full source>"}<!--BANDWIDTH-FILES-END-->

The Tester reads the files to run real pytest; the Engineer reads them (and the
metadata) to write and push a fix.
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

META_RE = re.compile(r"<!--\s*bandwidth-meta\s+(.*?)\s*-->", re.DOTALL)
FILES_RE = re.compile(
    r"<!--BANDWIDTH-FILES-START-->(.*?)<!--BANDWIDTH-FILES-END-->", re.DOTALL
)

# Used by the transcript formatter to strip these blocks before posting to GitHub.
STRIP_RE = re.compile(
    r"<!--\s*bandwidth-meta\b.*?-->|<!--BANDWIDTH-FILES-START-->.*?<!--BANDWIDTH-FILES-END-->",
    re.DOTALL,
)


def build_meta(*, repo: str, pr: int, head_repo: str, branch: str) -> str:
    """Render the metadata sentinel for the opening message."""
    return (
        f"<!-- bandwidth-meta repo={repo} pr={pr} "
        f"head_repo={head_repo} branch={branch} -->"
    )


def build_files(files: dict[str, str]) -> str:
    """Render the files payload sentinel for the opening message."""
    return (
        "<!--BANDWIDTH-FILES-START-->"
        + json.dumps(files, ensure_ascii=False)
        + "<!--BANDWIDTH-FILES-END-->"
    )


def parse_meta(text: str) -> dict[str, str]:
    """Extract the `key=value` pairs from the bandwidth-meta sentinel."""
    if not text:
        return {}
    m = META_RE.search(text)
    if not m:
        return {}
    meta: dict[str, str] = {}
    for token in m.group(1).split():
        if "=" in token:
            key, _, value = token.partition("=")
            meta[key] = value
    return meta


def parse_files(text: str) -> dict[str, str]:
    """Extract the `{path: source}` map from the BANDWIDTH-FILES sentinel."""
    if not text:
        return {}
    m = FILES_RE.search(text)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except (ValueError, TypeError):
        log.warning("room_payload: could not decode embedded files payload")
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def strip_payload(text: str) -> str:
    """Remove the hidden meta/files blocks so transcripts stay readable."""
    if not text:
        return text
    return STRIP_RE.sub("", text).strip()

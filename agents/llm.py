"""Shared, hardened helpers for the Featherless (OpenAI-compatible) LLM calls.

Every agent funnels its completions through here so behavior is consistent:
  - temperature=0 (deterministic; this is what stops the degenerate repetition
    loops we saw the Reviewer fall into on trivial nitpicks);
  - one bounded retry on transient errors;
  - failures degrade gracefully ({} or "") instead of raising;
  - sanitize() is a last-resort guard so a runaway generation can never post a
    wall of repeated text into the room or a GitHub comment.
"""

from __future__ import annotations

import json
import logging
import time

log = logging.getLogger(__name__)


def _create(client, model, system, user, *, max_tokens, json_mode):
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    last_exc: Exception | None = None
    for attempt in range(2):  # one initial try + one retry
        try:
            resp = client.chat.completions.create(**kwargs)
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001 - transient API errors
            last_exc = exc
            log.warning("LLM call failed (attempt %d/2): %s", attempt + 1, exc)
            time.sleep(1)
    raise last_exc  # type: ignore[misc]


def complete_text(client, model, system, user, *, max_tokens: int = 1024) -> str:
    """Return the model's text response, or "" on failure (never raises)."""
    try:
        return _create(client, model, system, user, max_tokens=max_tokens, json_mode=False)
    except Exception:
        log.exception("complete_text: giving up after retry")
        return ""


def complete_json(client, model, system, user, *, max_tokens: int = 1024) -> dict:
    """Return the parsed JSON object, or {} on failure (never raises)."""
    try:
        raw = _create(client, model, system, user, max_tokens=max_tokens, json_mode=True)
    except Exception:
        log.exception("complete_json: giving up after retry")
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        log.warning("complete_json: response was not valid JSON")
        return {}
    return data if isinstance(data, dict) else {}


def _normalize(line: str) -> str:
    """Loose key for near-duplicate detection: lowercased, collapsed whitespace."""
    return " ".join(line.lower().split())


def sanitize(text: str, *, max_chars: int = 2000, max_lines: int = 12) -> str:
    """Collapse repeated/near-duplicate lines and hard-truncate.

    Guards against degenerate generations (the Reviewer's "floats…floats…" loop):
    even if the model rambles, what reaches the room stays short and readable.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return text
    seen: set[str] = set()
    kept: list[str] = []
    for raw_line in text.splitlines():
        key = _normalize(raw_line)
        if key and key in seen:
            continue  # drop exact/near duplicates
        if key:
            seen.add(key)
        kept.append(raw_line)
        if len(kept) >= max_lines:
            kept.append("… (truncated)")
            break
    result = "\n".join(kept).strip()
    if len(result) > max_chars:
        result = result[:max_chars].rstrip() + "… (truncated)"
    return result

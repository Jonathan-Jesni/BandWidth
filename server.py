"""Webhook listener — receives GitHub PR events and triggers the Architect."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import threading

from flask import Flask, abort, request

import config
from agents.architect_handler import handle_issue_comment, handle_pr_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("server")

app = Flask(__name__)


def _verify_signature(body: bytes, sig_header: str) -> bool:
    """Return True if the X-Hub-Signature-256 header matches our webhook secret."""
    if not sig_header.startswith("sha256="):
        return False
    secret = config.webhook_secret().encode()
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig_header, expected)


@app.route("/webhook", methods=["POST"])
def webhook() -> tuple[str, int]:
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(request.data, sig):
        log.warning("Webhook: invalid signature — rejected")
        abort(401)

    event = request.headers.get("X-GitHub-Event", "")
    payload = request.get_json(force=True) or {}
    action = payload.get("action", "")
    repo_name = payload.get("repository", {}).get("full_name", "?")

    # Run async handlers in a daemon thread so Flask returns 200 immediately.
    # GitHub webhooks time out at 10 s; the Band room setup takes ~5 s.
    def _dispatch(coro_fn) -> None:
        threading.Thread(target=lambda: asyncio.run(coro_fn(payload)), daemon=True).start()

    if event == "pull_request":
        if action not in ("opened", "synchronize", "reopened"):
            return "ok", 200
        pr_info = payload.get("pull_request", {})
        log.info("PR %s #%s (%s) — spinning up Architect",
                 repo_name, pr_info.get("number", "?"), action)
        _dispatch(handle_pr_event)
        return "ok", 200

    if event == "issue_comment":
        # Only newly created comments; the handler filters out non-PR and
        # bot-authored comments to avoid feedback loops.
        if action != "created":
            return "ok", 200
        log.info("Comment on %s #%s — relaying to Band",
                 repo_name, payload.get("issue", {}).get("number", "?"))
        _dispatch(handle_issue_comment)
        return "ok", 200

    return "ok", 200


if __name__ == "__main__":
    app.run(port=5000, debug=False)

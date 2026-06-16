"""Webhook listener — receives GitHub PR events and triggers the Architect."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import threading

from flask import Flask, abort, request

import config
from agents.architect_handler import handle_pr_event

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
    if event != "pull_request":
        return "ok", 200

    payload = request.get_json(force=True) or {}
    action = payload.get("action", "")
    if action not in ("opened", "synchronize", "reopened"):
        return "ok", 200

    pr_info = payload.get("pull_request", {})
    log.info(
        "PR %s #%s (%s) — spinning up Architect",
        payload.get("repository", {}).get("full_name", "?"),
        pr_info.get("number", "?"),
        action,
    )

    # Run the async handler in a daemon thread so Flask returns 200 immediately.
    # GitHub webhooks time out at 10 s; the Band room setup takes ~5 s.
    def _run() -> None:
        asyncio.run(handle_pr_event(payload))

    threading.Thread(target=_run, daemon=True).start()
    return "ok", 200


if __name__ == "__main__":
    app.run(port=5000, debug=False)

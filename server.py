"""Webhook listener — receives GitHub PR events and triggers the Architect."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import threading

from flask import Flask, abort, jsonify, request

import config
from agents.architect_handler import handle_issue_comment, handle_pr_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("server")

app = Flask(__name__)

_REPO_URL = "https://github.com/Jonathan-Jesni/BandWidth"

# Self-contained (no external assets) on-brand status page. This URL is the one
# link a judge is most likely to click, so it doubles as a 10-second pitch.
_LANDING_HTML = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BandWidth — The Autonomous Code-Review Crew</title>
<style>
  :root{ --bg:#0a0f24; --bg2:#111a3e; --card:#141c3c; --stroke:#2e3a6e;
    --cyan:#22d3ee; --text:#eef2ff; --muted:#aab6e6; --dim:#8190c4; --green:#34d399; }
  *{box-sizing:border-box} html,body{margin:0;height:100%}
  body{ background:radial-gradient(1200px 600px at 50% -10%, #1b1147 0%, var(--bg) 60%);
    color:var(--text); font-family:"Segoe UI",system-ui,-apple-system,sans-serif;
    display:flex; align-items:center; justify-content:center; padding:32px; }
  .wrap{ width:100%; max-width:760px; }
  .status{ display:inline-flex; align-items:center; gap:8px; font-size:13px; font-weight:600;
    color:var(--green); background:rgba(52,211,153,.1); border:1px solid rgba(52,211,153,.35);
    padding:6px 14px; border-radius:999px; letter-spacing:.3px; }
  .dot{ width:8px; height:8px; border-radius:50%; background:var(--green);
    box-shadow:0 0 0 0 rgba(52,211,153,.7); animation:pulse 2s infinite; }
  @keyframes pulse{ 0%{box-shadow:0 0 0 0 rgba(52,211,153,.6)} 70%{box-shadow:0 0 0 10px rgba(52,211,153,0)} 100%{box-shadow:0 0 0 0 rgba(52,211,153,0)} }
  h1{ font-size:54px; margin:22px 0 6px; letter-spacing:-1px; }
  h1 .w{ color:var(--cyan); }
  .tag{ font-size:20px; color:var(--muted); font-weight:500; margin:0 0 28px; }
  .lead{ font-size:16px; color:var(--muted); line-height:1.6; max-width:620px; }
  .chips{ display:flex; flex-wrap:wrap; gap:10px; margin:26px 0 30px; }
  .chip{ font-size:13.5px; font-weight:600; color:var(--text); background:var(--card);
    border:1px solid var(--stroke); padding:8px 14px; border-radius:10px; }
  .chip b{ color:var(--cyan); font-weight:700; }
  .cta{ display:inline-flex; align-items:center; gap:10px; text-decoration:none;
    background:var(--cyan); color:#06121b; font-weight:700; font-size:16px;
    padding:13px 22px; border-radius:12px; }
  .cta:hover{ filter:brightness(1.07); }
  .foot{ margin-top:34px; font-size:12.5px; color:var(--dim); }
  .foot b{ color:var(--muted); }
</style>
</head>
<body>
  <main class="wrap">
    <span class="status"><span class="dot"></span>SYSTEM LIVE</span>
    <h1>Band<span class="w">Width</span></h1>
    <p class="tag">The Autonomous Code-Review Crew</p>
    <p class="lead">Five specialized AI agents collaborate <b>through Band</b> to plan,
      review, fix, test, and document every GitHub pull request — and escalate to a human
      the moment they're genuinely stuck.</p>
    <div class="chips">
      <span class="chip"><b>1</b> Architect</span>
      <span class="chip"><b>2</b> Reviewer</span>
      <span class="chip"><b>3</b> Engineer</span>
      <span class="chip"><b>4</b> Tester</span>
      <span class="chip"><b>5</b> Documenter</span>
    </div>
    <p class="lead" style="margin-bottom:22px">This is the webhook listener. The product
      experience lives in the GitHub pull request thread the crew operates on.</p>
    <a class="cta" href="%REPO%">View the agents in action on GitHub &rarr;</a>
    <p class="foot">Webhook listener &middot; <b>POST /webhook</b> &middot; health at
      <b>/health</b> &middot; built by <b>Dev Duo</b></p>
  </main>
</body>
</html>
""".replace("%REPO%", _REPO_URL)


def _verify_signature(body: bytes, sig_header: str) -> bool:
    """Return True if the X-Hub-Signature-256 header matches our webhook secret."""
    if not sig_header.startswith("sha256="):
        return False
    secret = config.webhook_secret().encode()
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig_header, expected)


@app.route("/", methods=["GET"])
def index() -> str:
    return _LANDING_HTML


@app.route("/health", methods=["GET"])
def health():
    """Lightweight health check for uptime pings / load balancers."""
    return jsonify(status="ok", service="bandwidth-webhook"), 200


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
    import os

    # Host/port are env-configurable so the same entrypoint works locally
    # (default 127.0.0.1) and inside a container (set HOST=0.0.0.0).
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port, debug=False)

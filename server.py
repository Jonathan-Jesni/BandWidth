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
<title>bandwidth — the autonomous code-review crew</title>
<style>
  :root{
    --bg:#0c0c0c; --panel:#101010; --panel-2:#0e0e0e;
    --line:rgba(255,255,255,.08); --line-2:rgba(255,255,255,.14);
    --fg:#d7d7cf; --dim:#6b716a; --bright:#f2f2ec;
    --accent:#4ade80; --accent-dim:#2f7d4f;
    --ease:cubic-bezier(.2,.7,.3,1);
    --mono:ui-monospace,"SF Mono","JetBrains Mono","Cascadia Code",Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html{height:100%}
  body{
    min-height:100%; background:var(--bg); color:var(--fg);
    font-family:var(--mono); font-size:15px; line-height:1.6;
    -webkit-font-smoothing:antialiased;
    display:flex; flex-direction:column; position:relative; overflow-x:hidden;
  }
  /* one faint vignette only — no scanlines */
  body::before{
    content:""; position:fixed; inset:0; z-index:0; pointer-events:none;
    background:radial-gradient(1100px 700px at 50% 0%, rgba(74,222,128,.05), transparent 60%);
  }
  .wrap{ position:relative; z-index:1; width:100%; max-width:920px;
    margin:0 auto; padding:clamp(20px,4vw,40px); flex:1 0 auto;
    display:flex; flex-direction:column; min-width:0; }

  /* top bar */
  .bar{ display:flex; align-items:center; justify-content:space-between;
    gap:16px; margin-bottom:clamp(22px,4vh,38px); }
  .brand{ display:flex; align-items:baseline; gap:2px; color:var(--bright);
    font-weight:600; font-size:15px; letter-spacing:.02em; }
  .brand .pmt{ color:var(--accent); margin-right:8px; }
  .caret{ display:inline-block; width:8px; height:1.05em; transform:translateY(2px);
    margin-left:4px; background:var(--accent); animation:blink 1.1s steps(1) infinite; }
  @keyframes blink{ 0%,50%{opacity:1} 50.01%,100%{opacity:0} }
  .online{ display:inline-flex; align-items:center; gap:8px; color:var(--dim);
    font-size:12px; letter-spacing:.04em; }
  .online .dot{ width:7px; height:7px; border-radius:50%; background:var(--accent);
    box-shadow:0 0 8px rgba(74,222,128,.7); animation:breathe 2.6s var(--ease) infinite; }
  @keyframes breathe{ 0%,100%{opacity:.5} 50%{opacity:1} }

  /* terminal panel */
  .term{ border:1px solid var(--line); border-radius:12px; background:var(--panel);
    box-shadow:0 24px 60px -30px rgba(0,0,0,.9), inset 0 1px 0 rgba(255,255,255,.03);
    overflow:hidden; }
  .term-head{ display:flex; align-items:center; gap:12px;
    padding:12px 16px; border-bottom:1px solid var(--line); background:var(--panel-2); }
  .dots{ display:flex; gap:7px; }
  .dots i{ width:11px; height:11px; border-radius:50%; background:#2a2a2a; }
  .term-head .path{ color:var(--dim); font-size:12.5px; }
  .term-head .tab{ margin-left:auto; color:var(--dim); font-size:11.5px;
    border:1px solid var(--line); border-radius:6px; padding:3px 9px; letter-spacing:.05em; }
  .term-body{ padding:clamp(18px,3.2vw,30px); overflow-x:auto; }

  .line{ white-space:pre; } /* keep command columns honest; body scrolls if narrow */
  .cmt{ color:var(--dim); }
  .cmd{ color:var(--bright); margin-top:6px; }
  .cmd .p{ color:var(--accent); margin-right:10px; }
  .out{ color:var(--fg); white-space:normal; }            /* prose wraps */
  .blk{ margin:6px 0 20px; }
  .blk:last-child{ margin-bottom:0; }

  /* crew list — aligned columns via monospace */
  .crew{ margin:8px 0 20px; }
  .crew .r{ display:flex; gap:14px; padding:3px 0; align-items:baseline; }
  .crew .nm{ color:var(--accent); flex:0 0 124px; }
  .crew .rl{ color:var(--fg); min-width:0; }
  @media (max-width:520px){ .crew .nm{ flex-basis:96px } }

  /* run log — streamed */
  .log .ln{ display:flex; gap:12px; align-items:baseline; padding:2px 0;
    opacity:0; transform:translateY(6px); }
  .log .ln.show{ opacity:1; transform:none; transition:opacity .4s var(--ease),transform .4s var(--ease); }
  .log .tag{ color:var(--accent); flex:0 0 116px; }
  .log .msg{ color:var(--fg); min-width:0; }
  .log .msg b{ color:var(--bright); font-weight:600; }
  .log .ok{ color:var(--accent); }
  .runcaret{ display:inline-block; width:8px; height:1.05em; transform:translateY(2px);
    background:var(--accent); opacity:0; }
  .runcaret.show{ opacity:1; animation:blink 1.1s steps(1) infinite; }
  @media (max-width:520px){ .log .tag{ flex-basis:96px } }

  /* action row */
  .row{ margin-top:clamp(26px,4vh,40px); display:flex; flex-wrap:wrap;
    align-items:center; gap:14px 22px; }
  .cta{ display:inline-flex; align-items:center; gap:9px; text-decoration:none;
    font-family:var(--mono); font-size:14px; font-weight:600; color:#06140c;
    background:var(--accent); padding:12px 20px; border-radius:9px; letter-spacing:.01em;
    transition:transform .25s var(--ease), box-shadow .25s var(--ease);
    box-shadow:0 0 0 1px rgba(74,222,128,.4), 0 12px 30px -14px rgba(74,222,128,.7); }
  .cta:hover{ transform:translateY(-2px); box-shadow:0 0 0 1px rgba(74,222,128,.6),0 18px 38px -14px rgba(74,222,128,.85); }
  .cta .arr{ transition:transform .25s var(--ease); }
  .cta:hover .arr{ transform:translateX(4px); }
  .cta2{ display:inline-flex; align-items:center; gap:9px; text-decoration:none;
    font-family:var(--mono); font-size:14px; font-weight:600; color:var(--accent);
    background:transparent; padding:11px 19px; border-radius:9px; letter-spacing:.01em;
    border:1px solid var(--accent-dim);
    transition:transform .25s var(--ease), border-color .25s var(--ease), background .25s var(--ease); }
  .cta2:hover{ transform:translateY(-2px); border-color:var(--accent); background:rgba(74,222,128,.07); }
  .ghost{ color:var(--dim); text-decoration:none; font-size:13.5px;
    border-bottom:1px solid var(--line-2); padding-bottom:2px;
    transition:color .2s var(--ease), border-color .2s var(--ease); }
  .ghost:hover{ color:var(--fg); border-color:var(--accent); }
  a:focus-visible,.cta:focus-visible{ outline:2px solid var(--accent); outline-offset:3px; border-radius:6px; }

  /* footer */
  .foot{ position:relative; z-index:1; width:100%; max-width:920px;
    margin:clamp(30px,6vh,56px) auto 0; padding:18px clamp(20px,4vw,40px) 30px;
    border-top:1px solid var(--line);
    display:flex; flex-wrap:wrap; gap:12px 20px; align-items:center; justify-content:space-between; }
  .ends{ display:flex; flex-wrap:wrap; gap:8px; }
  .ends code{ font-family:var(--mono); font-size:11.5px; color:var(--dim);
    border:1px solid var(--line); border-radius:6px; padding:5px 9px; white-space:nowrap; }
  .ends code b{ color:var(--accent); font-weight:600; }
  .by{ color:var(--dim); font-size:12px; letter-spacing:.02em; }
  .by b{ color:var(--fg); font-weight:600; }

  /* entrance: panel + bar fade up */
  .rise{ opacity:0; transform:translateY(14px); animation:rise .6s var(--ease) forwards; }
  .d1{animation-delay:.04s}.d2{animation-delay:.12s}.d3{animation-delay:.22s}
  @keyframes rise{ to{opacity:1;transform:none} }

  @media (prefers-reduced-motion:reduce){
    .rise{animation:none;opacity:1;transform:none}
    .caret,.online .dot,.runcaret.show{animation:none}
    .log .ln{opacity:1;transform:none}
    *{transition:none !important}
  }
</style>
</head>
<body>
  <div class="wrap">
    <header class="bar rise d1">
      <span class="brand"><span class="pmt">$</span>bandwidth<span class="caret"></span></span>
      <span class="online"><span class="dot"></span>online</span>
    </header>

    <main class="term rise d2">
      <div class="term-head">
        <span class="dots"><i></i><i></i><i></i></span>
        <span class="path">~/bandwidth</span>
        <span class="tab">webhook listener</span>
      </div>
      <div class="term-body">

        <div class="blk">
          <div class="line cmt"># The Autonomous Code-Review Crew</div>
          <div class="line cmd"><span class="p">$</span>whoami</div>
          <p class="out">Five specialized AI agents that collaborate <b style="color:var(--bright)">through Band</b>
            to plan, review, fix, test, and document every GitHub pull request — and escalate to a
            human the moment they're genuinely stuck. This service is the webhook listener; the
            product lives in the pull-request thread itself.</p>
        </div>

        <div class="blk">
          <div class="line cmd"><span class="p">$</span>bandwidth crew --list</div>
          <div class="crew">
            <div class="r"><span class="nm">architect</span><span class="rl">plans &amp; coordinates the room</span></div>
            <div class="r"><span class="nm">reviewer</span><span class="rl">judges the diff, routes the verdict</span></div>
            <div class="r"><span class="nm">engineer</span><span class="rl">pushes a real fix commit</span></div>
            <div class="r"><span class="nm">tester</span><span class="rl">runs real pytest in a sandbox</span></div>
            <div class="r"><span class="nm">documenter</span><span class="rl">writes the final PR summary</span></div>
          </div>
        </div>

        <div class="blk">
          <div class="line cmd"><span class="p">$</span>bandwidth run --pr 42</div>
          <div class="log" id="log">
            <div class="ln"><span class="tag">[architect]</span><span class="msg">room created · diff + source posted</span></div>
            <div class="ln"><span class="tag">[reviewer]</span><span class="msg">verdict: <b>blocker</b> &rarr; engineer</span></div>
            <div class="ln"><span class="tag">[engineer]</span><span class="msg">pushed fix <b>a1b2c3d</b> · re-running</span></div>
            <div class="ln"><span class="tag">[reviewer]</span><span class="msg">verdict: <b>pass</b> &rarr; tester</span></div>
            <div class="ln"><span class="tag">[tester]</span><span class="msg">pytest · <span class="ok">6 passed</span></span></div>
            <div class="ln"><span class="tag">[documenter]</span><span class="msg">PR description updated &check;</span></div>
          </div>
          <div class="line"><span style="color:var(--accent)">$</span> <span class="runcaret" id="caret"></span></div>
        </div>

      </div>
    </main>

    <div class="row rise d3">
      <a class="cta" href="%REPO%">view source <span class="arr">&rarr;</span></a>
      <a class="cta2" href="%REPO%/pulls">view pull requests</a>
      <a class="ghost" href="%REPO%/blob/main/README.md">read the documentation</a>
    </div>
  </div>

  <footer class="foot">
    <div class="ends">
      <code><b>GET</b> /</code>
      <code><b>GET</b> /health</code>
      <code><b>POST</b> /webhook</code>
    </div>
    <span class="by">built by <b>Dev Duo</b> · cross-model · coordinated through Band</span>
  </footer>

  <script>
    // Stream the run log once on load (a live agent run), then leave a blinking
    // caret. Lines reserve their space up-front (opacity/transform only) so there
    // is no layout shift or clipping.
    (function(){
      var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      var lines = Array.prototype.slice.call(document.querySelectorAll('#log .ln'));
      var caret = document.getElementById('caret');
      if(reduce){ lines.forEach(function(l){ l.classList.add('show'); }); if(caret) caret.classList.add('show'); return; }
      lines.forEach(function(l,i){ setTimeout(function(){ l.classList.add('show'); }, 700 + i*260); });
      setTimeout(function(){ if(caret) caret.classList.add('show'); }, 700 + lines.length*260 + 150);
    })();
  </script>
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

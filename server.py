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
  :root{
    --bg:#070b16; --ink:#f4f7ff; --muted:#9aa7c7; --faint:#64709a;
    --line:rgba(140,160,210,.14); --line-2:rgba(140,160,210,.28);
    --accent:#4fe3d6; --accent-2:#5ab0ff; --panel:rgba(255,255,255,.02);
    --ease:cubic-bezier(.16,.84,.44,1);
    --mono:ui-monospace,"SF Mono","Cascadia Code",Menlo,Consolas,monospace;
    --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%}
  body{
    background:var(--bg); color:var(--ink); font-family:var(--sans);
    -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
    min-height:100%; display:flex; flex-direction:column;
    position:relative; overflow-x:hidden;
  }
  /* ambient: one faint off-center wash + a hairline grid, no candy gradients */
  body::before{
    content:""; position:fixed; inset:0; z-index:0; pointer-events:none;
    background:
      radial-gradient(900px 520px at 78% -8%, rgba(79,227,214,.10), transparent 60%),
      radial-gradient(760px 600px at 8% 108%, rgba(90,176,255,.08), transparent 55%);
  }
  body::after{
    content:""; position:fixed; inset:0; z-index:0; pointer-events:none; opacity:.5;
    background-image:linear-gradient(var(--line) 1px,transparent 1px),
      linear-gradient(90deg,var(--line) 1px,transparent 1px);
    background-size:64px 64px; -webkit-mask-image:radial-gradient(circle at 50% 30%,#000,transparent 78%);
    mask-image:radial-gradient(circle at 50% 30%,#000,transparent 78%);
  }
  .shell{ position:relative; z-index:1; width:100%; max-width:1080px;
    margin:0 auto; padding:40px clamp(22px,5vw,64px); flex:1 0 auto;
    display:flex; flex-direction:column; }

  /* top bar */
  .bar{ display:flex; align-items:center; justify-content:space-between; gap:16px; }
  .brand{ display:flex; align-items:center; gap:11px; font-weight:600; letter-spacing:-.01em; }
  .glyph{ width:26px; height:26px; border-radius:7px; position:relative;
    background:linear-gradient(135deg,var(--accent),var(--accent-2)); }
  .glyph::after{ content:""; position:absolute; inset:7px; border-radius:3px; background:var(--bg); }
  .brand b{ font-size:16px; font-weight:650; }
  .status{ display:inline-flex; align-items:center; gap:9px;
    font:600 11px/1 var(--mono); letter-spacing:.16em; text-transform:uppercase;
    color:var(--muted); border:1px solid var(--line-2); border-radius:999px; padding:8px 13px; }
  .live{ width:7px; height:7px; border-radius:50%; background:var(--accent);
    box-shadow:0 0 0 4px rgba(79,227,214,.16); animation:breathe 3.2s var(--ease) infinite; }
  @keyframes breathe{ 0%,100%{opacity:.55} 50%{opacity:1} }

  /* hero */
  .hero{ margin-top:clamp(56px,11vh,128px); max-width:760px; }
  .eyebrow{ font:600 12px/1 var(--mono); letter-spacing:.2em; text-transform:uppercase;
    color:var(--accent); margin-bottom:22px; }
  h1{ font-size:clamp(44px,8.5vw,92px); line-height:.96; letter-spacing:-.035em; font-weight:680; }
  h1 .w{ color:transparent; background:linear-gradient(120deg,var(--accent),var(--accent-2));
    -webkit-background-clip:text; background-clip:text; }
  .tag{ margin-top:18px; font-size:clamp(17px,2.4vw,21px); color:var(--ink); font-weight:500; opacity:.92; }
  .lead{ margin-top:20px; max-width:600px; font-size:16px; line-height:1.65; color:var(--muted); }
  .lead em{ color:var(--ink); font-style:normal; font-weight:600; }

  /* pipeline */
  .flow{ margin-top:clamp(40px,6vh,64px); }
  .flow .cap{ font:600 11px/1 var(--mono); letter-spacing:.18em; text-transform:uppercase;
    color:var(--faint); margin-bottom:16px; }
  .rail{ position:relative; display:flex; align-items:center; gap:0;
    overflow-x:auto; padding-bottom:6px; scrollbar-width:none; }
  .rail::-webkit-scrollbar{ display:none; }
  .node{ flex:0 0 auto; display:flex; flex-direction:column; align-items:center; gap:9px; min-width:84px; }
  .pip{ width:11px; height:11px; border-radius:50%; background:#1a2236; border:1px solid var(--line-2);
    transition:background .4s var(--ease),box-shadow .4s var(--ease),border-color .4s var(--ease); }
  .node.on .pip{ background:var(--accent); border-color:var(--accent);
    box-shadow:0 0 0 5px rgba(79,227,214,.14),0 0 14px rgba(79,227,214,.5); }
  .node span{ font-size:12.5px; color:var(--muted); white-space:nowrap; letter-spacing:.01em;
    transition:color .4s var(--ease); }
  .node.on span{ color:var(--ink); }
  .node small{ font:600 9.5px/1 var(--mono); letter-spacing:.12em; text-transform:uppercase; color:var(--faint); }
  .seg{ flex:1 1 auto; min-width:24px; height:1px; background:var(--line-2); position:relative; }
  .endpt span{ color:var(--accent-2); }

  /* CTA + meta */
  .row{ margin-top:clamp(40px,6vh,60px); display:flex; flex-wrap:wrap; align-items:center; gap:18px 26px; }
  .cta{ display:inline-flex; align-items:center; gap:10px; text-decoration:none;
    font-size:15px; font-weight:650; color:#04120f; background:var(--accent);
    padding:14px 22px; border-radius:12px; letter-spacing:.005em;
    transition:transform .3s var(--ease),box-shadow .3s var(--ease),background .3s var(--ease);
    box-shadow:0 10px 30px -12px rgba(79,227,214,.55); }
  .cta:hover{ transform:translateY(-2px); box-shadow:0 16px 38px -12px rgba(79,227,214,.7); }
  .cta .arr{ transition:transform .3s var(--ease); }
  .cta:hover .arr{ transform:translateX(4px); }
  .ghost{ font-size:14px; color:var(--muted); text-decoration:none; border-bottom:1px solid var(--line-2);
    padding-bottom:2px; transition:color .25s var(--ease),border-color .25s var(--ease); }
  .ghost:hover{ color:var(--ink); border-color:var(--accent); }
  a:focus-visible,.cta:focus-visible{ outline:2px solid var(--accent); outline-offset:3px; border-radius:6px; }

  /* footer */
  .foot{ position:relative; z-index:1; border-top:1px solid var(--line);
    margin-top:clamp(48px,8vh,96px); padding:22px clamp(22px,5vw,64px);
    display:flex; flex-wrap:wrap; gap:10px 22px; align-items:center; justify-content:space-between;
    max-width:1080px; margin-left:auto; margin-right:auto; width:100%; }
  .ends{ display:flex; flex-wrap:wrap; gap:8px; }
  .ends code{ font:500 11.5px/1 var(--mono); color:var(--faint);
    border:1px solid var(--line); border-radius:7px; padding:6px 9px; }
  .ends code b{ color:var(--accent); font-weight:600; }
  .by{ font:500 12px/1 var(--mono); letter-spacing:.04em; color:var(--faint); }
  .by b{ color:var(--muted); font-weight:600; }

  /* entrance choreography — staggered, ease-out */
  .rise{ opacity:0; transform:translateY(16px); animation:rise .7s var(--ease) forwards; }
  .d1{animation-delay:.05s}.d2{animation-delay:.14s}.d3{animation-delay:.23s}
  .d4{animation-delay:.34s}.d5{animation-delay:.46s}.d6{animation-delay:.58s}
  @keyframes rise{ to{opacity:1;transform:none} }

  @media (prefers-reduced-motion:reduce){
    .rise{animation:none;opacity:1;transform:none}
    .live{animation:none}
    .node.on .pip{box-shadow:0 0 0 5px rgba(79,227,214,.14)}
    * { transition:none !important; }
  }
  @media (max-width:560px){
    .node small{display:none} .node{min-width:64px}
    .status .lbl{display:none}
  }
</style>
</head>
<body>
  <div class="shell">
    <header class="bar rise d1">
      <div class="brand"><span class="glyph"></span><b>BandWidth</b></div>
      <span class="status"><span class="live"></span><span class="lbl">Operational</span></span>
    </header>

    <main class="hero">
      <p class="eyebrow rise d1">Multi-Agent Software Development</p>
      <h1 class="rise d2">The Autonomous<br>Code-Review <span class="w">Crew</span>.</h1>
      <p class="tag rise d3">Five specialized AI agents. One coordination layer — Band.</p>
      <p class="lead rise d3">They <em>plan, review, fix, test, and document</em> every GitHub
        pull request — handing work to one another through Band, and escalating to a human
        the moment they're genuinely stuck. This service is the webhook listener; the product
        lives in the pull-request thread itself.</p>

      <section class="flow rise d4" aria-label="The agent handoff pipeline">
        <p class="cap">Handoff pipeline</p>
        <div class="rail">
          <div class="node endpt" data-step="0"><span class="pip"></span><span>GitHub</span><small>PR</small></div>
          <div class="seg"></div>
          <div class="node" data-step="1"><span class="pip"></span><span>Architect</span><small>Plan</small></div>
          <div class="seg"></div>
          <div class="node" data-step="2"><span class="pip"></span><span>Reviewer</span><small>Verdict</small></div>
          <div class="seg"></div>
          <div class="node" data-step="3"><span class="pip"></span><span>Engineer</span><small>Fix</small></div>
          <div class="seg"></div>
          <div class="node" data-step="4"><span class="pip"></span><span>Tester</span><small>pytest</small></div>
          <div class="seg"></div>
          <div class="node" data-step="5"><span class="pip"></span><span>Documenter</span><small>Write</small></div>
          <div class="seg"></div>
          <div class="node endpt" data-step="6"><span class="pip"></span><span>GitHub</span><small>Merge</small></div>
        </div>
      </section>

      <div class="row rise d5">
        <a class="cta" href="%REPO%">See the agents in action&nbsp;<span class="arr">&rarr;</span></a>
        <a class="ghost" href="%REPO%">Read the architecture &amp; docs</a>
      </div>
    </main>
  </div>

  <footer class="foot rise d6">
    <div class="ends">
      <code><b>GET</b>&nbsp;/</code>
      <code><b>GET</b>&nbsp;/health</code>
      <code><b>POST</b>&nbsp;/webhook</code>
    </div>
    <span class="by">built by <b>Dev&nbsp;Duo</b> · cross-model · coordinated through Band</span>
  </footer>

  <script>
    // Signature motion: a handoff "packet" walks the pipeline, lighting each
    // node in turn — the product's behaviour, shown. Pure JS, no deps.
    (function(){
      var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      var nodes = Array.prototype.slice.call(document.querySelectorAll('.node'));
      if(!nodes.length) return;
      if(reduce){ nodes.forEach(function(n){ n.classList.add('on'); }); return; }
      var i = 0;
      function step(){
        nodes.forEach(function(n,idx){ n.classList.toggle('on', idx <= i); });
        i++;
        if(i > nodes.length){ // brief hold on full path, then reset and replay
          setTimeout(function(){ nodes.forEach(function(n){ n.classList.remove('on'); }); i = 0; }, 900);
        }
      }
      setTimeout(function(){ step(); setInterval(step, 620); }, 800);
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

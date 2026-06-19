# BandWidth — The Autonomous Code-Review Crew

> **Track 2 — Multi-Agent Software Development** · built by **Dev Duo** on the [Band platform](https://app.band.ai)

**The problem.** Code review is the most expensive recurring coordination tax in software. Every pull request stalls waiting on a human reviewer, context is scattered across diffs, CI logs, and chat, and the loop from "found a bug" to "fixed and verified" is measured in days. Teams don't lack tools — they lack *coordination*.

**BandWidth** is a crew of **five specialized AI agents** that collaborate **through Band** to plan, review, fix, test, and document every GitHub pull request — and escalate to a human the moment they're genuinely stuck. When a developer opens or updates a PR, a secure webhook spins up an isolated Band room and the crew goes to work: the Reviewer hands a Blocker to the Engineer, the Engineer pushes a real fix commit, the Tester runs actual pytest, and the Documenter writes the final PR description — turning hours of human glue into minutes of autonomous, auditable collaboration.

### Band is the collaboration layer — not a notifier

The agents don't just *report* to Band; they *work* in it. Coordination happens through Band as a first-class part of the workflow:

- **Discovery** — agents are added to a per-PR room and address each other by identity.
- **Task handoffs by `agent_id`** — each verdict is routed to exactly one teammate (Pass → Tester, Blocker → Engineer). A direct delegation, never a broadcast.
- **Shared context** — the full diff + changed-file source live in the room; teammates read it through the Architect.
- **Typed task-state events** — every stage emits a `task` event, so coordination is visible as a Band primitive, not just chat.
- **Strict-mode escalation** — a stuck Reviewer↔Engineer debate hits a cap and hands off to a human with a written handover.
- **Bi-directional human sync** — a reply on the GitHub PR flows into the room and the answer flows back out.

![Python](https://img.shields.io/badge/Python-3.x-blue?style=flat&logo=python)
![Flask](https://img.shields.io/badge/Flask-Server-black?style=flat&logo=flask)
![GitHub Webhooks](https://img.shields.io/badge/GitHub-Webhooks-lightgrey?style=flat&logo=github)
![Band AI](https://img.shields.io/badge/Band_AI-Multi--Agent_Platform-orange?style=flat)
![Featherless AI](https://img.shields.io/badge/Featherless_AI-Serverless-purple?style=flat)
![DeepSeek V4](https://img.shields.io/badge/DeepSeek--V4--Pro-1.6T-blue?style=flat)
![AI/ML API](https://img.shields.io/badge/AI/ML_API-Gateway-red?style=flat)
![GPT-4o](https://img.shields.io/badge/OpenAI-GPT--4o-green?style=flat)

---

## 🏗️ Architecture & Component Flow

```text
GitHub PR Event 
   │
   ▼
[ Flask Server: server.py ] ──► (Validates HMAC SHA256 Signature)
   │
   ▼ Spawns Background Daemon Thread
[ agents/architect_handler.py ]
   │
   ├──► 1. Queries GitHub REST API for targeted PR code diffs
   ├──► 2. Plans the review & PATCHes GitHub PR Description (AI/ML API)
   ├──► 3. Creates an isolated Band Chatroom
   ├──► 4. Injects Specialized Agents (Reviewer, Tester, Engineer, Documenter)
   └──► 5. Dispatches Initial Markdown Context (+ embedded source) & Mentions
              │
              ├──► [ Reviewer Agent ] ──► Reviews; routes verdict
              │         ├─ Pass    ──► [ Tester Agent ]   ──► Runs real pytest in a sandbox
              │         └─ Blocker ──► [ Engineer Agent ] ──► Pushes a fix commit to the PR branch
              │
              ├──► [ Documenter Agent ] ──► Synthesizes final outcome & updates GitHub PR Description
              │
              └──► (Human replies to the PR comment are relayed back into the room;
                    the Reviewer answers and the answer is posted to GitHub.)
```

### Winning capabilities

1. **Engineer agent (auto-remediation).** On a `Blocker`, the Engineer writes a
   whole-file fix and pushes a commit to the PR head branch (GitHub Contents
   API). The resulting `synchronize` event auto-triggers a fresh review cycle.
   Gated behind `ENABLE_AUTO_FIX` (default off).
2. **Bi-directional GitHub sync.** A human reply on the PR comment is routed back
   into the Band room via an `issue_comment` webhook; the Reviewer answers and
   the answer is posted back to GitHub. Guards prevent the bot answering itself.
3. **Real test execution.** With `ENABLE_TEST_EXECUTION` on, the Architect embeds
   the modified files' full source in the room; the Tester writes them plus an
   LLM-generated pytest file into a `tempfile.TemporaryDirectory()` and runs
   `pytest` in a sandboxed subprocess, posting the **real** pass/fail output.
4. **Documenter agent (the 5th agent).** A passive observer that stays silent during
   the Reviewer↔Engineer↔Tester debate and wakes only on a *terminal* signal
   (`## Test Results` / `## Tests & Docs` or `## Escalated for Human Review`). It
   reads the full room transcript, synthesizes a polished `## Final PR Documentation`
   block, and the Architect pushes it to the **GitHub PR description**. It narrates
   only what actually happened — no fix is claimed unless the Engineer truly pushed one.
5. **Strict-mode escalation.** With `REVIEWER_MODE=strict`, the Reviewer blocks any
   unhandled edge case, driving a multi-cycle Reviewer→Engineer→Reviewer debate. When
   the per-PR attempt cap is hit, the pipeline **escalates to a human** with a
   handover document instead of looping forever — agents that *know when to stop and
   ask for help*.

### Cross-model topology

BandWidth is a **cross-model** multi-agent system — different agents reason on
different inference providers, all coordinated through Band:

| Agent | Provider | Model |
|-------|----------|-------|
| Reviewer, Tester | **Featherless** (open-source inference) | `deepseek-ai/DeepSeek-V4-Pro` |
| Engineer, Architect-planner | **AI/ML API** (hosted frontier) | `AIML_MODEL` (default `gpt-4o-mini`) |
| Documenter | **AI/ML API** (hosted frontier) | `DOCUMENTER_MODEL` (default `gpt-4o`) |

Providers are pure config (`config.provider_for(role)`, override with
`{ROLE}_PROVIDER`), built through `agents/llm.py`. If `AIML_API_KEY` is unset, those
roles fall back to Featherless so the system always runs. Each agent also emits Band
**task-progress events** (`message_type="task"`) per stage, so the coordination state
is visible as a first-class Band primitive — not just chat.

> ⚠️ **Security:** `ENABLE_TEST_EXECUTION` runs LLM/PR-supplied code and
> `ENABLE_AUTO_FIX` mutates the PR branch. Both are **off by default**. Test
> execution is sandboxed (subprocess + temp dir + timeout + scrubbed env) but is
> not a hard boundary — run the agents in a disposable container/VM for untrusted
> PRs.

---

## 🛠️ Local Installation & Setup

### 1. Initialize Virtual Environment & Dependencies

```powershell
# Activate local environment
.\venv\Scripts\activate

# Install package dependencies
pip install -r requirements.txt
```

### 2. Configure Local Environment State (`.env`)

Create a `.env` file in the project root containing your unique configuration keys:

```env
# Band Agent Identities & Platform Authorization (one per agent — 5 total)
ARCHITECT_AGENT_ID="your-architect-uuid"
ARCHITECT_API_KEY="your-architect-key"

REVIEWER_AGENT_ID="your-reviewer-uuid"
REVIEWER_API_KEY="your-reviewer-key"

TESTER_AGENT_ID="your-tester-uuid"
TESTER_API_KEY="your-tester-key"

ENGINEER_AGENT_ID="your-engineer-uuid"
ENGINEER_API_KEY="your-engineer-key"

DOCUMENTER_AGENT_ID="your-documenter-uuid"
DOCUMENTER_API_KEY="your-documenter-key"

# GitHub REST Integration & Webhook Ingestion
GITHUB_TOKEN="your-github-personal-access-token"   # needs repo write scope for auto-fix
GITHUB_WEBHOOK_SECRET="your-chosen-webhook-security-string"

# LLM Gateways (cross-model — see topology table above)
FEATHERLESS_API_KEY="fp_your_featherless_premium_key"   # Reviewer + Tester (DeepSeek)
AIML_API_KEY="your-aiml-key"                            # Engineer + Architect + Documenter

# Reviewer strictness — reasonable (happy path) | strict (forces escalation arc)
REVIEWER_MODE="reasonable"

# Feature flags (default off)
ENABLE_TEST_EXECUTION="0"      # Tester runs real pytest in a sandboxed subprocess
ENABLE_AUTO_FIX="0"            # Engineer pushes fix commits to the PR branch
ENABLE_SELF_COMMENT_GUARD="0"  # ignore the bot's own PR comments (set 1 only when the bot has its own GitHub account)
```

> See [`.env example`](.env%20example) for the full list, including optional model
> and per-role provider overrides.

> The GitHub webhook must also send **Issue comment** events (in addition to
> **Pull requests**) for the bi-directional human-in-the-loop sync to work.

---

## 🚀 Launch Sequence

Spin up the background system processes by opening 7 distinct terminal tabs to isolate your daemon architectures. Ensure your virtual environment is activated in **each** tab:

* **Tab 1 (Public Proxy Bridge):** `ngrok http 5000`
* **Tab 2 (Ingestion Gateway Server):** `python server.py`
* **Tab 3 (Architect Daemon):** `python -m agents.architect`
* **Tab 4 (Reviewer Daemon):** `python -m agents.reviewer`
* **Tab 5 (Tester Daemon):** `python -m agents.tester`
* **Tab 6 (Engineer Daemon):** `python -m agents.engineer`
* **Tab 7 (Documenter Daemon):** `python -m agents.documenter`

---

## 🔬 Execution Verification

To verify full pipeline integrity without a public internet connection, trigger a mock ingestion packet locally:

```powershell
python test_webhook_local.py
```

---

## 🐳 Containerized Run (Docker Compose)

The whole stack — the webhook `server` plus the five agent daemons — runs from a
single image as six services that share your `.env`:

```bash
cp ".env example" .env   # then fill in your credentials
docker compose up -d --build
docker compose logs -f   # follow all six processes
```

Only `server` publishes a port (`5000`); the agents dial **out** to Band over
WebSockets and need no inbound ports. `restart: unless-stopped` keeps the
long-lived daemons alive across transient drops, and a `/health` **healthcheck** plus
a small **`autoheal`** sidecar automatically restart the webhook server if it ever
goes unhealthy (a wedged-but-still-running process won't recover from
`restart: unless-stopped` alone).

### HTTP endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/` | Branded status landing page (the link to share with judges/users). |
| `GET`  | `/health` | JSON health check (`{"status":"ok"}`) — used by the Docker healthcheck. |
| `POST` | `/webhook` | GitHub webhook ingress, verified via `X-Hub-Signature-256`. |

---

## ☁️ Deployment (Google Cloud — Compute Engine VM)

> **Why a VM, not Cloud Run?** The five agents are *long-lived daemons holding
> persistent WebSocket connections to Band*. Request-scaled / scale-to-zero
> platforms (Cloud Run, Lambda) terminate idle instances and would drop those
> connections. A small always-on VM running Docker Compose is the right fit.

### 1. Provision the VM + static IP

```bash
gcloud compute addresses create bandwidth-ip --region=us-central1

gcloud compute instances create bandwidth \
  --zone=us-central1-a \
  --machine-type=e2-small \
  --image-family=debian-12 --image-project=debian-cloud \
  --address=bandwidth-ip \
  --tags=http-server,https-server

# Allow the webhook port (skip if you front it with Caddy/nginx on 443).
gcloud compute firewall-rules create allow-bandwidth-webhook \
  --allow=tcp:5000 --target-tags=http-server --source-ranges=0.0.0.0/0
```

### 2. Install Docker + deploy

```bash
gcloud compute ssh bandwidth --zone=us-central1-a

# On the VM:
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git
sudo usermod -aG docker "$USER" && newgrp docker
git clone https://github.com/Jonathan-Jesni/BandWidth.git && cd BandWidth
cp ".env example" .env && nano .env        # fill in credentials
docker compose up -d --build
```

### 3. Wire the GitHub webhook

In the repo: **Settings → Webhooks → Add webhook**
- **Payload URL:** `http://<STATIC_IP>:5000/webhook`
  (or `https://<domain>/webhook` if you put Caddy/nginx in front for TLS)
- **Content type:** `application/json`
- **Secret:** the same value as `GITHUB_WEBHOOK_SECRET`
- **Events:** select **Pull requests** *and* **Issue comments** (the latter powers
  the bi-directional human-in-the-loop sync).

> For a production-grade endpoint, run a Caddy reverse-proxy container in front of
> `server` to get automatic HTTPS on 443 — GitHub strongly prefers TLS webhooks.

> ⚠️ Because `ENABLE_TEST_EXECUTION` / `ENABLE_AUTO_FIX` execute and push code, treat
> the VM as disposable and scope the `GITHUB_TOKEN` to only the demo repo.
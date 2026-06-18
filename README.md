# BandWidth

BandWidth is an autonomous, multi-agent continuous integration and review pipeline built on the [Band platform](https://app.band.ai). 

When a developer opens or updates a Pull Request on GitHub, a secure webhook payload provisions an isolated collaboration workspace. Inside this space, a swarm of specialized AI agents analyzes code diffs, tracks blockers via typed system events, and prepares documentation or unit tests asynchronously.

![Python](https://img.shields.io/badge/Python-3.x-blue?style=flat&logo=python)
![Flask](https://img.shields.io/badge/Flask-Server-black?style=flat&logo=flask)
![GitHub Webhooks](https://img.shields.io/badge/GitHub-Webhooks-lightgrey?style=flat&logo=github)
![Featherless AI](https://img.shields.io/badge/Featherless_AI-Serverless-purple?style=flat)
![DeepSeek V4](https://img.shields.io/badge/DeepSeek--V4--Pro-1.6T-blue?style=flat)

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
   ├──► 2. Authenticates via BandLink (Architect Credentials)
   ├──► 3. Creates an isolated Band Chatroom
   ├──► 4. Injects Specialized Agents (Reviewer + Tester + Engineer)
   └──► 5. Dispatches Initial Markdown Context (+ embedded source) & Mentions
              │
              ├──► [ Reviewer Agent ] ──► Reviews; routes verdict
              │         ├─ Pass    ──► [ Tester Agent ]   ──► Runs real pytest in a sandbox
              │         └─ Blocker ──► [ Engineer Agent ] ──► Pushes a fix commit to the PR branch
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
# Band Agent Identities & Platform Authorization
ARCHITECT_AGENT_ID="your-architect-uuid"
ARCHITECT_API_KEY="your-architect-key"

REVIEWER_AGENT_ID="your-reviewer-uuid"
REVIEWER_API_KEY="your-reviewer-key"

TESTER_AGENT_ID="your-tester-uuid"
TESTER_API_KEY="your-tester-key"

ENGINEER_AGENT_ID="your-engineer-uuid"
ENGINEER_API_KEY="your-engineer-key"

# GitHub REST Integration & Webhook Ingestion
GITHUB_TOKEN="your-github-personal-access-token"   # needs repo write scope for auto-fix
GITHUB_WEBHOOK_SECRET="your-chosen-webhook-security-string"

# LLM Gateway
FEATHERLESS_API_KEY="fp_your_featherless_premium_key"

# Feature flags (default off)
ENABLE_TEST_EXECUTION="0"   # Tester runs real pytest in a sandboxed subprocess
ENABLE_AUTO_FIX="0"         # Engineer pushes fix commits to the PR branch
```

> The GitHub webhook must also send **Issue comment** events (in addition to
> **Pull requests**) for the bi-directional human-in-the-loop sync to work.

---

## 🚀 Launch Sequence

Spin up the background system processes by opening 6 distinct terminal tabs to isolate your daemon architectures. Ensure your virtual environment is activated in **each** tab:

* **Tab 1 (Public Proxy Bridge):** `ngrok http 5000`
* **Tab 2 (Ingestion Gateway Server):** `python server.py`
* **Tab 3 (Architect Daemon):** `python -m agents.architect`
* **Tab 4 (Reviewer Daemon):** `python -m agents.reviewer`
* **Tab 5 (Tester Daemon):** `python -m agents.tester`
* **Tab 6 (Engineer Daemon):** `python -m agents.engineer`

---

## 🔬 Execution Verification

To verify full pipeline integrity without a public internet connection, trigger a mock ingestion packet locally:

```powershell
python test_webhook_local.py
```
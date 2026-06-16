# BandWidth

BandWidth is an autonomous, multi-agent continuous integration and review pipeline built on the [Band platform](https://app.band.ai). 

When a developer opens or updates a Pull Request on GitHub, a secure webhook payload provisions an isolated collaboration workspace. Inside this space, a swarm of specialized AI agents analyzes code diffs, tracks blockers via typed system events, and prepares documentation or unit tests asynchronously.

![Python](https://img.shields.io/badge/Python-3.x-blue?style=flat&logo=python)
![Flask](https://img.shields.io/badge/Flask-Server-black?style=flat&logo=flask)
![GitHub Webhooks](https://img.shields.io/badge/GitHub-Webhooks-lightgrey?style=flat&logo=github)

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
   ├──► 4. Injects Specialized Agents (Reviewer + Tester)
   └──► 5. Dispatches Initial Markdown Context & Mentions
              │
              ├──► [ Reviewer Agent ] ──► Evaluates code structures
              └──► [ Tester Agent ]   ──► Monitors status & maps tests
```

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

# GitHub REST Integration & Webhook Ingestion Guards
GITHUB_TOKEN="your-github-personal-access-token"
GITHUB_WEBHOOK_SECRET="your-chosen-webhook-security-string"
```

---

## 🚀 Launch Sequence

Spin up the background system processes by opening 5 distinct terminal tabs to isolate your daemon architectures. Ensure your virtual environment is activated in **each** tab:

* **Tab 1 (Public Proxy Bridge):** `ngrok http 5000`
* **Tab 2 (Ingestion Gateway Server):** `python server.py`
* **Tab 3 (Architect Daemon):** `python -m agents.architect`
* **Tab 4 (Reviewer Daemon):** `python -m agents.reviewer`
* **Tab 5 (Tester Daemon):** `python -m agents.tester`

---

## 🔬 Execution Verification

To verify full pipeline integrity without a public internet connection, trigger a mock ingestion packet locally:

```powershell
python test_webhook_local.py
```
"""
Fire a signed GitHub pull_request webhook at the local Flask server.

Edit REPO and PR_NUMBER to point at a real public PR your GITHUB_TOKEN can read,
otherwise _fetch_pr_files will 404.
"""

import hashlib
import hmac
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

REPO = "jonathan-jesni/bandwidth"          # ← change to a real repo + PR you can access
PR_NUMBER = 4

SECRET = os.environ["GITHUB_WEBHOOK_SECRET"].encode()
URL = "http://localhost:5000/webhook"

payload = {
    "action": "opened",
    "repository": {"full_name": REPO},
    "pull_request": {
        "number": PR_NUMBER,
        "title": "Test PR via test_webhook_local.py",
        "body": "Local test — not a real PR.",
        "html_url": f"https://github.com/{REPO}/pull/{PR_NUMBER}",
    },
}

body = json.dumps(payload).encode()
sig = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()

resp = requests.post(
    URL,
    data=body,
    headers={
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": sig,
    },
    timeout=10,
)
print(resp.status_code, resp.text)

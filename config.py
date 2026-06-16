"""Central configuration: loads agent credentials and Band platform URLs from .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Placeholder values shipped in `.env example`. If any of these survive into the
# real environment, the credential was never filled in.
_PLACEHOLDER_FRAGMENTS = ("your-", "uuid", "your-key")

# Band SDK defaults (override only if pointing at a non-prod platform).
BAND_WS_URL = os.getenv("BAND_WS_URL", "wss://app.band.ai/api/v1/socket/websocket")
BAND_REST_URL = os.getenv("BAND_REST_URL", "https://app.band.ai")


def require(name: str) -> str:
    """Return env var `name`, raising a clear error if missing or still a placeholder."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Environment variable {name} is not set. "
            f"Copy '.env example' to '.env' and fill in your Band credentials."
        )
    lowered = value.lower()
    if any(fragment in lowered for fragment in _PLACEHOLDER_FRAGMENTS):
        raise RuntimeError(
            f"Environment variable {name} still holds a placeholder value ({value!r}). "
            f"Fill in the real Band credential in your .env file."
        )
    return value


@dataclass(frozen=True)
class AgentCreds:
    """Credentials for a single Band agent."""

    name: str
    agent_id: str
    api_key: str


def load_creds(prefix: str, name: str) -> AgentCreds:
    """Build AgentCreds from `{PREFIX}_AGENT_ID` / `{PREFIX}_API_KEY` env vars."""
    return AgentCreds(
        name=name,
        agent_id=require(f"{prefix}_AGENT_ID"),
        api_key=require(f"{prefix}_API_KEY"),
    )


# Lazily resolved per-agent so importing this module doesn't force all three
# credentials to be present (each agent process only needs its own).
def architect() -> AgentCreds:
    return load_creds("ARCHITECT", "Architect")


def reviewer() -> AgentCreds:
    return load_creds("REVIEWER", "Reviewer")


def tester() -> AgentCreds:
    return load_creds("TESTER", "Tester")

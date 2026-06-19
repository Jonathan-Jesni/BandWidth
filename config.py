"""Central configuration: loads agent credentials and Band platform URLs from .env."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# Placeholder values shipped in `.env example`. If any of these survive into the
# real environment, the credential was never filled in.
# NOTE: "uuid" is a deliberately loose fragment — a real credential that happens
# to contain the substring "uuid" would be rejected. None of Band's IDs/keys do,
# so this is acceptable; widen with care if that ever changes.
_PLACEHOLDER_FRAGMENTS = ("your-", "uuid", "your-key")

_TRUTHY = {"1", "true", "yes", "on"}

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


def engineer() -> AgentCreds:
    return load_creds("ENGINEER", "Engineer")


def documenter() -> AgentCreds:
    return load_creds("DOCUMENTER", "Documenter")


def github_token() -> str:
    return require("GITHUB_TOKEN")


def webhook_secret() -> str:
    return require("GITHUB_WEBHOOK_SECRET")


def _flag(name: str) -> bool:
    """Read a boolean feature flag from the environment (default: off)."""
    return os.getenv(name, "").strip().lower() in _TRUTHY


def enable_test_execution() -> bool:
    """When true, the Tester runs real pytest in a sandboxed subprocess.

    Off by default: executing test/source code from a PR is arbitrary code
    execution and should be opted into deliberately (ENABLE_TEST_EXECUTION=1).
    """
    return _flag("ENABLE_TEST_EXECUTION")


def enable_auto_fix() -> bool:
    """When true, the Engineer pushes fix commits to the PR branch.

    Off by default: this requires a write-scoped token and mutates the author's
    branch, so it must be opted into deliberately (ENABLE_AUTO_FIX=1).
    """
    return _flag("ENABLE_AUTO_FIX")


def enable_self_comment_guard() -> bool:
    """When true, ignore PR comments authored by the bot's own GitHub login.

    Off by default: in the local demo the human asking questions IS the PAT
    owner, so blocking the PAT owner's comments would break the human-in-the-loop
    flow. Set ENABLE_SELF_COMMENT_GUARD=1 only when the bot posts under its own,
    separate GitHub account.
    """
    return _flag("ENABLE_SELF_COMMENT_GUARD")


# --------------------------------------------------------------------------- #
# LLM providers — BandWidth is a cross-model system: different agents reason on
# different providers, coordinated through Band. Featherless serves open-source
# inference (DeepSeek-V4-Pro); AI/ML API serves a hosted frontier model. Both are
# OpenAI-compatible, so an agent only needs (api_key, base_url, model).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Provider:
    """An OpenAI-compatible inference provider + the default model to use on it."""

    name: str
    api_key: str
    base_url: str
    model: str


def _usable(value: str | None) -> bool:
    """True if an env value is present and not a shipped placeholder."""
    if not value:
        return False
    lowered = value.lower()
    return not any(fragment in lowered for fragment in _PLACEHOLDER_FRAGMENTS)


def featherless_provider() -> Provider:
    return Provider(
        name="featherless",
        api_key=require("FEATHERLESS_API_KEY"),
        base_url="https://api.featherless.ai/v1",
        model=os.getenv("FEATHERLESS_MODEL", "deepseek-ai/DeepSeek-V4-Pro"),
    )


def aiml_provider() -> Provider:
    return Provider(
        name="aimlapi",
        api_key=require("AIML_API_KEY"),
        base_url="https://api.aimlapi.com/v1",
        model=os.getenv("AIML_MODEL", "gpt-4o-mini"),
    )


# Default cross-model topology: open-source reviewers/testers on Featherless,
# frontier engineer/planner on AI/ML API. Override per role with {ROLE}_PROVIDER.
_DEFAULT_PROVIDER = {
    "reviewer": "featherless",
    "tester": "featherless",
    "engineer": "aimlapi",
    "architect": "aimlapi",
    "documenter": "aimlapi",
}


def provider_for(role: str) -> Provider:
    """Return the inference Provider for a role.

    Honors a ``{ROLE}_PROVIDER`` env override, then the default topology. Falls back
    to Featherless (with a warning) if the chosen provider's key isn't configured,
    so the system still runs with a single provider key.

    A ``{ROLE}_MODEL`` override (e.g. ``DOCUMENTER_MODEL=gpt-4o``) lets individual
    roles use a different model than the shared ``AIML_MODEL`` default, without
    changing the provider. Useful for giving the Documenter a smarter model while
    keeping the Engineer on a cheaper one.
    """
    choice = os.getenv(f"{role.upper()}_PROVIDER", _DEFAULT_PROVIDER.get(role, "featherless"))
    choice = choice.strip().lower()
    if choice == "aimlapi" and _usable(os.getenv("AIML_API_KEY")):
        base = aiml_provider()
        role_model = os.getenv(f"{role.upper()}_MODEL", "").strip()
        if role_model:
            log.info("provider_for(%s): using model override %r", role, role_model)
            return Provider(base.name, base.api_key, base.base_url, role_model)
        return base
    if choice == "aimlapi":
        log.warning("provider_for(%s): AIML_API_KEY not configured — using Featherless", role)
    return featherless_provider()

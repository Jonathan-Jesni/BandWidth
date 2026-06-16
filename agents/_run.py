"""Shared entrypoint helper for running a single echo agent."""

from __future__ import annotations

import asyncio
import logging

from band import Agent

import config
from agents.echo_adapter import EchoAdapter


def run_agent(creds: config.AgentCreds) -> None:
    """Start one Band agent with the EchoAdapter and run until interrupted."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    agent = Agent.create(
        adapter=EchoAdapter(),
        agent_id=creds.agent_id,
        api_key=creds.api_key,
        ws_url=config.BAND_WS_URL,
        rest_url=config.BAND_REST_URL,
    )
    logging.getLogger(__name__).info("Launching %s agent...", creds.name)
    asyncio.run(agent.run())

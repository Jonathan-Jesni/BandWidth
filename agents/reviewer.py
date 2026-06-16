"""Reviewer agent entrypoint. Run: python -m agents.reviewer"""

import asyncio
import logging

from band import Agent

import config
from agents.reviewer_adapter import ReviewerAdapter

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    creds = config.reviewer()
    agent = Agent.create(
        adapter=ReviewerAdapter(),
        agent_id=creds.agent_id,
        api_key=creds.api_key,
        ws_url=config.BAND_WS_URL,
        rest_url=config.BAND_REST_URL,
    )
    logging.getLogger(__name__).info("Launching Reviewer agent...")
    asyncio.run(agent.run())

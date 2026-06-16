"""Tester agent entrypoint. Run: python -m agents.tester"""

import asyncio
import logging

from band import Agent

import config
from agents.tester_adapter import TesterAdapter

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    creds = config.tester()
    agent = Agent.create(
        adapter=TesterAdapter(),
        agent_id=creds.agent_id,
        api_key=creds.api_key,
        ws_url=config.BAND_WS_URL,
        rest_url=config.BAND_REST_URL,
    )
    logging.getLogger(__name__).info("Launching Tester agent...")
    asyncio.run(agent.run())

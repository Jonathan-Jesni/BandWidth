"""One-shot: create a Band room as the Architect, add Reviewer + Tester, and
kick off the echo loop with an opening message.

Run this AFTER the three agent processes are up (python -m agents.architect, etc.):

    python bootstrap_room.py
"""

from __future__ import annotations

import asyncio
import logging

from band import AgentTools
from band.platform import BandLink

import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bootstrap")


async def main() -> None:
    architect = config.architect()
    reviewer = config.reviewer()
    tester = config.tester()

    # Connect to the platform as the Architect (REST only — no WebSocket needed
    # for a one-shot bootstrap).
    link = BandLink(
        agent_id=architect.agent_id,
        api_key=architect.api_key,
        ws_url=config.BAND_WS_URL,
        rest_url=config.BAND_REST_URL,
    )
    rest = link.rest

    # 1. Create the room.
    room_id = await AgentTools("", rest, []).create_chatroom()
    log.info("Created room: %s", room_id)

    tools = AgentTools(room_id, rest, [])

    # 2. Add the other two agents by their agent IDs (resolved to participants).
    for creds in (reviewer, tester):
        result = await tools.add_participant(creds.agent_id)
        log.info("Added %s: %s", creds.name, result)

    # 3. Refresh participant cache so we can resolve handles for mentions.
    await tools.get_participants()
    mentions = [
        p.get("handle") or p.get("name")
        for p in tools.participants
        if p.get("id") != architect.agent_id and (p.get("handle") or p.get("name"))
    ]
    log.info("Participants to mention: %s", mentions)

    # Give agents 3 s to complete their initial room sync before the opening
    # message arrives. Without this, agents race to mark the message processed
    # and the slower one gets a 422, causing an infinite resync loop.
    log.info("Waiting 3 s for agents to sync...")
    await asyncio.sleep(3)

    # 4. Kick off the echo loop. Include the word "verdict" to also exercise the
    #    typed-event ("shared state") channel.
    await tools.send_message(
        "Room is live — say hi. (verdict)",
        mentions=mentions,
    )
    log.info("Opening message sent. Watch the room and the agent logs.")


if __name__ == "__main__":
    asyncio.run(main())

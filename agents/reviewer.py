"""Reviewer agent entrypoint. Run: python -m agents.reviewer"""

import config
from agents._run import run_agent

if __name__ == "__main__":
    run_agent(config.reviewer())

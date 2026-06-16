"""Tester agent entrypoint. Run: python -m agents.tester"""

import config
from agents._run import run_agent

if __name__ == "__main__":
    run_agent(config.tester())

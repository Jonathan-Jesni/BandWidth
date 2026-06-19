"""Shared marker constants used by the Documenter and Architect.

Kept in a separate module to avoid circular imports between
``architect_handler`` (which adds agents to rooms) and
``documenter_adapter`` (which imports ``fetch_room_context_as_architect``
from ``architect_handler``).
"""

# The exact prefix the Documenter posts. The Architect waits for this as the
# TRUE pipeline terminal (must not appear in any other agent's output).
DOCUMENTER_DONE_MARKER = "## Final PR Documentation"

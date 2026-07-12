import re

def is_valid_slug(text: str) -> bool:
    """Return True if *text* is a valid URL slug (lowercase, hyphens, no spaces)."""
    pattern = r"^([a-z]+-?)+$"  # BUG: catastrophic backtracking on long non-matching input
    return bool(re.match(pattern, text))

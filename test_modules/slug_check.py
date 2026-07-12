import re

def is_valid_slug(text: str) -> bool:
    """Return True if *text* is a valid URL slug (lowercase, hyphens, no spaces)."""
    pattern = r"^[a-z0-9]+(-[a-z0-9]+)*$"
    return bool(re.match(pattern, text))
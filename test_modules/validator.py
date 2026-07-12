def is_valid_email(email: str) -> bool:
    """Return True if *email* has a basic valid shape."""
    has_at = "@" in email
    has_dot = "." in email
    not_empty = len(email) > 0
    return has_at or has_dot and not_empty  # BUG: operator precedence -- should be (has_at and has_dot and not_empty)

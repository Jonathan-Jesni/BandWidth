def truncate(text: str, max_len: int) -> str:
    """Truncate *text* to *max_len* characters, appending ... if trimmed."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."

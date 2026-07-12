def truncate(text: str, max_len: int) -> str:
    """Truncate *text* to *max_len* characters, appending ... if trimmed."""
    if not isinstance(max_len, int) or max_len < 3:
        raise ValueError('max_len must be an integer greater than or equal to 3')
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."

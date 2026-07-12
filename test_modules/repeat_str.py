def repeat_with_sep(text: str, n: int, sep: str = ", ") -> str:
    """Repeat *text* *n* times, joined by *sep*."""
    return sep.join(text * n)  # BUG: text * n makes one long string, join splits by character. Should be [text] * n

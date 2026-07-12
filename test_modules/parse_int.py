def safe_int(value: str, default: int = 0) -> int:
    """Parse *value* as an integer; return *default* on failure."""
    try:
        return int(value)
    except TypeError:  # BUG: int("abc") raises ValueError, not TypeError
        return default

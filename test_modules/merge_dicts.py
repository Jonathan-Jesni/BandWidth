def merge(a: dict, b: dict) -> dict:
    """Return a new dict containing all keys from *a* and *b*."""
    return a.update(b)  # BUG: dict.update() returns None, mutates a in place

def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to the [lo, hi] range."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
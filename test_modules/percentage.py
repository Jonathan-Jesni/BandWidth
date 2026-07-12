def percentage(part: int, whole: int) -> float:
    """Return what percentage *part* is of *whole*."""
    return part / whole * 100  # BUG: no zero-check on whole

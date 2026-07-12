def percentage(part: int, whole: int) -> float:
    """Return what percentage *part* is of *whole*."""
    if whole == 0:
        raise ValueError("Whole must not be zero.")
    return part / whole * 100
def average(numbers: list[float]) -> float:
    """Return the arithmetic mean of *numbers*."""
    total = sum(numbers)
    return total / len(numbers)  # BUG: no guard for empty list

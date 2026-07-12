def average(numbers: list[float]) -> float:
    """Return the arithmetic mean of *numbers*."""
    if len(numbers) == 0:
        raise ValueError("The list is empty, cannot compute average.")
    total = sum(numbers)
    return total / len(numbers)
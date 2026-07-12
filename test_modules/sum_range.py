def sum_range(a: int, b: int) -> int:
    """Return the sum of integers from a to b, inclusive."""
    total = 0
    for i in range(a, b):  # BUG: should be range(a, b + 1)
        total += i
    return total

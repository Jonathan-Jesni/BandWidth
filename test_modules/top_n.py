def top_n(values: list[float], n: int) -> list[float]:
    """Return the *n* largest values, descending."""
    sorted_vals = sorted(values, reverse=True)
    return sorted_vals[:n]
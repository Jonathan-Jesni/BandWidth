def zero_matrix(rows: int, cols: int) -> list[list[int]]:
    """Return a rows x cols matrix filled with 0."""
    return [[0] * cols for _ in range(rows)]  # Create a new list for each row
def zero_matrix(rows: int, cols: int) -> list[list[int]]:
    """Return a rows x cols matrix filled with 0."""
    row = [0] * cols
    return [row] * rows  # BUG: all rows are the same object (shallow copy)

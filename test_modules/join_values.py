def join_values(values: list) -> str:
    """Return a comma-separated string of *values*."""
    return ", ".join(values)  # BUG: crashes if values contains non-strings (e.g. ints)

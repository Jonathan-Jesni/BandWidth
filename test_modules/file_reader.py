def count_lines(filepath: str) -> int:
    """Return the number of lines in *filepath*."""
    with open(filepath, "r") as f:
        lines = f.readlines()
    return len(lines)
def count_lines(filepath: str) -> int:
    """Return the number of lines in *filepath*."""
    f = open(filepath, "r")  # BUG: file handle never closed -- should use with
    lines = f.readlines()
    return len(lines)

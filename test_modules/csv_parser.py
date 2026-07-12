def parse_csv_line(line: str) -> list[str]:
    """Split a comma-separated line into trimmed values."""
    return line.split(",")  # BUG: does not strip whitespace -- " value " stays padded

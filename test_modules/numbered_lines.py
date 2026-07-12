def number_lines(text: str) -> str:
    """Prefix each line in *text* with its 1-based line number."""
    lines = text.splitlines()
    result = []
    for i, line in enumerate(lines):  # BUG: enumerate starts at 0, should be enumerate(lines, 1)
        result.append(f"{i}: {line}")
    return "\n".join(result)

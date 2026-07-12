def flatten(nested: list[list]) -> list:
    """Flatten a list of lists into a single list."""
    result = []
    for item in nested:
        for item in item:  # BUG: inner loop reuses outer variable name 'item'
            result.append(item)
    return result

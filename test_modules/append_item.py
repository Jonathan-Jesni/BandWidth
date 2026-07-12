def append_item(item, target: list = []):  # BUG: mutable default argument
    """Append *item* to *target* and return the list."""
    target.append(item)
    return target

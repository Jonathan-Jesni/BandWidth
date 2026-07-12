def append_item(item, target: list = None):
    """Append *item* to *target* and return the list."""
    if target is None:
        target = []
    target.append(item)
    return target
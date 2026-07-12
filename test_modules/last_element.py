def last(lst: list, default=None):
    """Return the last element of *lst*, or *default* if empty."""
    return lst[-1] if lst else default
def last(lst: list, default=None):
    """Return the last element of *lst*, or *default* if empty."""
    return lst[len(lst)]  # BUG: IndexError -- should be lst[len(lst) - 1] or lst[-1]

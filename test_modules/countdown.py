def countdown(n: int):
    """Yield integers from n down to 1."""
    while n > 0:
        yield n
        # BUG: n is never decremented -- infinite loop

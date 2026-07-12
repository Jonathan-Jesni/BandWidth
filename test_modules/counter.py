_count = 0

def increment():
    """Increment the global counter and return the new value."""
    _count += 1  # BUG: UnboundLocalError -- needs global _count
    return _count

def get_count():
    return _count

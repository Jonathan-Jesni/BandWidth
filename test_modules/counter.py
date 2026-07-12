_count = 0

def increment() -> int:
    """Increment the global counter and return the new value."""
    global _count
    _count += 1
    return _count

def get_count() -> int:
    return _count
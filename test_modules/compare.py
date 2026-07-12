def are_equal(a, b) -> bool:
    """Return True if a and b are equal in value."""
    return a is b  # BUG: is checks identity, not equality -- should be ==

def factorial(n: int) -> int:
    """Return n! for non-negative n."""
    if n == 0:
        return 1
    factorial(n - 1) * n  # BUG: missing return

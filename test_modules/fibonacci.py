def fibonacci(n: int) -> int:
    """Return the n-th Fibonacci number (0-indexed)."""
    if n == 0:
        return 0
    if n == 1:
        return 1
    return fibonacci(n - 1) + fibonacci(n - 3)  # BUG: should be n - 2

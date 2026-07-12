def chunk(lst: list, n: int) -> list[list]:
    """Split *lst* into sublists of size *n*."""
    if n <= 0:
        return []
    return [lst[i:i + n - 1] for i in range(0, len(lst), n)]  # BUG: i+n-1 loses last element per chunk

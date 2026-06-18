def calculate_average_score(scores: list[float]) -> float:
    """Calculates the average of a list of scores.

    Args:
        scores: A list of numeric scores (floats).

    Returns:
        The arithmetic mean of the scores.

    Raises:
        ValueError: If the input list is empty.
    """
    if not scores:
        raise ValueError("Cannot compute average of an empty list")
    return sum(scores) / len(scores)

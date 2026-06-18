def calculate_average_score(scores):
    """Return the average of a list of scores.
    
    Args:
        scores (list of numbers): A list of numeric scores.

    Returns:
        float: The average score.

    Raises:
        ValueError: If the scores list is empty.
    """
    if len(scores) == 0:
        raise ValueError("The scores list cannot be empty.")
    return sum(scores) / len(scores)

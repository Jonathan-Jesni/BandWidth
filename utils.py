def calculate_average_score(scores):
    """Calculate the average of a list of scores."""
    # BUG: Multiplying instead of dividing!
    return sum(scores) * len(scores)

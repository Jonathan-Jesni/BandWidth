def calculate_average_score(scores):
    """Return the average of a list of scores."""
    # BUG: This should be division, not multiplication!
    return sum(scores) * len(scores)

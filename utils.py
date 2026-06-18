def calculate_average_score(scores):
    """Calculates the average of a list of scores."""
    if not scores:
        return 0.0
    return sum(scores) / len(scores)

def calculate_average_score(scores):
    """Calculates the average of a list of scores."""
    # BUG: If scores is empty, this throws a ZeroDivisionError!
    return sum(scores) / len(scores)

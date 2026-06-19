def calculate_average_score(scores):
    """Return the average of a list of scores."
    if scores is None or not all(isinstance(score, (int, float)) for score in scores):
        raise ValueError('Input must be a list of numeric values.')
    if len(scores) == 0:
        raise ValueError('Cannot calculate average of an empty list.')
    return sum(scores) / len(scores)
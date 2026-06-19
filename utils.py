def calculate_average_score(scores):
    if len(scores) == 0:
        return 0
    return sum(scores) / len(scores)
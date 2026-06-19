def calculate_average_score(scores: list[float]) -> float:
    if not scores:
        return 0.0
    return sum(scores) / len(scores)
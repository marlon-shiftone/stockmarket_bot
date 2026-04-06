import math


def compute_nadaraya_watson_envelope(
    closes: list[float],
    bandwidth: float = 8.0,
    mult: float = 3.0,
) -> tuple[float, float, float]:
    if not closes:
        return 0.0, 0.0, 0.0

    window = min(len(closes), max(20, int(bandwidth * 6)))
    series = closes[-window:]

    weights = []
    for idx, _ in enumerate(series):
        distance = (window - 1) - idx
        weight = math.exp(-(distance * distance) / (2 * bandwidth * bandwidth))
        weights.append(weight)

    total_weight = sum(weights)
    center = sum(v * w for v, w in zip(series, weights)) / total_weight
    variance = sum(w * (v - center) ** 2 for v, w in zip(series, weights)) / total_weight
    deviation = math.sqrt(max(variance, 0.0))

    upper = center + (mult * deviation)
    lower = center - (mult * deviation)
    return center, upper, lower

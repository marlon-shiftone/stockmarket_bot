import math

from core.models.enums import TrendColor


def compute_multi_kernel_regression(
    closes: list[float],
    bandwidth: float = 9.0,
    prev_value: float | None = None,
) -> tuple[float, TrendColor]:
    if not closes:
        return 0.0, TrendColor.NEUTRAL

    window = min(len(closes), max(20, int(bandwidth * 6)))
    series = closes[-window:]

    weights = []
    for idx, _ in enumerate(series):
        distance = (window - 1) - idx
        weight = math.exp(-(abs(distance) / max(bandwidth, 1e-9)))
        weights.append(weight)

    total_weight = sum(weights)
    value = sum(v * w for v, w in zip(series, weights)) / total_weight

    if prev_value is None:
        color = TrendColor.NEUTRAL
    elif value > prev_value:
        color = TrendColor.GREEN
    elif value < prev_value:
        color = TrendColor.RED
    else:
        color = TrendColor.NEUTRAL

    return value, color

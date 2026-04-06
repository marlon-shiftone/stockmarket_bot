def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1)
    ema_values = [values[0]]
    for value in values[1:]:
        ema_values.append((value * alpha) + (ema_values[-1] * (1 - alpha)))
    return ema_values


def compute_trend_meter_macd(closes: list[float]) -> tuple[bool, bool]:
    if len(closes) < 35:
        return False, False

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = [fast - slow for fast, slow in zip(ema12, ema26)]
    signal_line = _ema(macd_line, 9)

    close_ema9 = _ema(closes, 9)
    close_ema21 = _ema(closes, 21)

    dot1_green = macd_line[-1] > signal_line[-1]
    dot2_green = macd_line[-1] > 0
    dot3_green = close_ema9[-1] > close_ema21[-1]

    all_green = dot1_green and dot2_green and dot3_green
    all_red = (not dot1_green) and (not dot2_green) and (not dot3_green)
    return all_green, all_red

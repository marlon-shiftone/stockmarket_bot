def compute_heiken_ashi(
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    prev_ha_open: float | None,
    prev_ha_close: float | None,
) -> tuple[float, float]:
    ha_close = (open_price + high_price + low_price + close_price) / 4.0
    if prev_ha_open is None or prev_ha_close is None:
        ha_open = (open_price + close_price) / 2.0
    else:
        ha_open = (prev_ha_open + prev_ha_close) / 2.0
    return ha_open, ha_close

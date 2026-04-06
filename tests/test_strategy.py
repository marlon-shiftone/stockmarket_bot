from datetime import datetime, timezone

from core.models.candle import Candle
from core.models.enums import PositionSide, SignalType, TrendColor
from core.models.indicator_snapshot import IndicatorSnapshot
from core.models.position import Position
from core.models.strategy_context import StrategyFrame
from strategies.ha_envelope_trend_meter import HAEnvelopeTrendMeterStrategy


def _frame(
    *,
    symbol: str = "PETR4",
    price: float = 10.0,
    ha_open: float,
    ha_close: float,
    nw_upper: float,
    nw_lower: float,
    mkr_color: TrendColor,
    tm_green: bool,
    tm_red: bool,
) -> StrategyFrame:
    candle = Candle(
        symbol=symbol,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=1000,
    )
    indicators = IndicatorSnapshot(
        ha_open=ha_open,
        ha_close=ha_close,
        nw_upper=nw_upper,
        nw_lower=nw_lower,
        mkr_value=price,
        mkr_color=mkr_color,
        trend_meter_all_green=tm_green,
        trend_meter_all_red=tm_red,
    )
    return StrategyFrame(candle=candle, indicators=indicators)


def test_buy_signal_when_all_buy_rules_pass() -> None:
    strategy = HAEnvelopeTrendMeterStrategy()

    previous = _frame(
        ha_open=8,
        ha_close=8.5,
        nw_upper=12,
        nw_lower=9,
        mkr_color=TrendColor.GREEN,
        tm_green=True,
        tm_red=False,
    )
    current = _frame(
        ha_open=7.8,
        ha_close=8.2,
        nw_upper=12,
        nw_lower=9,
        mkr_color=TrendColor.GREEN,
        tm_green=True,
        tm_red=False,
    )

    signal = strategy.generate_signal(current=current, previous=previous, position=None)

    assert signal.signal_type == SignalType.BUY


def test_sell_signal_when_all_sell_rules_pass() -> None:
    strategy = HAEnvelopeTrendMeterStrategy()

    previous = _frame(
        ha_open=13,
        ha_close=13.2,
        nw_upper=12,
        nw_lower=9,
        mkr_color=TrendColor.RED,
        tm_green=False,
        tm_red=True,
    )
    current = _frame(
        ha_open=13.5,
        ha_close=13.7,
        nw_upper=12,
        nw_lower=9,
        mkr_color=TrendColor.RED,
        tm_green=False,
        tm_red=True,
    )

    signal = strategy.generate_signal(current=current, previous=previous, position=None)

    assert signal.signal_type == SignalType.SELL


def test_close_buy_signal_on_mkr_red_with_open_long() -> None:
    strategy = HAEnvelopeTrendMeterStrategy()

    current = _frame(
        ha_open=10,
        ha_close=10,
        nw_upper=12,
        nw_lower=9,
        mkr_color=TrendColor.RED,
        tm_green=False,
        tm_red=True,
    )
    position = Position(
        symbol="PETR4",
        side=PositionSide.LONG,
        qty=1,
        entry_price=9.0,
        entry_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_price=10.0,
    )

    signal = strategy.generate_signal(current=current, previous=None, position=position)

    assert signal.signal_type == SignalType.CLOSE_BUY


def test_sell_signal_with_relaxed_confirmation_and_trend_meter() -> None:
    strategy = HAEnvelopeTrendMeterStrategy(
        require_confirmation=False,
        require_trend_meter=False,
        require_mkr_alignment=True,
    )

    current = _frame(
        ha_open=13.5,
        ha_close=13.7,
        nw_upper=12,
        nw_lower=9,
        mkr_color=TrendColor.RED,
        tm_green=False,
        tm_red=False,
    )

    signal = strategy.generate_signal(current=current, previous=None, position=None)

    assert signal.signal_type == SignalType.SELL


def test_sell_signal_with_body_only_when_all_optional_filters_disabled() -> None:
    strategy = HAEnvelopeTrendMeterStrategy(
        require_confirmation=False,
        require_trend_meter=False,
        require_mkr_alignment=False,
    )

    current = _frame(
        ha_open=13.5,
        ha_close=13.7,
        nw_upper=12,
        nw_lower=9,
        mkr_color=TrendColor.GREEN,
        tm_green=False,
        tm_red=False,
    )

    signal = strategy.generate_signal(current=current, previous=None, position=None)

    assert signal.signal_type == SignalType.SELL

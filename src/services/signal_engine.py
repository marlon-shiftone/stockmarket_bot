from collections import defaultdict

from core.models.candle import Candle
from core.models.signal import Signal
from core.models.strategy_context import StrategyFrame
from core.ports.broker_port import BrokerPort
from indicators.pipeline import IndicatorCalculator
from services.symbol_state import SymbolState
from strategies.ha_envelope_trend_meter import HAEnvelopeTrendMeterStrategy


class SignalEngine:
    def __init__(
        self,
        strategy: HAEnvelopeTrendMeterStrategy,
        indicator_calculator: IndicatorCalculator,
        broker: BrokerPort,
    ) -> None:
        self._strategy = strategy
        self._indicator_calculator = indicator_calculator
        self._broker = broker
        self._states: dict[str, SymbolState] = defaultdict(SymbolState)

    def process_candle(self, candle: Candle) -> Signal:
        state = self._states[candle.symbol]
        state.closes.append(candle.close)

        computation = self._indicator_calculator.compute(
            candle=candle,
            closes=list(state.closes),
            prev_ha_open=state.prev_ha_open,
            prev_ha_close=state.prev_ha_close,
            prev_mkr_value=state.prev_mkr_value,
        )

        current_frame = StrategyFrame(candle=candle, indicators=computation.snapshot)
        position = self._broker.get_position(candle.symbol)

        signal = self._strategy.generate_signal(
            current=current_frame,
            previous=state.prev_frame,
            position=position,
        )

        state.prev_frame = current_frame
        state.prev_ha_open = computation.ha_open
        state.prev_ha_close = computation.ha_close
        state.prev_mkr_value = computation.mkr_value

        return signal

    def reset(self) -> None:
        self._states.clear()

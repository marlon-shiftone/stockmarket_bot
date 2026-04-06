from core.models.enums import SignalType
from core.models.order import Order
from core.models.signal import Signal
from core.ports.broker_port import BrokerPort


class ExecutionEngine:
    def __init__(
        self,
        broker: BrokerPort,
        trading_mode: str = "paper",
        allow_live_trading: bool = False,
    ) -> None:
        allowed_modes = {"paper", "live"}
        if trading_mode not in allowed_modes:
            raise RuntimeError(f"Invalid trading mode: {trading_mode}. Expected one of {allowed_modes}.")
        if trading_mode == "live" and not allow_live_trading:
            raise RuntimeError(
                "Live trading blocked. Set ALLOW_LIVE_TRADING=true and configure a live broker to enable it."
            )
        self._trading_mode = trading_mode
        self._broker = broker

    def execute(self, signal: Signal, qty: float) -> Order | None:
        actionable = {
            SignalType.BUY,
            SignalType.SELL,
            SignalType.CLOSE_BUY,
            SignalType.CLOSE_SELL,
        }
        if signal.signal_type not in actionable:
            return None
        return self._broker.place_order(signal=signal, qty=qty)

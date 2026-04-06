import pytest

from adapters.brokers.paper_broker import PaperBroker
from services.execution_engine import ExecutionEngine


def test_live_mode_requires_allow_flag() -> None:
    with pytest.raises(RuntimeError, match="Live trading blocked"):
        ExecutionEngine(
            broker=PaperBroker(),
            trading_mode="live",
            allow_live_trading=False,
        )


def test_live_mode_allowed_when_flag_is_true() -> None:
    engine = ExecutionEngine(
        broker=PaperBroker(),
        trading_mode="live",
        allow_live_trading=True,
    )
    assert engine is not None

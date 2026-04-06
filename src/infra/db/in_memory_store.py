from core.models.signal import Signal


class InMemoryStore:
    def __init__(self) -> None:
        self._signals: list[Signal] = []

    def add_signal(self, signal: Signal) -> None:
        self._signals.append(signal)

    def list_signals(self) -> list[Signal]:
        return list(self._signals)

    def reset(self) -> None:
        self._signals.clear()

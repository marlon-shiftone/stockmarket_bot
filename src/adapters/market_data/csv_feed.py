import csv
from datetime import datetime

from core.models.candle import Candle
from core.ports.market_data_port import MarketDataPort


class CSVMarketDataAdapter(MarketDataPort):
    def load_candles(self, source: str, symbol: str) -> list[Candle]:
        candles: list[Candle] = []
        with open(source, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_raw = (row.get("timestamp") or row.get("time") or "").strip()
                timestamp = self._parse_timestamp(ts_raw)
                candles.append(
                    Candle(
                        symbol=symbol,
                        timestamp=timestamp,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]) if row.get("volume") not in (None, "") else None,
                    )
                )
        return candles

    def load_candles_with_symbol_fallback(
        self,
        source: str,
        default_symbol: str | None = None,
    ) -> list[Candle]:
        candles: list[Candle] = []
        with open(source, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = (row.get("symbol") or default_symbol or "").strip()
                if not symbol:
                    raise ValueError(
                        "CSV row is missing symbol and no default symbol was provided."
                    )

                ts_raw = (row.get("timestamp") or row.get("time") or "").strip()
                timestamp = self._parse_timestamp(ts_raw)
                candles.append(
                    Candle(
                        symbol=symbol,
                        timestamp=timestamp,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]) if row.get("volume") not in (None, "") else None,
                    )
                )
        return candles

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        if not value:
            raise ValueError("CSV row is missing timestamp/time column")

        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"Invalid timestamp format: {value}") from exc

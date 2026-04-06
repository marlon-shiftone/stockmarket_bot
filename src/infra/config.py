import os
import shlex
import sys
from pathlib import Path

from infra.operational_params import resolve_operational_selection


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_positive_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("Indicator parameters must be positive numbers.")
    return parsed


def _parse_env_value(raw_value: str) -> str:
    tokens = shlex.split(raw_value, comments=True, posix=True)
    if not tokens:
        return ""
    return " ".join(tokens)


def _load_project_dotenv() -> None:
    # Tests control env explicitly; auto-loading the developer's local .env would pollute them.
    if "pytest" in sys.modules:
        return

    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        os.environ.setdefault(key, _parse_env_value(raw_value.strip()))


def _resolve_operational_candidate_from_env():
    operational_path = os.getenv("OPERATIONAL_PARAMS_PATH", "").strip()
    if not operational_path:
        return None

    symbol = os.getenv("SYMBOL", "").strip() or None
    timeframe = (
        os.getenv("ALPACA_BAR_TIMEFRAME", "").strip()
        or os.getenv("TIMEFRAME", "").strip()
        or None
    )
    return resolve_operational_selection(operational_path, symbol=symbol, timeframe=timeframe)


_load_project_dotenv()


class Settings:
    def __init__(self) -> None:
        self.trading_mode = os.getenv("TRADING_MODE", "paper").lower()
        self.default_order_qty = float(os.getenv("DEFAULT_ORDER_QTY", "1.0"))
        self.allow_live_trading = _as_bool(os.getenv("ALLOW_LIVE_TRADING"), default=False)
        self.broker_provider = os.getenv("BROKER_PROVIDER", "paper").lower()
        self.alpaca_api_key = os.getenv("ALPACA_API_KEY", "")
        self.alpaca_api_secret = os.getenv("ALPACA_API_SECRET", "")
        self.alpaca_base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        self.operational_params_path = os.getenv("OPERATIONAL_PARAMS_PATH", "").strip() or None
        self.operational_selection_source: str | None = None
        self.operational_selection_basis: str | None = None
        self.operational_symbol: str | None = None
        self.operational_timeframe: str | None = None

        resolved_operational = _resolve_operational_candidate_from_env()
        candidate = None
        if resolved_operational is not None:
            params_file, selected_dataset = resolved_operational
            candidate = selected_dataset.candidate
            self.operational_selection_source = params_file.selection_source
            self.operational_selection_basis = selected_dataset.selection_basis
            self.operational_symbol = selected_dataset.symbol
            self.operational_timeframe = selected_dataset.timeframe

        self.nw_bandwidth = _as_positive_float(
            str(candidate.nw_bandwidth) if candidate is not None else os.getenv("NW_BANDWIDTH"),
            default=8.0,
        )
        self.nw_mult = _as_positive_float(
            str(candidate.nw_mult) if candidate is not None else os.getenv("NW_MULT"),
            default=3.0,
        )
        self.mkr_bandwidth = _as_positive_float(
            str(candidate.mkr_bandwidth) if candidate is not None else os.getenv("MKR_BANDWIDTH"),
            default=9.0,
        )
        self.require_confirmation = (
            candidate.require_confirmation
            if candidate is not None
            else _as_bool(os.getenv("REQUIRE_CONFIRMATION"), default=True)
        )
        self.require_trend_meter = (
            candidate.require_trend_meter
            if candidate is not None
            else _as_bool(os.getenv("REQUIRE_TREND_METER"), default=True)
        )
        self.require_mkr_alignment = (
            candidate.require_mkr_alignment
            if candidate is not None
            else _as_bool(os.getenv("REQUIRE_MKR_ALIGNMENT"), default=True)
        )

        allowed_modes = {"paper", "live"}
        if self.trading_mode not in allowed_modes:
            raise ValueError(f"TRADING_MODE must be one of {allowed_modes}")

        if self.trading_mode == "paper":
            if self.broker_provider not in {"paper", "alpaca"}:
                raise ValueError("BROKER_PROVIDER must be 'paper' or 'alpaca'")
            if self.broker_provider == "alpaca":
                if not self.alpaca_api_key or not self.alpaca_api_secret:
                    raise ValueError(
                        "ALPACA_API_KEY and ALPACA_API_SECRET are required when "
                        "BROKER_PROVIDER=alpaca, even in paper mode."
                    )
            return

        if not self.allow_live_trading:
            raise ValueError("Live trading blocked. Set ALLOW_LIVE_TRADING=true to enable it.")

        allowed_live_providers = {"alpaca"}
        if self.broker_provider not in allowed_live_providers:
            raise ValueError(f"In live mode, BROKER_PROVIDER must be one of {allowed_live_providers}")

        if self.broker_provider == "alpaca":
            if not self.alpaca_api_key or not self.alpaca_api_secret:
                raise ValueError("ALPACA_API_KEY and ALPACA_API_SECRET are required for Alpaca live mode.")


def get_settings() -> Settings:
    return Settings()

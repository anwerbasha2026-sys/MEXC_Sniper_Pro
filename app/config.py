"""Dependency-free runtime settings used by desktop and Android."""
from __future__ import annotations

import os
from enum import Enum


class TradingMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


class Settings:
    """Attribute-compatible replacement for the former Pydantic Settings model.

    The Android runtime must not require pydantic-settings or pydantic-core.
    Environment overrides are retained for desktop/server deployments.
    """

    def __init__(self) -> None:
        mode = _env_str("TRADING_MODE", "LIVE").upper()
        self.trading_mode = TradingMode(mode if mode in {"LIVE", "PAPER"} else "LIVE")

        self.mexc_api_key = _env_str("MEXC_API_KEY", "")
        self.mexc_api_secret = _env_str("MEXC_API_SECRET", "")
        self.live_trading_enabled = _env_bool("LIVE_TRADING_ENABLED", True)
        self.live_runtime_armed = _env_bool("LIVE_RUNTIME_ARMED", False)
        self.live_trading_confirm = _env_str("LIVE_TRADING_CONFIRM", "")
        self.trading_env = _env_str("TRADING_ENV", "live")
        self.live_order_usdt = _env_float("LIVE_ORDER_USDT", 10.0)
        self.live_hard_max_order_usdt = _env_float("LIVE_HARD_MAX_ORDER_USDT", 100.0)
        self.live_max_open_positions = _env_int("LIVE_MAX_OPEN_POSITIONS", 1)
        self.live_stop_loss_pct = _env_float("LIVE_STOP_LOSS_PCT", 1.5)
        self.live_take_profit_pct = _env_float("LIVE_TAKE_PROFIT_PCT", 3.0)
        self.live_test_symbol = _env_str("LIVE_TEST_SYMBOL", "BTCUSDT")
        self.live_max_slippage_pct = _env_float("LIVE_MAX_SLIPPAGE_PCT", 0.30)
        self.live_max_spread_pct = _env_float("LIVE_MAX_SPREAD_PCT", 0.20)
        self.live_max_entry_drift_pct = _env_float("LIVE_MAX_ENTRY_DRIFT_PCT", 0.30)
        self.live_min_top_ask_coverage_pct = _env_float("LIVE_MIN_TOP_ASK_COVERAGE_PCT", 50.0)

        self.scanner_symbol_limit = _env_int("SCANNER_SYMBOL_LIMIT", 116)
        self.stablecoin_exclusion_enabled = _env_bool("STABLECOIN_EXCLUSION_ENABLED", True)
        self.stablecoin_base_assets = _env_str(
            "STABLECOIN_BASE_ASSETS",
            "USDT,USDC,USDS,USDE,USD1,USDD,DAI,FDUSD,TUSD,BUSD,PYUSD,GUSD,FRAX,LUSD,SUSD,USDP,USTC,UST,CRVUSD,EURC,EURT,EURS,USDX,USDXL",
        )
        self.scanner_score_threshold = _env_float("SCANNER_SCORE_THRESHOLD", 65.0)
        self.scanner_ready_threshold = _env_float("SCANNER_READY_THRESHOLD", 55.0)
        self.scanner_reset_threshold = _env_float("SCANNER_RESET_THRESHOLD", 50.0)
        self.scanner_confirmations = _env_int("SCANNER_CONFIRMATIONS", 1)
        self.scanner_cooldown_seconds = _env_float("SCANNER_COOLDOWN_SECONDS", 20.0)
        self.scanner_stale_after_ms = _env_float("SCANNER_STALE_AFTER_MS", 5000.0)

        self.paper_starting_balance = _env_float("PAPER_STARTING_BALANCE", 1000.0)
        self.paper_order_usdt = _env_float("PAPER_ORDER_USDT", 50.0)
        self.paper_max_open_positions = _env_int("PAPER_MAX_OPEN_POSITIONS", 5)
        self.paper_stop_loss_pct = _env_float("PAPER_STOP_LOSS_PCT", 1.5)
        self.paper_take_profit_pct = _env_float("PAPER_TAKE_PROFIT_PCT", 3.0)
        self.paper_max_spread_pct = _env_float("PAPER_MAX_SPREAD_PCT", 0.40)
        self.paper_max_entry_drift_pct = _env_float("PAPER_MAX_ENTRY_DRIFT_PCT", 0.60)
        self.paper_min_top_ask_coverage_pct = _env_float("PAPER_MIN_TOP_ASK_COVERAGE_PCT", 25.0)

        self.strategy_volume = _env_bool("STRATEGY_VOLUME", True)
        self.strategy_flow = _env_bool("STRATEGY_FLOW", True)
        self.strategy_momentum = _env_bool("STRATEGY_MOMENTUM", True)
        self.strategy_book = _env_bool("STRATEGY_BOOK", True)
        self.strategy_volatility = _env_bool("STRATEGY_VOLATILITY", True)
        self.strategy_liquidity = _env_bool("STRATEGY_LIQUIDITY", True)

        self.telegram_bot_token = _env_str("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = _env_str("TELEGRAM_CHAT_ID", "")
        self.max_risk_per_trade = _env_float("MAX_RISK_PER_TRADE", 0.005)
        self.max_daily_loss = _env_float("MAX_DAILY_LOSS", 0.02)
        self.max_open_positions = _env_int("MAX_OPEN_POSITIONS", 3)


settings = Settings()

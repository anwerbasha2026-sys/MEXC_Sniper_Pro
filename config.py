from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class Settings(BaseSettings):
    trading_mode: TradingMode = TradingMode.LIVE

    mexc_api_key: str = ""
    mexc_api_secret: str = ""

    # Live trading is deliberately fail-closed. The GUI also requires a
    # separate runtime arm before any live order can be sent.
    live_trading_enabled: bool = True
    live_runtime_armed: bool = False
    live_trading_confirm: str = ""
    trading_env: str = "live"
    live_order_usdt: float = 10.0
    live_hard_max_order_usdt: float = 100.0
    live_max_open_positions: int = 1
    live_stop_loss_pct: float = 1.5
    live_take_profit_pct: float = 3.0
    live_test_symbol: str = "BTCUSDT"
    live_max_slippage_pct: float = 0.30
    live_max_spread_pct: float = 0.20
    live_max_entry_drift_pct: float = 0.30
    live_min_top_ask_coverage_pct: float = 50.0

    # Scanner runtime settings.
    scanner_symbol_limit: int = 116
    stablecoin_exclusion_enabled: bool = True
    stablecoin_base_assets: str = "USDT,USDC,USDS,USDE,USD1,USDD,DAI,FDUSD,TUSD,BUSD,PYUSD,GUSD,FRAX,LUSD,SUSD,USDP,USTC,UST,CRVUSD,EURC,EURT,EURS,USDX,USDXL"
    scanner_score_threshold: float = 65.0
    scanner_ready_threshold: float = 55.0
    scanner_reset_threshold: float = 50.0
    scanner_confirmations: int = 1
    scanner_cooldown_seconds: float = 20.0
    scanner_stale_after_ms: float = 5000.0

    # Paper trading settings.
    paper_starting_balance: float = 1000.0
    paper_order_usdt: float = 50.0
    paper_max_open_positions: int = 5
    paper_stop_loss_pct: float = 1.5
    paper_take_profit_pct: float = 3.0
    paper_max_spread_pct: float = 0.40
    paper_max_entry_drift_pct: float = 0.60
    paper_min_top_ask_coverage_pct: float = 25.0

    # Score components.
    strategy_volume: bool = True
    strategy_flow: bool = True
    strategy_momentum: bool = True
    strategy_book: bool = True
    strategy_volatility: bool = True
    strategy_liquidity: bool = True

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    max_risk_per_trade: float = 0.005
    max_daily_loss: float = 0.02
    max_open_positions: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

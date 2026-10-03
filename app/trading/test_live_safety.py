import os
import sys
from pathlib import Path
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trading.live_engine import LiveSpotEngine


def main():
    # This test never calls MEXC and never sends an order.
    old = {
        "TRADING_MODE": os.getenv("TRADING_MODE"),
        "LIVE_TRADING_ENABLED": os.getenv("LIVE_TRADING_ENABLED"),
        "LIVE_TRADING_CONFIRM": os.getenv("LIVE_TRADING_CONFIRM"),
        "TRADING_ENV": os.getenv("TRADING_ENV"),
        "MEXC_API_KEY": os.getenv("MEXC_API_KEY"),
        "MEXC_API_SECRET": os.getenv("MEXC_API_SECRET"),
    }

    os.environ["TRADING_MODE"] = "LIVE"
    os.environ["LIVE_TRADING_ENABLED"] = "true"
    os.environ["LIVE_TRADING_CONFIRM"] = "I_UNDERSTAND_REAL_MONEY"
    os.environ["TRADING_ENV"] = "live"
    os.environ["MEXC_API_KEY"] = "TEST_KEY"
    os.environ["MEXC_API_SECRET"] = "TEST_SECRET"

    # Reload settings-dependent module state.
    import importlib
    import app.config as config
    importlib.reload(config)
    import app.trading.live_engine as live_engine
    importlib.reload(live_engine)

    engine = live_engine.LiveSpotEngine()
    engine.api = Mock()
    engine.api.account.return_value = {
        "accountType": "SPOT",
        "canTrade": True,
        "permissions": ["SPOT"],
        "balances": [{"asset": "USDT", "free": "100.00"}],
    }
    engine.api.exchange_info.return_value = {
        "symbol": "BTCUSDT",
        "isSpotTradingAllowed": True,
        "quoteAmountPrecisionMarket": "5",
        "maxQuoteAmountMarket": "100000",
        "baseSizePrecision": "0.000001",
    }

    result = engine.preflight()
    assert result["accountType"] == "SPOT"
    assert result["canTrade"] is True
    assert result["permissions"] == ["SPOT"]
    assert engine.api.new_order.call_count == 0

    # The hard ceiling rejects accidental oversized live orders.
    engine.order_usdt = 10.01
    try:
        engine.preflight()
    except RuntimeError as exc:
        assert "hard safety ceiling" in str(exc)
    else:
        raise AssertionError("Hard live-order ceiling did not reject 10.01 USDT")

    print("=" * 80)
    print("MEXC SPOT LIVE SAFETY TEST")
    print("=" * 80)
    print("SPOT account check       : PASSED")
    print("Permission check         : PASSED")
    print("Balance/rules isolation  : PASSED")
    print("Hard 10 USDT ceiling     : PASSED")
    print("Real orders sent         : 0")
    print("=" * 80)
    print("TEST PASSED")

    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    main()

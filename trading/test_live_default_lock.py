from __future__ import annotations

from app.config import TradingMode, settings
from app.trading.live_engine import LiveSpotEngine


def test_live_is_locked_without_runtime_arm(monkeypatch):
    monkeypatch.setattr(settings, "trading_mode", TradingMode.LIVE)
    monkeypatch.setattr(settings, "live_trading_enabled", True)
    monkeypatch.setattr(settings, "live_runtime_armed", False)
    monkeypatch.setattr(settings, "live_trading_confirm", LiveSpotEngine.CONFIRMATION)
    monkeypatch.setattr(settings, "trading_env", "live")
    # Credentials are deliberately dummy: the gate must fail before any API call.
    monkeypatch.setattr(settings, "mexc_api_key", "dummy")
    monkeypatch.setattr(settings, "mexc_api_secret", "dummy")

    engine = LiveSpotEngine()
    assert engine.enabled is False

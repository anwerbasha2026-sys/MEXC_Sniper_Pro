from __future__ import annotations

from types import SimpleNamespace

from app.trading.live_engine import LivePosition, LiveSpotEngine


class FakeAPI:
    def __init__(self):
        self.account_payload = {"accountType": "SPOT", "canTrade": True, "permissions": ["SPOT"], "balances": []}
        self.after_sell_payload = self.account_payload

    def account(self):
        return self.after_sell_payload

    def book_ticker(self, symbol):
        return {"bidPrice": "100", "askPrice": "101"}

    def exchange_info(self, symbol):
        return {"symbol": symbol, "isSpotTradingAllowed": True, "baseSizePrecision": "0.0001"}

    def make_client_order_id(self, prefix):
        return prefix + "_TEST"

    def market_sell_quantity(self, symbol, quantity, client_order_id=None, test=False):
        return {"orderId": "SELL-1"}

    def get_order(self, symbol, order_id):
        return {"orderId": order_id, "executedQty": "0.4"}


def engine_for_test() -> LiveSpotEngine:
    engine = LiveSpotEngine.__new__(LiveSpotEngine)
    engine.api = FakeAPI()
    engine.positions = {}
    engine.max_open_positions = 5
    engine.order_usdt = 10.0
    engine.hard_max_order_usdt = 100.0
    return engine


def test_sync_updates_existing_quantity_from_exchange_balance():
    engine = engine_for_test()
    engine.positions["ABCUSDT"] = LivePosition("ABCUSDT", 2.0, 100.0, 0.0, 0.0, "LIVE-1", 0.0, 0.0)
    engine.api.account_payload["balances"] = [{"asset": "ABC", "free": "0.5", "locked": "0.25", "total": "0.75"}]
    engine.sync_account_positions(min_notional_usdt=1.0, account=engine.api.account_payload)
    assert engine.positions["ABCUSDT"].quantity == 0.75


def test_sync_removes_position_when_exchange_balance_is_zero():
    engine = engine_for_test()
    engine.positions["ABCUSDT"] = LivePosition("ABCUSDT", 1.0, 100.0, 0.0, 0.0, "ACCOUNT_SYNC", 0.0, 0.0)
    account = {"accountType": "SPOT", "canTrade": True, "permissions": ["SPOT"], "balances": []}
    engine.sync_account_positions(min_notional_usdt=1.0, account=account)
    assert "ABCUSDT" not in engine.positions


def test_partial_sell_keeps_remaining_position():
    engine = engine_for_test()
    engine.positions["ABCUSDT"] = LivePosition("ABCUSDT", 1.0, 100.0, 0.0, 0.0, "LIVE-1", 0.0, 0.0)
    before = {"accountType": "SPOT", "canTrade": True, "permissions": ["SPOT"], "balances": [{"asset": "ABC", "free": "1", "locked": "0", "total": "1"}]}
    after = {"accountType": "SPOT", "canTrade": True, "permissions": ["SPOT"], "balances": [{"asset": "ABC", "free": "0.6", "locked": "0", "total": "0.6"}]}
    calls = {"n": 0}

    def account():
        calls["n"] += 1
        return before if calls["n"] == 1 else after

    engine.api.account = account
    result = engine.close("ABCUSDT", "MANUAL")
    assert result["remaining_quantity"] == 0.6
    assert engine.positions["ABCUSDT"].quantity == 0.6


def test_sell_does_not_use_locked_quantity():
    engine = engine_for_test()
    engine.positions["ABCUSDT"] = LivePosition("ABCUSDT", 1.0, 100.0, 0.0, 0.0, "ACCOUNT_SYNC", 0.0, 0.0)
    engine.api.account_payload = {
        "accountType": "SPOT", "canTrade": True, "permissions": ["SPOT"],
        "balances": [{"asset": "ABC", "free": "0", "locked": "1", "total": "1"}],
    }
    try:
        engine.close("ABCUSDT", "MANUAL")
    except RuntimeError as exc:
        assert "locked balance" in str(exc)
    else:
        raise AssertionError("Locked quantity must never be submitted for a market sell")

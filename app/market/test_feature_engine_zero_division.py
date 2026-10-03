from app.market.feature_engine import SymbolFeatureEngine


def test_snapshot_with_old_trades_but_no_recent_trades_has_no_zero_division():
    engine = SymbolFeatureEngine()
    engine.add_trade(price=100.0, qty=1.0, is_buy=True, ts=100.0)
    # Snapshot 6 seconds later: the old trade remains in the 120s buffer,
    # but there are zero trades inside the 5-second averaging window.
    snapshot = engine.snapshot(now=106.0)
    assert snapshot.avg_trade_size_5s == 0.0


def test_snapshot_empty_engine_is_safe():
    snapshot = SymbolFeatureEngine().snapshot(now=100.0)
    assert snapshot.avg_trade_size_5s == 0.0
    assert snapshot.ready is False

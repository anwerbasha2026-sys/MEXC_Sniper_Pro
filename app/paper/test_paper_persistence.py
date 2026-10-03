from __future__ import annotations

from app.paper.paper_trader import PaperTrader


def test_paper_state_and_trade_survive_restart(tmp_path):
    db = tmp_path / "paper.db"
    csv_path = tmp_path / "paper_trades.csv"

    first = PaperTrader(
        starting_balance=1000,
        allocation_usdt=50,
        stop_loss_pct=10,
        take_profit_pct=20,
        max_open_positions=5,
        fee_rate=0,
        slippage_pct=0,
        log_path=str(csv_path),
        db_path=str(db),
    )
    first.open_long(symbol="BTCUSDT", price=100, score=90, setup="TEST", now=1000)
    first.update_price("BTCUSDT", 90, now=1001)
    dd_before = first.summary()["max_drawdown_usdt"]
    first.shutdown()

    second = PaperTrader(
        starting_balance=1000,
        allocation_usdt=50,
        stop_loss_pct=10,
        take_profit_pct=20,
        max_open_positions=5,
        fee_rate=0,
        slippage_pct=0,
        log_path=str(csv_path),
        db_path=str(db),
    )
    assert len(second.closed_trades) == 1
    assert second.stats.closed_trades == 1
    assert second.summary()["max_drawdown_usdt"] >= dd_before
    assert second.summary()["net_pnl_usdt"] < 0
    second.shutdown()


def test_open_position_is_restored(tmp_path):
    db = tmp_path / "paper.db"
    csv_path = tmp_path / "paper_trades.csv"

    first = PaperTrader(
        starting_balance=1000, allocation_usdt=50, stop_loss_pct=1.5,
        take_profit_pct=3, max_open_positions=5, fee_rate=0, slippage_pct=0,
        log_path=str(csv_path), db_path=str(db),
    )
    position = first.open_long(symbol="ETHUSDT", price=2000, score=88, setup="BREAKOUT", now=1000)
    assert position is not None
    first.update_price("ETHUSDT", 2010, now=1001)

    second = PaperTrader(
        starting_balance=1000, allocation_usdt=50, stop_loss_pct=1.5,
        take_profit_pct=3, max_open_positions=5, fee_rate=0, slippage_pct=0,
        log_path=str(csv_path), db_path=str(db),
    )
    assert "ETHUSDT" in second.positions
    assert second.positions["ETHUSDT"].entry_price == position.entry_price
    assert second.summary()["open_positions"] == 1

    first.shutdown()
    second.shutdown()

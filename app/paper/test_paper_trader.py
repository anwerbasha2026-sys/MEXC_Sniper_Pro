import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.paper.paper_trader import PaperTrader


def main():
    log_path = (
        PROJECT_ROOT
        / "data"
        / "test_paper_trades.csv"
    )

    if log_path.exists():
        log_path.unlink()

    trader = PaperTrader(
        starting_balance=1000.0,
        allocation_usdt=50.0,
        stop_loss_pct=1.5,
        take_profit_pct=3.0,
        max_open_positions=5,
        fee_rate=0.001,
        slippage_pct=0.05,
        log_path=str(log_path),
    )

    position = trader.open_long(
        symbol="BTCUSDT",
        price=100.0,
        score=88.0,
        setup="BREAKOUT_PRESSURE",
        now=1000.0,
    )

    assert position is not None
    assert position.entry_price > 100.0

    # Trigger TP.
    trade = trader.update_price(
        "BTCUSDT",
        104.0,
        now=1010.0,
    )

    assert trade is not None
    assert trade.reason == "TAKE_PROFIT"
    assert trade.pnl_usdt > 0

    print("=" * 80)
    print("MEXC SPOT PAPER TRADER TEST")
    print("=" * 80)
    print("Entry        :", position.entry_price)
    print("Stop Loss    :", position.stop_loss)
    print("Take Profit  :", position.take_profit)
    print("Exit         :", trade.exit_price)
    print("PnL USDT     :", round(trade.pnl_usdt, 4))
    print("PnL %        :", round(trade.pnl_pct, 4))
    print("-" * 80)
    print("SUMMARY")
    for key, value in trader.summary().items():
        print(f"{key:<20}: {value}")

    # Max DD must use mark-to-market equity, not cash balance.
    trader2 = PaperTrader(
        starting_balance=1000.0, allocation_usdt=50.0,
        stop_loss_pct=10.0, take_profit_pct=20.0, max_open_positions=5,
        fee_rate=0.001, slippage_pct=0.0,
        log_path=str(PROJECT_ROOT / "data" / "test_paper_trades_dd.csv"),
    )
    trader2.open_long(symbol="ETHUSDT", price=100.0, score=90.0, setup="TEST", now=2000.0)
    trader2.update_price("ETHUSDT", 90.0, now=2001.0)
    dd = trader2.summary()["max_drawdown_usdt"]
    assert 4.0 < dd < 6.0, dd
    assert dd < 10.0, "DD must not count the entire cash allocation as a loss"

    print("=" * 80)
    print("TEST PASSED")


if __name__ == "__main__":
    main()

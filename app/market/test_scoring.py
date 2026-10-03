import sys
from pathlib import Path

# Allow direct execution:
# python .\app\market\test_scoring.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import random
import time

from app.market.feature_engine import FeatureBook
from app.market.score_engine import ScoreEngine


def main():
    symbol = "BTCUSDT"

    features = FeatureBook()
    feature_engine = features.for_symbol(symbol)
    scorer = ScoreEngine(strong_threshold=80.0)

    now = time.monotonic()

    price = 84000.0

    # Synthetic smoke test only.
    # This does NOT represent live market data and does NOT place orders.
    for i in range(40):
        ts = now - 10.0 + (i * 0.25)

        price *= 1.0008

        qty = (
            0.01
            if i < 20
            else 0.03 + random.random() * 0.02
        )

        feature_engine.add_trade(
            price=price,
            qty=qty,
            is_buy=True,
            ts=ts,
        )

        feature_engine.add_book(
            bid=price - 0.01,
            ask=price + 0.01,
            bid_qty=2.0,
            ask_qty=0.8,
            ts=ts,
        )

    snapshot = features.snapshot(symbol)
    result = scorer.score(snapshot)

    print("=" * 80)
    print("MEXC SPOT FEATURE / SCORE ENGINE TEST")
    print("=" * 80)
    print(f"Symbol             : {snapshot.symbol}")
    print(f"Ready              : {snapshot.ready}")
    print(f"Price              : {snapshot.price:.8f}")
    print(f"5s Price Change    : {snapshot.price_change_5s_pct:.4f}%")
    print(f"15s Price Change   : {snapshot.price_change_15s_pct:.4f}%")
    print(f"5s Volume          : {snapshot.volume_5s:.2f}")
    print(f"15s Volume         : {snapshot.volume_15s:.2f}")
    print(f"Volume Acceleration: {snapshot.volume_acceleration:.2f}x")
    print(f"Buy Pressure       : {snapshot.buy_pressure_5s:.2%}")
    print(f"Trades 5s          : {snapshot.trades_5s}")
    print(f"Trades 15s         : {snapshot.trades_15s}")
    print(f"Book Imbalance     : {snapshot.book_imbalance:.2%}")
    print(f"Spread             : {snapshot.spread_pct:.5f}%")
    print(f"Volatility 15s     : {snapshot.volatility_15s_pct:.5f}%")
    print("-" * 80)
    print(f"SCORE              : {result.score:.2f}/100")
    print(f"Setup              : {result.setup}")
    print(f"Strong             : {result.strong}")
    print(
        f"Components         : "
        f"V={result.volume_score:.1f} "
        f"F={result.flow_score:.1f} "
        f"M={result.momentum_score:.1f} "
        f"B={result.book_score:.1f} "
        f"Vol={result.volatility_score:.1f} "
        f"L={result.liquidity_score:.1f}"
    )

    if result.reasons:
        print("Reasons            :")

        for reason in result.reasons:
            print(f"  - {reason}")

    print("=" * 80)


if __name__ == "__main__":
    main()

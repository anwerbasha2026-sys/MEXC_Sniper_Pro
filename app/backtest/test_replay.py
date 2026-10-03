import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backtest.replay import ReplayEngine, ReplayEvent


def main():
    events = []
    for i in range(40):
        ts = float(i) * 0.25
        price = 100.0 * (1.0005 ** i)
        events.append(ReplayEvent(
            ts=ts, symbol="BTCUSDT", price=price,
            qty=10.0 if i > 20 else 1.0, is_buy=True,
            bid=price - 0.01, ask=price + 0.01,
            bid_qty=10.0, ask_qty=1.0,
        ))
    result = ReplayEngine(80).run(events)
    assert result.events == 40
    assert result.symbols == 1
    print("REPLAY TEST PASSED")


if __name__ == "__main__":
    main()

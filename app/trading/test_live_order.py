from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trading.live_engine import LiveSpotEngine


SYMBOL = "BTCUSDT"
REAL_CONFIRMATION = "I_UNDERSTAND_REAL_MONEY"


def print_preflight(engine: LiveSpotEngine) -> dict:
    result = engine.preflight()

    print("=" * 80)
    print("MEXC SPOT LIVE ORDER TEST")
    print("=" * 80)
    print(f"Account type: {result['accountType']}")
    print(f"Can trade  : {result['canTrade']}")
    print(f"Permissions: {result['permissions']}")
    print(f"Order size : {result['live_order_usdt']} USDT")
    print(f"Hard cap   : {result['hard_max_order_usdt']} USDT")
    print("=" * 80)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MEXC Spot live-order test. Dry-run by default."
    )
    parser.add_argument(
        "--execute-real",
        action="store_true",
        help="Actually place the configured real Spot BUY.",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Required with --execute-real: {REAL_CONFIRMATION}",
    )
    args = parser.parse_args()

    engine = LiveSpotEngine()

    try:
        preflight = print_preflight(engine)

        if not args.execute_real:
            print()
            print("DRY RUN")
            print("No real order was placed.")
            print()
            print("To explicitly request the real Spot BUY:")
            print(
                "python .\\app\\trading\\test_live_order.py "
                "--execute-real "
                f"--confirm {REAL_CONFIRMATION}"
            )
            return 0

        if args.confirm != REAL_CONFIRMATION:
            print()
            print("REAL ORDER BLOCKED")
            print(f"Required confirmation: {REAL_CONFIRMATION}")
            return 2

        order_size = float(preflight["live_order_usdt"])
        hard_cap = float(preflight["hard_max_order_usdt"])

        if order_size <= 0:
            raise RuntimeError("Configured live order size is invalid.")
        if hard_cap <= 0:
            raise RuntimeError("Configured hard safety ceiling is invalid.")
        if order_size > hard_cap:
            raise RuntimeError("Configured order exceeds hard safety cap.")

        print()
        print("=" * 80)
        print("REAL SPOT ORDER REQUEST")
        print("=" * 80)
        print(f"Symbol      : {SYMBOL}")
        print(f"Order value : {order_size:.2f} USDT")
        print(f"Hard cap    : {hard_cap:.2f} USDT")
        print("Side        : BUY")
        print("Market      : SPOT")
        print("Type        : MARKET")
        print("=" * 80)

        print()
        print("Sending the real Spot BUY through LiveSpotEngine...")
        position = engine.open_long(symbol=SYMBOL, price=1.0, score=0.0)

        if position is None:
            raise RuntimeError(
                "No position was created. The order may have been rejected or the position limit reached."
            )

        print()
        print("=" * 80)
        print("REAL SPOT BUY EXECUTED")
        print("=" * 80)
        print(f"Symbol      : {position.symbol}")
        print(f"Quantity    : {position.quantity}")
        print(f"Entry price : {position.entry_price}")
        print(f"Stop loss   : {position.stop_loss}")
        print(f"Take profit : {position.take_profit}")
        print(f"Order ID    : {position.entry_order_id}")
        print("=" * 80)
        print()
        print("WARNING: SL/TP are monitored by the running process, not exchange-native stop orders.")
        return 0

    except Exception as exc:
        print()
        print("=" * 80)
        print("LIVE ORDER FAILED / BLOCKED")
        print("=" * 80)
        print(type(exc).__name__)
        print(str(exc))
        print("=" * 80)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

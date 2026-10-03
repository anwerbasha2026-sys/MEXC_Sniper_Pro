import sys
from pathlib import Path
import asyncio
import json
import time

import websockets

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = PROJECT_ROOT / "generated"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(GENERATED_DIR))

from generated.PushDataV3ApiWrapper_pb2 import PushDataV3ApiWrapper
from app.market.engine import MarketEngine

WS_URL = "wss://wbs-api.mexc.com/ws"
SYMBOL = "BTCUSDT"
CHANNEL = "spot@public.aggre.deals.v3.api.pb@10ms@BTCUSDT"

async def main():
    print("=" * 80)
    print("MEXC SPOT MARKET ENGINE TEST")
    print("=" * 80)
    print(f"Symbol : {SYMBOL}")
    print(f"Channel: {CHANNEL}")
    print("=" * 80)

    engine = MarketEngine()

    print("Connecting to MEXC...")

    async with websockets.connect(
        WS_URL,
        ping_interval=None,
        max_size=None,
    ) as ws:
        print("WebSocket connected.")

        await ws.send(json.dumps({
            "method": "SUBSCRIPTION",
            "params": [CHANNEL],
        }))

        print("Subscription sent.")
        print("Waiting for Spot market data...")
        print()

        last_print = 0.0

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=25)
            except asyncio.TimeoutError:
                print("Timeout - sending PING...")
                await ws.send(json.dumps({"method": "PING"}))
                continue

            if isinstance(raw, str):
                try:
                    print("MEXC:", json.loads(raw))
                except json.JSONDecodeError:
                    print("MEXC TEXT:", raw)
                continue

            wrapper = PushDataV3ApiWrapper()

            try:
                wrapper.ParseFromString(raw)
            except Exception as exc:
                print("PROTOBUF ERROR:", repr(exc))
                continue

            state = engine.process_wrapper(wrapper)
            if state is None:
                continue

            now = time.time()
            if now - last_print < 1.0:
                continue
            last_print = now

            print("-" * 80)
            print(f"SYMBOL         : {state.symbol}")
            print(f"LAST PRICE     : {state.last_price:.8f}")
            print(f"BUY PRESSURE   : {state.buy_pressure:.2%}")
            print(f"SPREAD         : {state.spread_pct:.6f}%")
            print(f"BOOK IMBALANCE : {state.orderbook_imbalance:.2%}")
            print(f"BUY VOLUME     : {state.buy_volume:.2f} USDT")
            print(f"SELL VOLUME    : {state.sell_volume:.2f} USDT")
            print(f"TOTAL VOLUME   : {state.total_volume:.2f} USDT")
            print(f"TRADES BUFFER  : {len(state.trades)}")
            print("-" * 80)

if __name__ == "__main__":
    print("Starting test_ws.py...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as exc:
        print("=" * 80)
        print("FATAL ERROR")
        print("=" * 80)
        print(repr(exc))
        print("=" * 80)
        raise

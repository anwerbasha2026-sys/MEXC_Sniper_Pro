import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trading.live_engine import LiveSpotEngine


def main():
    engine = LiveSpotEngine()
    if not engine.enabled:
        print("LIVE GATE: DISABLED (safe)")
        print("Set TRADING_MODE=LIVE and the explicit confirmation to enable.")
        return
    print(engine.preflight())
    print("LIVE PREFLIGHT PASSED. No order was placed.")


if __name__ == "__main__":
    main()

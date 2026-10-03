from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULES = [
    "app.market.feature_engine",
    "app.market.score_engine",
    "app.exchange.websocket_manager",
    "app.scanner.live_signal_scanner",
    "app.paper.paper_trader",
    "app.paper.risk_manager",
    "app.backtest.replay",
    "app.dashboard.dashboard",
    "app.trading.live_gate",
]


def main():
    failures = []
    for module in MODULES:
        try:
            importlib.import_module(module)
            print(f"OK  {module}")
        except ModuleNotFoundError as exc:
            if module == "app.exchange.websocket_manager" and "generated" in str(exc):
                print("WARN app.exchange.websocket_manager: generated protobuf modules are not bundled; keep the generated/ directory from your working MEXC build")
                continue
            failures.append((module, repr(exc)))
            print(f"ERR {module}: {exc}")
        except Exception as exc:
            failures.append((module, repr(exc)))
            print(f"ERR {module}: {exc}")

    print("=" * 80)
    if failures:
        print(f"PREFLIGHT FAILED: {len(failures)} module(s)")
        raise SystemExit(1)
    print("PREFLIGHT PASSED")


if __name__ == "__main__":
    main()

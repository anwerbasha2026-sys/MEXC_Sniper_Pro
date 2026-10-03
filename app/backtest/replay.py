from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.market.feature_engine import SymbolFeatureEngine
from app.market.score_engine import ScoreEngine


@dataclass
class ReplayEvent:
    ts: float
    symbol: str
    price: float
    qty: float = 0.0
    is_buy: bool = True
    bid: float = 0.0
    ask: float = 0.0
    bid_qty: float = 0.0
    ask_qty: float = 0.0


@dataclass
class ReplayResult:
    events: int
    symbols: int
    strong_setups: int
    first_strong_events: list[dict]


class ReplayEngine:
    """Deterministic market-data replay for strategy research.

    Input CSV columns:
      ts,symbol,price,qty,is_buy,bid,ask,bid_qty,ask_qty

    No live orders are sent.
    """

    def __init__(self, threshold: float = 80.0):
        self.scorer = ScoreEngine(strong_threshold=threshold)
        self.engines: dict[str, SymbolFeatureEngine] = {}
        self.threshold = threshold

    def run(self, events: Iterable[ReplayEvent]) -> ReplayResult:
        count = 0
        strong = 0
        symbols: set[str] = set()
        first: list[dict] = []
        alerted: set[str] = set()

        for event in events:
            count += 1
            symbol = event.symbol.upper()
            symbols.add(symbol)
            engine = self.engines.setdefault(symbol, SymbolFeatureEngine())

            if event.price > 0 and event.qty > 0:
                engine.add_trade(event.price, event.qty, event.is_buy, event.ts)
            if event.bid > 0 and event.ask > 0:
                engine.add_book(event.bid, event.ask, event.bid_qty, event.ask_qty, event.ts)

            snapshot = engine.snapshot(event.ts)
            snapshot.symbol = symbol
            result = self.scorer.score(snapshot)

            if result.score >= self.threshold:
                strong += 1
                if symbol not in alerted:
                    alerted.add(symbol)
                    first.append({
                        "ts": event.ts,
                        "symbol": symbol,
                        "price": snapshot.price,
                        "score": result.score,
                        "setup": result.setup,
                    })

        return ReplayResult(count, len(symbols), strong, first)


def load_csv(path: Path) -> Iterable[ReplayEvent]:
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield ReplayEvent(
                ts=float(row["ts"]),
                symbol=row["symbol"],
                price=float(row["price"]),
                qty=float(row.get("qty") or 0),
                is_buy=str(row.get("is_buy", "1")).lower() in {"1", "true", "yes", "buy"},
                bid=float(row.get("bid") or 0),
                ask=float(row.get("ask") or 0),
                bid_qty=float(row.get("bid_qty") or 0),
                ask_qty=float(row.get("ask_qty") or 0),
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--threshold", type=float, default=80.0)
    args = parser.parse_args()

    result = ReplayEngine(args.threshold).run(load_csv(args.csv))
    print("=" * 80)
    print("MEXC SPOT REPLAY / BACKTEST")
    print("=" * 80)
    print(f"Events         : {result.events}")
    print(f"Symbols        : {result.symbols}")
    print(f"Strong events  : {result.strong_setups}")
    print("First strong setups:")
    for item in result.first_strong_events:
        print(item)
    print("=" * 80)


if __name__ == "__main__":
    main()

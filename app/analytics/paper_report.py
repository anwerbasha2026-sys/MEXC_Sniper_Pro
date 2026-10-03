from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_trades(path: Path):
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    path = PROJECT_ROOT / "data" / "paper_trades.csv"
    trades = load_trades(path)

    print("=" * 90)
    print("MEXC SPOT PAPER TRADING REPORT")
    print("=" * 90)
    print(f"Journal: {path}")
    print(f"Closed trades: {len(trades)}")

    if not trades:
        print("No closed trades yet.")
        print("Run the live Spot scanner in PAPER mode first.")
        print("=" * 90)
        return

    pnls = [float(t["pnl_usdt"]) for t in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]

    net = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    win_rate = len(wins) / len(pnls) * 100
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf")

    equity = 1000.0
    peak = equity
    max_dd = 0.0

    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0

    by_reason = {}
    by_symbol = {}
    for t in trades:
        reason = t.get("reason", "UNKNOWN")
        symbol = t.get("symbol", "UNKNOWN")
        by_reason[reason] = by_reason.get(reason, 0.0) + float(t["pnl_usdt"])
        by_symbol[symbol] = by_symbol.get(symbol, 0.0) + float(t["pnl_usdt"])

    print(f"Net PnL USDT       : {net:+.4f}")
    print(f"Win rate           : {win_rate:.2f}%")
    print(f"Profit factor      : {'INF' if profit_factor == float('inf') else f'{profit_factor:.3f}'}")
    print(f"Average win        : {avg_win:+.4f}")
    print(f"Average loss       : {-avg_loss:+.4f}")
    print(f"Max drawdown USDT  : {max_dd:.4f}")
    dd_pct = (max_dd / peak * 100.0) if peak > 0 else 0.0
    print(f"Max drawdown %     : {dd_pct:.3f}%")
    print(f"Peak equity        : {peak:.4f}")
    print(f"Ending equity      : {equity:.4f}")

    print("-" * 90)
    print("PnL by exit reason")
    for key, value in sorted(by_reason.items(), key=lambda x: x[1], reverse=True):
        print(f"  {key:<18} {value:+.4f} USDT")

    print("-" * 90)
    print("Top symbols by PnL")
    for key, value in sorted(by_symbol.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {key:<18} {value:+.4f} USDT")

    print("=" * 90)


if __name__ == "__main__":
    main()

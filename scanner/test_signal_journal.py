import csv
from pathlib import Path

from app.scanner.live_signal_scanner import LiveSignalScanner


def test_signal_log_schema_exists(tmp_path):
    scanner = LiveSignalScanner(paper_starting_balance=1000, paper_order_usdt=50)
    scanner.signal_log_path = tmp_path / "signals.csv"
    scanner._ensure_signal_log()
    with scanner.signal_log_path.open("r", newline="", encoding="utf-8") as f:
        fields = next(csv.reader(f))
    assert "symbol" in fields
    assert "paper_action" in fields
    assert "reasons" in fields

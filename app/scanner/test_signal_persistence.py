from __future__ import annotations

from types import SimpleNamespace

from app.scanner.live_signal_scanner import LiveSignalScanner


def test_signal_journal_survives_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scanner = LiveSignalScanner()
    snapshot = SimpleNamespace(
        symbol="BTCUSDT", price=100.0, buy_pressure_5s=0.75,
        price_change_5s_pct=2.0, volume_acceleration=3.0,
        book_imbalance=0.2, spread_pct=0.05,
    )
    result = SimpleNamespace(score=85.0, setup="TEST", reasons=["volume"])
    decision = SimpleNamespace(state=SimpleNamespace(value="TRIGGERED"))
    scanner._record_signal(snapshot, result, decision, "OPENED")
    scanner.close()

    restored = LiveSignalScanner()
    assert len(restored.signal_history) == 1
    assert restored.signal_history[0]["symbol"] == "BTCUSDT"
    assert restored.diagnostics()["signal_history_count"] == 1
    restored.close()

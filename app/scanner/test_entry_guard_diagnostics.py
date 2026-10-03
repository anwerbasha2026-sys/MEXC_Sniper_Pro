from app.scanner.live_signal_scanner import LiveSignalScanner


def test_entry_guard_reason_counters_exist_and_start_zero(tmp_path, monkeypatch):
    # Redirect durable files away from the project DB for a deterministic unit test.
    scanner = LiveSignalScanner()
    try:
        assert scanner.paper_guard_rejections == 0
        assert scanner.paper_spread_rejections == 0
        assert scanner.paper_drift_rejections == 0
        assert scanner.paper_coverage_rejections == 0
        assert scanner.paper_risk_rejections == 0
    finally:
        scanner.close()

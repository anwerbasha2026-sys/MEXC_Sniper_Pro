import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.market.feature_engine import FeatureSnapshot
from app.market.score_engine import ScoreResult
from app.scanner.signal_state import SignalStateMachine


def main():
    machine = SignalStateMachine(
        trigger_threshold=80.0,
        confirmations_required=1,
        cooldown_seconds=20
    )

    snapshot = FeatureSnapshot(
        symbol="BTCUSDT",
        ts=1.0,
        price=84000.0,
        buy_pressure_5s=0.82,
        volume_5s=50000.0,
        volume_acceleration=3.5,
        price_change_5s_pct=0.8,
        book_imbalance=0.55,
        spread_pct=0.05,
        data_age_ms=50.0,
        ready=True,
    )

    result = ScoreResult(
        symbol="BTCUSDT",
        score=88.0,
        volume_score=95.0,
        flow_score=92.0,
        momentum_score=90.0,
        book_score=90.0,
        volatility_score=60.0,
        liquidity_score=90.0,
        setup="BREAKOUT_PRESSURE",
        strong=True,
        reasons=[
            "Volume acceleration",
            "Strong buy pressure",
            "Positive 5s momentum",
            "Bid-side book imbalance",
        ],
    )

    first = machine.update(
        snapshot,
        result,
        now=100.0,
    )

    second = machine.update(
        snapshot,
        result,
        now=101.0,
    )

    print("=" * 80)
    print("SIGNAL STATE MACHINE TEST")
    print("=" * 80)
    print(
        "First update :",
        first.state.value,
        "alert=",
        first.should_alert,
    )
    print(
        "Second update:",
        second.state.value,
        "alert=",
        second.should_alert,
    )
    print("=" * 80)

    assert not first.should_alert
    assert second.should_alert
    print("TEST PASSED")


if __name__ == "__main__":
    main()

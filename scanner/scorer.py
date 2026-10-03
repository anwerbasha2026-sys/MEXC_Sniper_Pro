from dataclasses import dataclass

@dataclass
class ScoreResult:
    score: float
    reasons: list[str]

def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))

def score_state(state):
    # Initial conservative score scaffold.
    # It intentionally does not trigger live orders.
    reasons = []

    pressure = state.buy_pressure * 100.0
    volume_component = min(100.0, state.total_volume / 1000.0)
    imbalance = (state.orderbook_imbalance + 1.0) * 50.0

    score = (
        pressure * 0.35
        + volume_component * 0.35
        + imbalance * 0.30
    )

    score = clamp(score)

    if pressure >= 70:
        reasons.append("strong buy pressure")
    if volume_component >= 70:
        reasons.append("elevated recent volume")
    if state.orderbook_imbalance >= 0.20:
        reasons.append("positive order-book imbalance")

    return ScoreResult(score=score, reasons=reasons)

def format_score_result(symbol, result, threshold=80.0):
    """Return a compact human-readable score line for monitoring."""
    status = "SIGNAL" if result.score >= threshold else "WATCH"
    reasons = ", ".join(result.reasons) if result.reasons else "no strong factors"
    return (
        f"{status} | {symbol} | score={result.score:.1f}/100 | "
        f"{reasons}"
    )

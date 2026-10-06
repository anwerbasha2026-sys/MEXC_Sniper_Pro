from __future__ import annotations

from dataclasses import dataclass, field

from app.market.feature_engine import FeatureSnapshot


@dataclass
class ScoreResult:
    symbol: str
    score: float

    volume_score: float
    flow_score: float
    momentum_score: float
    book_score: float
    volatility_score: float
    liquidity_score: float

    setup: str
    strong: bool

    reasons: list[str] = field(default_factory=list)


class ScoreEngine:
    """Deterministic 0-100 pre-breakout setup score.

    The scanner is deliberately biased toward *early acceleration* rather than
    chasing a candle that has already exploded.  It combines relative volume,
    aggressive buy flow, short-term momentum, top-of-book imbalance, moderate
    volatility and execution liquidity.  Hard anti-chase gates prevent a high
    raw score from becoming a late market buy when spread, stale data or price
    displacement is already excessive.
    """

    def __init__(
        self,
        strong_threshold: float = 80.0,
        enabled_strategies: dict[str, bool] | None = None,
    ):
        self.strong_threshold = float(strong_threshold)
        defaults = {
            "volume": True, "flow": True, "momentum": True,
            "book": True, "volatility": True, "liquidity": True,
        }
        if enabled_strategies:
            defaults.update({k: bool(v) for k, v in enabled_strategies.items() if k in defaults})
        self.enabled_strategies = defaults

    def score(self, snapshot: FeatureSnapshot) -> ScoreResult:
        if not snapshot.ready:
            return ScoreResult(
                symbol=snapshot.symbol, score=0.0,
                volume_score=0.0, flow_score=0.0, momentum_score=0.0,
                book_score=0.0, volatility_score=0.0, liquidity_score=0.0,
                setup="NOT_READY", strong=False,
                reasons=["Insufficient market data"],
            )

        volume = self._volume_score(snapshot)
        flow = self._flow_score(snapshot)
        momentum = self._momentum_score(snapshot)
        book = self._book_score(snapshot)
        volatility = self._volatility_score(snapshot)
        liquidity = self._liquidity_score(snapshot)

        components = {
            "volume": (volume, 0.25),
            "flow": (flow, 0.20),
            "momentum": (momentum, 0.15),
            "book": (book, 0.20),
            "volatility": (volatility, 0.10),
            "liquidity": (liquidity, 0.10),
        }
        active = [(value, weight) for name, (value, weight) in components.items()
                  if self.enabled_strategies.get(name, True)]
        weight_sum = sum(weight for _, weight in active)
        raw_score = sum(value * weight for value, weight in active) / weight_sum if weight_sum else 0.0
        raw_score = max(0.0, min(100.0, raw_score))

        reasons: list[str] = []
        if snapshot.volume_acceleration >= 1.8:
            reasons.append("Relative volume acceleration")
        if snapshot.buy_pressure_5s >= 0.62:
            reasons.append("Aggressive buy flow")
        if 0.10 <= snapshot.price_change_5s_pct <= 0.90:
            reasons.append("Early positive momentum")
        elif snapshot.price_change_5s_pct > 0.90:
            reasons.append("Momentum already extended")
        if snapshot.book_imbalance >= 0.15:
            reasons.append("Bid-side order-book pressure")
        if snapshot.spread_pct <= 0.20:
            reasons.append("Execution spread acceptable")
        if snapshot.trades_1s >= 2 and snapshot.trades_5s > 0:
            burst = snapshot.trades_1s / max(snapshot.trades_5s / 5.0, 1.0)
            if burst >= 1.25:
                reasons.append("Trade-rate burst")

        # Professional pre-breakout gate: a high score alone is not enough.
        # These conditions reject stale, illiquid, excessively wide or already
        # parabolic entries. The cap is below the strong threshold so the state
        # machine cannot fire a LIVE entry on a chased setup.
        gate_reasons: list[str] = []
        if snapshot.data_age_ms > 3000:
            gate_reasons.append("stale market data")
        if snapshot.spread_pct > 0.25:
            gate_reasons.append("spread too wide")
        if snapshot.volume_acceleration < 1.50:
            gate_reasons.append("no relative-volume acceleration")
        if snapshot.buy_pressure_5s < 0.58:
            gate_reasons.append("buy-flow not dominant")
        if snapshot.book_imbalance < 0.05:
            gate_reasons.append("order-book pressure weak")
        if snapshot.price_change_5s_pct < -0.10:
            gate_reasons.append("short-term trend negative")
        if snapshot.price_change_5s_pct > 1.20:
            gate_reasons.append("price already extended")
        if snapshot.price_change_1s_pct > 0.80:
            gate_reasons.append("one-second move already too fast")
        if snapshot.ask_qty <= 0 or snapshot.bid_qty <= 0:
            gate_reasons.append("insufficient top-of-book depth")

        if gate_reasons:
            score = min(raw_score, max(0.0, self.strong_threshold - 0.1))
            reasons.extend(f"Gate: {x}" for x in gate_reasons)
            strong = False
        else:
            score = raw_score
            strong = score >= self.strong_threshold

        setup = self._setup_name(score, snapshot, strong, gate_reasons)
        return ScoreResult(
            symbol=snapshot.symbol,
            score=round(score, 2),
            volume_score=round(volume, 2),
            flow_score=round(flow, 2),
            momentum_score=round(momentum, 2),
            book_score=round(book, 2),
            volatility_score=round(volatility, 2),
            liquidity_score=round(liquidity, 2),
            setup=setup,
            strong=strong,
            reasons=reasons,
        )

    def _volume_score(self, s: FeatureSnapshot) -> float:
        a = s.volume_acceleration
        if a <= 0:
            return 0.0
        if a < 1.0:
            return a * 25.0
        return min(100.0, 25.0 + (a - 1.0) * 30.0)

    def _flow_score(self, s: FeatureSnapshot) -> float:
        return self._clamp(50.0 + (s.buy_pressure_5s - 0.5) * 200.0)

    def _momentum_score(self, s: FeatureSnapshot) -> float:
        p = s.price_change_5s_pct
        # Reward a controlled lift; penalize an already vertical move.
        if p <= 0:
            return 0.0
        if p <= 0.20:
            return 45.0 + p * 100.0
        if p <= 0.80:
            return 65.0 + (p - 0.20) * 50.0
        if p <= 1.20:
            return 95.0 - (p - 0.80) * 50.0
        return max(10.0, 75.0 - (p - 1.20) * 55.0)

    def _book_score(self, s: FeatureSnapshot) -> float:
        return self._clamp(50.0 + s.book_imbalance * 140.0)

    def _volatility_score(self, s: FeatureSnapshot) -> float:
        v = s.volatility_15s_pct
        if v <= 0:
            return 0.0
        if v <= 0.15:
            return 45.0 + v * 180.0
        if v <= 0.60:
            return 72.0 + (v - 0.15) * 45.0
        if v <= 1.00:
            return 92.0 - (v - 0.60) * 70.0
        return max(10.0, 64.0 - (v - 1.00) * 55.0)

    def _liquidity_score(self, s: FeatureSnapshot) -> float:
        if s.volume_5s <= 0:
            return 0.0
        spread_component = max(0.0, 1.0 - min(s.spread_pct / 0.50, 1.0))
        volume_component = min(s.volume_5s / 10000.0, 1.0)
        return spread_component * 70.0 + volume_component * 30.0

    def _setup_name(self, score: float, s: FeatureSnapshot, strong: bool, gate_reasons: list[str]) -> str:
        if gate_reasons:
            if "price already extended" in gate_reasons or "one-second move already too fast" in gate_reasons:
                return "EXTENDED_NO_CHASE"
            return "BUILDING_FILTERED"
        if strong and s.volume_acceleration >= 1.8 and s.buy_pressure_5s >= 0.62:
            return "PRE_BREAKOUT"
        if s.volume_acceleration >= 1.5 and s.buy_pressure_5s >= 0.58:
            return "BUILDING"
        if score >= 50 and s.buy_pressure_5s >= 0.55:
            return "BUY_PRESSURE"
        return "MOMENTUM_WATCH"

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(100.0, value))

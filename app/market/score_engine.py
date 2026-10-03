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
    """
    Deterministic 0-100 setup score.

    This is a signal-generation layer, not financial advice and not an
    order-execution engine. The weights are intentionally explicit so they
    can later be backtested and calibrated.
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

    def score(
        self,
        snapshot: FeatureSnapshot,
    ) -> ScoreResult:
        if not snapshot.ready:
            return ScoreResult(
                symbol=snapshot.symbol,
                score=0.0,
                volume_score=0.0,
                flow_score=0.0,
                momentum_score=0.0,
                book_score=0.0,
                volatility_score=0.0,
                liquidity_score=0.0,
                setup="NOT_READY",
                strong=False,
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
            "momentum": (momentum, 0.20),
            "book": (book, 0.15),
            "volatility": (volatility, 0.10),
            "liquidity": (liquidity, 0.10),
        }
        active = [(value, weight) for name, (value, weight) in components.items()
                  if self.enabled_strategies.get(name, True)]
        weight_sum = sum(weight for _, weight in active)
        score = sum(value * weight for value, weight in active) / weight_sum if weight_sum else 0.0
        score = max(0.0, min(100.0, score))

        reasons = []

        if snapshot.volume_acceleration >= 2.0:
            reasons.append("Volume acceleration")

        if snapshot.buy_pressure_5s >= 0.65:
            reasons.append("Strong buy pressure")

        if snapshot.price_change_5s_pct >= 0.30:
            reasons.append("Positive 5s momentum")

        if snapshot.book_imbalance >= 0.25:
            reasons.append("Bid-side book imbalance")

        if snapshot.spread_pct <= 0.15:
            reasons.append("Tight spread")

        setup = self._setup_name(
            score,
            snapshot,
        )

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
            strong=score >= self.strong_threshold,
            reasons=reasons,
        )

    def _volume_score(
        self,
        s: FeatureSnapshot,
    ) -> float:
        acceleration = s.volume_acceleration

        if acceleration <= 1.0:
            return max(0.0, acceleration * 25.0)

        return min(
            100.0,
            25.0 + (acceleration - 1.0) * 30.0,
        )

    def _flow_score(
        self,
        s: FeatureSnapshot,
    ) -> float:
        # Center 50% = neutral.
        return self._clamp(
            50.0 + (s.buy_pressure_5s - 0.5) * 200.0
        )

    def _momentum_score(
        self,
        s: FeatureSnapshot,
    ) -> float:
        positive = s.price_change_5s_pct

        if positive <= 0:
            return 0.0

        return min(
            100.0,
            positive * 25.0,
        )

    def _book_score(
        self,
        s: FeatureSnapshot,
    ) -> float:
        return self._clamp(
            50.0 + s.book_imbalance * 100.0
        )

    def _volatility_score(
        self,
        s: FeatureSnapshot,
    ) -> float:
        if s.volatility_15s_pct <= 0:
            return 0.0

        # Avoid rewarding extreme noise without limit.
        return min(
            100.0,
            s.volatility_15s_pct * 20.0,
        )

    def _liquidity_score(
        self,
        s: FeatureSnapshot,
    ) -> float:
        if s.volume_5s <= 0:
            return 0.0

        spread_component = max(
            0.0,
            1.0 - min(s.spread_pct / 0.50, 1.0),
        )

        volume_component = min(
            s.volume_5s / 10000.0,
            1.0,
        )

        return (
            spread_component * 70.0
            + volume_component * 30.0
        )

    def _setup_name(
        self,
        score: float,
        s: FeatureSnapshot,
    ) -> str:
        if score < 50:
            return "NO_SETUP"

        if (
            s.volume_acceleration >= 2.0
            and s.buy_pressure_5s >= 0.65
            and s.price_change_5s_pct > 0
        ):
            if score >= self.strong_threshold:
                return "BREAKOUT_PRESSURE"
            return "BUILDING"

        if s.buy_pressure_5s >= 0.60:
            return "BUY_PRESSURE"

        return "MOMENTUM_WATCH"

    @staticmethod
    def _clamp(value: float) -> float:
        return max(
            0.0,
            min(100.0, value),
        )

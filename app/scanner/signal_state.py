from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time

from app.market.feature_engine import FeatureSnapshot
from app.market.score_engine import ScoreResult


class SignalState(str, Enum):
    WATCH = "WATCH"
    BUILDING = "BUILDING"
    READY = "READY"
    TRIGGERED = "TRIGGERED"
    COOLDOWN = "COOLDOWN"


@dataclass
class SignalDecision:
    symbol: str
    previous_state: SignalState
    state: SignalState
    score: float
    should_alert: bool
    reason: str
    reference_price: float = 0.0


@dataclass
class _SymbolSignal:
    state: SignalState = SignalState.WATCH
    confirmations: int = 0
    last_alert_at: float = 0.0
    last_score: float = 0.0
    reference_price: float = 0.0


class SignalStateMachine:
    """
    Prevents repeated alerts for the same setup.

    Flow:
        WATCH -> BUILDING -> READY -> TRIGGERED -> COOLDOWN
                     ^                         |
                     +-------------------------+

    This layer generates alerts only. It never places an order.
    """

    def __init__(
        self,
        *,
        ready_threshold: float = 70.0,
        trigger_threshold: float = 80.0,
        reset_threshold: float = 60.0,
        confirmations_required: int = 2,
        cooldown_seconds: float = 60.0,
        stale_after_ms: float = 3000.0,
    ):
        self.ready_threshold = ready_threshold
        self.trigger_threshold = trigger_threshold
        self.reset_threshold = reset_threshold
        self.confirmations_required = max(
            1,
            int(confirmations_required),
        )
        self.cooldown_seconds = max(
            0.0,
            float(cooldown_seconds),
        )
        self.stale_after_ms = max(
            0.0,
            float(stale_after_ms),
        )

        self._states: dict[str, _SymbolSignal] = {}

    def update(
        self,
        snapshot: FeatureSnapshot,
        result: ScoreResult,
        now: float | None = None,
    ) -> SignalDecision:
        current_time = (
            time.monotonic()
            if now is None
            else now
        )

        symbol = snapshot.symbol.upper()
        memory = self._states.setdefault(
            symbol,
            _SymbolSignal(),
        )

        previous = memory.state
        memory.last_score = result.score
        should_alert = False
        reason = ""

        if (
            not snapshot.ready
            or snapshot.data_age_ms > self.stale_after_ms
        ):
            memory.confirmations = 0

            if memory.state != SignalState.COOLDOWN:
                memory.state = SignalState.WATCH

            return SignalDecision(
                symbol=symbol,
                previous_state=previous,
                state=memory.state,
                score=result.score,
                should_alert=False,
                reason="insufficient or stale data",
                reference_price=memory.reference_price,
            )

        if memory.state == SignalState.COOLDOWN:
            elapsed = current_time - memory.last_alert_at

            if elapsed >= self.cooldown_seconds:
                memory.state = SignalState.WATCH
                memory.confirmations = 0
                memory.reference_price = 0.0
            else:
                if result.score < self.reset_threshold:
                    memory.state = SignalState.COOLDOWN

                return SignalDecision(
                    symbol=symbol,
                    previous_state=previous,
                    state=memory.state,
                    score=result.score,
                    should_alert=False,
                    reason="cooldown",
                    reference_price=memory.reference_price,
                )

        if result.score >= self.trigger_threshold:
            memory.confirmations += 1

            if (
                memory.confirmations
                >= self.confirmations_required
            ):
                memory.state = SignalState.TRIGGERED

                # Alert only on a transition into TRIGGERED.
                if previous != SignalState.TRIGGERED:
                    should_alert = True
                    reason = "strong setup confirmed"

                memory.last_alert_at = current_time
                memory.state = SignalState.COOLDOWN

        elif result.score >= self.ready_threshold:
            memory.confirmations = 0
            memory.state = SignalState.READY
            if memory.reference_price <= 0:
                memory.reference_price = float(snapshot.ask or snapshot.price or 0.0)
            reason = "setup is ready"

        elif result.score >= 50.0:
            memory.confirmations = 0
            memory.state = SignalState.BUILDING
            reason = "setup building"

        else:
            memory.confirmations = 0
            memory.state = SignalState.WATCH
            memory.reference_price = 0.0
            reason = "setup weak"

        return SignalDecision(
            symbol=symbol,
            previous_state=previous,
            state=memory.state,
            score=result.score,
            should_alert=should_alert,
            reason=reason,
            reference_price=memory.reference_price,
        )

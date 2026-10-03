from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    risk_usdt: float
    allocation_usdt: float


class PaperRiskManager:
    """Capital-protection layer for Spot paper trading."""

    def __init__(
        self,
        *,
        max_risk_per_trade_pct: float = 0.50,
        max_daily_loss_pct: float = 2.0,
        max_open_positions: int = 5,
        max_total_exposure_pct: float = 50.0,
        max_position_pct: float = 10.0,
    ):
        self.max_risk_per_trade_pct = max(0.01, float(max_risk_per_trade_pct))
        self.max_daily_loss_pct = max(0.01, float(max_daily_loss_pct))
        self.max_open_positions = max(1, int(max_open_positions))
        self.max_total_exposure_pct = max(1.0, float(max_total_exposure_pct))
        self.max_position_pct = max(1.0, float(max_position_pct))

        self.day = date.today()
        self.daily_realized_pnl = 0.0

    def reset_if_new_day(self):
        today = date.today()
        if today != self.day:
            self.day = today
            self.daily_realized_pnl = 0.0

    def record_closed_pnl(self, pnl_usdt: float):
        self.reset_if_new_day()
        self.daily_realized_pnl += float(pnl_usdt)

    def restore_daily_state(self, daily_pnl: float, risk_day: str):
        """Restore the daily risk budget after a process restart."""
        try:
            restored_day = date.fromisoformat(str(risk_day))
        except (TypeError, ValueError):
            restored_day = date.today()
        self.day = restored_day
        self.daily_realized_pnl = float(daily_pnl)
        self.reset_if_new_day()

    def evaluate(
        self,
        *,
        equity: float,
        open_positions: int,
        current_exposure: float,
        stop_distance_pct: float,
        requested_allocation: float,
    ) -> RiskDecision:
        self.reset_if_new_day()

        equity = max(0.0, float(equity))
        requested_allocation = max(0.0, float(requested_allocation))
        stop_distance_pct = abs(float(stop_distance_pct))

        if equity <= 0:
            return RiskDecision(False, "equity <= 0", 0.0, 0.0)

        if open_positions >= self.max_open_positions:
            return RiskDecision(False, "max open positions reached", 0.0, 0.0)

        daily_limit = equity * self.max_daily_loss_pct / 100.0
        if self.daily_realized_pnl <= -daily_limit:
            return RiskDecision(False, "daily loss limit reached", 0.0, 0.0)

        max_position_value = equity * self.max_position_pct / 100.0
        max_total_exposure = equity * self.max_total_exposure_pct / 100.0

        remaining_exposure = max(0.0, max_total_exposure - current_exposure)
        allocation = min(
            requested_allocation,
            max_position_value,
            remaining_exposure,
        )

        if allocation <= 0:
            return RiskDecision(False, "exposure limit reached", 0.0, 0.0)

        # Approximate monetary risk from stop distance.
        risk_usdt = allocation * stop_distance_pct / 100.0
        max_risk = equity * self.max_risk_per_trade_pct / 100.0

        if risk_usdt > max_risk and stop_distance_pct > 0:
            allocation = max_risk / (stop_distance_pct / 100.0)
            allocation = min(
                allocation,
                requested_allocation,
                max_position_value,
                remaining_exposure,
            )
            risk_usdt = allocation * stop_distance_pct / 100.0

        if allocation <= 0:
            return RiskDecision(False, "risk budget too small", 0.0, 0.0)

        return RiskDecision(
            True,
            "risk checks passed",
            risk_usdt,
            allocation,
        )

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LiveTradingGate:
    """Fail-closed switch for real Spot execution.

    This class deliberately does not submit orders. It is the final safety
    gate that a future exchange adapter must pass before live execution.
    """
    enabled: bool = False
    confirmation: str = ""
    environment: str = "paper"

    @classmethod
    def from_env(cls) -> "LiveTradingGate":
        enabled = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
        confirmation = os.getenv("LIVE_TRADING_CONFIRM", "")
        environment = os.getenv("TRADING_ENV", "paper").lower()
        return cls(enabled, confirmation, environment)

    def authorize(self) -> None:
        if not self.enabled:
            raise RuntimeError("Live trading is disabled (fail-closed).")
        if self.environment != "live":
            raise RuntimeError("TRADING_ENV must be 'live'.")
        if self.confirmation != "I_UNDERSTAND_REAL_MONEY":
            raise RuntimeError("Explicit live-trading confirmation is missing.")
        raise RuntimeError(
            "Live gate passed, but no live order adapter is installed in this build."
        )

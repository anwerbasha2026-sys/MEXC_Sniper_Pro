from __future__ import annotations

from dataclasses import dataclass, asdict
import time


@dataclass
class HealthState:
    websocket_connected: bool = False
    last_market_message: float = 0.0
    symbols_active: int = 0
    last_error: str = ""

    def report(self) -> dict:
        age = None
        if self.last_market_message:
            age = max(0.0, time.monotonic() - self.last_market_message)
        data = asdict(self)
        data["message_age_seconds"] = age
        data["healthy"] = bool(self.websocket_connected and (age is None or age < 10))
        return data

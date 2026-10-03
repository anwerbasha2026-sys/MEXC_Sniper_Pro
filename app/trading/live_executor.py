from __future__ import annotations

from dataclasses import dataclass

from app.trading.live_gate import LiveTradingGate


@dataclass
class OrderIntent:
    symbol: str
    side: str
    quantity: float
    price: float | None = None
    client_order_id: str = ""


class LiveSpotExecutor:
    """Safety boundary for Spot execution.

    This class deliberately delegates execution to LiveSpotEngine, which owns
    the MEXC-specific validation and order lifecycle. No Futures/Leverage API
    is exposed here.
    """

    def __init__(self, gate: LiveTradingGate | None = None):
        self.gate = gate or LiveTradingGate.from_env()

    def authorize(self) -> None:
        self.gate.authorize()

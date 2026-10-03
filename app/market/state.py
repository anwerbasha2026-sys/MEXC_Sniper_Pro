from dataclasses import dataclass, field
from collections import deque
import time


@dataclass
class Trade:

    timestamp: float
    price: float
    quantity: float
    is_buy: bool

    @property
    def value(self):
        return self.price * self.quantity


@dataclass
class MarketState:

    symbol: str

    trades: deque = field(
        default_factory=lambda: deque(
            maxlen=5000
        )
    )

    bid: float = 0.0
    ask: float = 0.0

    bid_quantity: float = 0.0
    ask_quantity: float = 0.0

    last_price: float = 0.0

    def add_trade(
        self,
        price,
        quantity,
        is_buy,
        timestamp=None,
    ):

        if timestamp is None:
            timestamp = time.time()

        trade = Trade(
            timestamp=timestamp,
            price=price,
            quantity=quantity,
            is_buy=is_buy,
        )

        self.trades.append(trade)

        self.last_price = price

        self.cleanup()

    def cleanup(self):

        cutoff = time.time() - 300

        while (
            self.trades
            and self.trades[0].timestamp < cutoff
        ):
            self.trades.popleft()

    @property
    def spread_pct(self):

        if self.bid <= 0:
            return 999

        return (
            (self.ask - self.bid)
            / self.bid
            * 100
        )

    @property
    def orderbook_imbalance(self):

        total = (
            self.bid_quantity
            + self.ask_quantity
        )

        if total <= 0:
            return 0

        return (
            self.bid_quantity
            - self.ask_quantity
        ) / total
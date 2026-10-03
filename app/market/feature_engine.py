from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Optional
import math
import time


@dataclass
class TradePoint:
    ts: float
    price: float
    qty: float
    is_buy: bool

    @property
    def notional(self) -> float:
        return self.price * self.qty


@dataclass
class BookPoint:
    ts: float
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float


@dataclass
class FeatureSnapshot:
    symbol: str
    ts: float

    price: float = 0.0
    price_change_1s_pct: float = 0.0
    price_change_5s_pct: float = 0.0
    price_change_15s_pct: float = 0.0

    volume_1s: float = 0.0
    volume_5s: float = 0.0
    volume_15s: float = 0.0

    volume_acceleration: float = 0.0

    buy_volume_5s: float = 0.0
    sell_volume_5s: float = 0.0
    buy_pressure_5s: float = 0.0

    trades_1s: int = 0
    trades_5s: int = 0
    trades_15s: int = 0

    avg_trade_size_5s: float = 0.0

    bid: float = 0.0
    ask: float = 0.0
    bid_qty: float = 0.0
    ask_qty: float = 0.0
    spread_pct: float = 0.0
    book_imbalance: float = 0.0

    volatility_15s_pct: float = 0.0

    data_age_ms: float = 0.0
    ready: bool = False

    extra: dict = field(default_factory=dict)


class SymbolFeatureEngine:
    """
    Per-symbol rolling feature engine.

    It consumes trade and book updates and produces a compact snapshot
    suitable for scoring. The engine intentionally uses monotonic time
    internally and does not place orders.
    """

    def __init__(
        self,
        *,
        max_trade_age: float = 120.0,
        max_book_age: float = 30.0,
    ):
        self.max_trade_age = max_trade_age
        self.max_book_age = max_book_age

        self.trades: deque[TradePoint] = deque()
        self.books: deque[BookPoint] = deque()

        self.last_snapshot: Optional[FeatureSnapshot] = None

    def add_trade(
        self,
        price: float,
        qty: float,
        is_buy: bool,
        ts: Optional[float] = None,
    ):
        now = time.monotonic() if ts is None else ts

        if price <= 0 or qty <= 0:
            return

        self.trades.append(
            TradePoint(
                ts=now,
                price=price,
                qty=qty,
                is_buy=bool(is_buy),
            )
        )

        self._trim(now)

    def add_book(
        self,
        bid: float,
        ask: float,
        bid_qty: float,
        ask_qty: float,
        ts: Optional[float] = None,
    ):
        now = time.monotonic() if ts is None else ts

        if bid <= 0 or ask <= 0:
            return

        self.books.append(
            BookPoint(
                ts=now,
                bid=bid,
                ask=ask,
                bid_qty=max(0.0, bid_qty),
                ask_qty=max(0.0, ask_qty),
            )
        )

        self._trim(now)

    def snapshot(
        self,
        now: Optional[float] = None,
    ) -> FeatureSnapshot:
        current = time.monotonic() if now is None else now

        self._trim(current)

        latest_trade = self.trades[-1] if self.trades else None
        latest_book = self.books[-1] if self.books else None

        price = (
            latest_trade.price
            if latest_trade
            else (
                (latest_book.bid + latest_book.ask) / 2.0
                if latest_book
                else 0.0
            )
        )

        p1 = self._price_at_or_before(current - 1.0)
        p5 = self._price_at_or_before(current - 5.0)
        p15 = self._price_at_or_before(current - 15.0)

        volume_1s = self._volume(current - 1.0)
        volume_5s = self._volume(current - 5.0)
        volume_15s = self._volume(current - 15.0)

        buy_5, sell_5 = self._buy_sell_volume(
            current - 5.0
        )

        total_5 = buy_5 + sell_5

        buy_pressure = (
            buy_5 / total_5
            if total_5 > 0
            else 0.0
        )

        previous_5s_volume = max(
            volume_15s - volume_5s,
            0.0,
        )

        volume_acceleration = (
            volume_5s / previous_5s_volume
            if previous_5s_volume > 0
            else 0.0
        )

        recent_trade_count = sum(
            1
            for t in self.trades
            if t.ts >= current - 5.0
        )
        avg_trade_size = (
            volume_5s / recent_trade_count
            if recent_trade_count > 0
            else 0.0
        )

        bid = latest_book.bid if latest_book else 0.0
        ask = latest_book.ask if latest_book else 0.0
        bid_qty = latest_book.bid_qty if latest_book else 0.0
        ask_qty = latest_book.ask_qty if latest_book else 0.0

        spread_pct = (
            ((ask - bid) / ((ask + bid) / 2.0)) * 100.0
            if bid > 0 and ask > 0 and ask >= bid
            else 0.0
        )

        book_imbalance = (
            (bid_qty - ask_qty) / (bid_qty + ask_qty)
            if (bid_qty + ask_qty) > 0
            else 0.0
        )

        volatility = self._volatility_15s(
            current
        )

        data_age_ms = self._data_age_ms(
            current
        )

        ready = (
            len(self.trades) >= 3
            and price > 0
            and volume_5s > 0
        )

        snapshot = FeatureSnapshot(
            symbol="",
            ts=current,
            price=price,
            price_change_1s_pct=self._pct_change(
                p1,
                price,
            ),
            price_change_5s_pct=self._pct_change(
                p5,
                price,
            ),
            price_change_15s_pct=self._pct_change(
                p15,
                price,
            ),
            volume_1s=volume_1s,
            volume_5s=volume_5s,
            volume_15s=volume_15s,
            volume_acceleration=volume_acceleration,
            buy_volume_5s=buy_5,
            sell_volume_5s=sell_5,
            buy_pressure_5s=buy_pressure,
            trades_1s=self._count(current - 1.0),
            trades_5s=self._count(current - 5.0),
            trades_15s=self._count(current - 15.0),
            avg_trade_size_5s=avg_trade_size,
            bid=bid,
            ask=ask,
            bid_qty=bid_qty,
            ask_qty=ask_qty,
            spread_pct=spread_pct,
            book_imbalance=book_imbalance,
            volatility_15s_pct=volatility,
            data_age_ms=data_age_ms,
            ready=ready,
        )

        self.last_snapshot = snapshot
        return snapshot

    def _trim(self, now: float):
        cutoff = now - max(
            self.max_trade_age,
            self.max_book_age,
        )

        while self.trades and self.trades[0].ts < cutoff:
            self.trades.popleft()

        book_cutoff = now - self.max_book_age

        while self.books and self.books[0].ts < book_cutoff:
            self.books.popleft()

    def _count(self, since: float) -> int:
        return sum(
            1 for trade in self.trades
            if trade.ts >= since
        )

    def _volume(self, since: float) -> float:
        return sum(
            trade.notional
            for trade in self.trades
            if trade.ts >= since
        )

    def _buy_sell_volume(self, since: float):
        buy = 0.0
        sell = 0.0

        for trade in self.trades:
            if trade.ts < since:
                continue

            if trade.is_buy:
                buy += trade.notional
            else:
                sell += trade.notional

        return buy, sell

    def _price_at_or_before(
        self,
        target: float,
    ) -> Optional[float]:
        result = None

        for trade in self.trades:
            if trade.ts <= target:
                result = trade.price
            else:
                break

        return result

    @staticmethod
    def _pct_change(
        old: Optional[float],
        new: float,
    ) -> float:
        if old is None or old <= 0 or new <= 0:
            return 0.0

        return ((new - old) / old) * 100.0

    def _volatility_15s(
        self,
        now: float,
    ) -> float:
        prices = [
            trade.price
            for trade in self.trades
            if trade.ts >= now - 15.0
        ]

        if len(prices) < 2:
            return 0.0

        returns = []

        for previous, current in zip(
            prices,
            prices[1:],
        ):
            if previous > 0 and current > 0:
                returns.append(
                    math.log(current / previous)
                )

        if len(returns) < 2:
            return 0.0

        mean = sum(returns) / len(returns)

        variance = sum(
            (value - mean) ** 2
            for value in returns
        ) / len(returns)

        return math.sqrt(variance) * 100.0

    def _data_age_ms(
        self,
        now: float,
    ) -> float:
        timestamps = []

        if self.trades:
            timestamps.append(
                self.trades[-1].ts
            )

        if self.books:
            timestamps.append(
                self.books[-1].ts
            )

        if not timestamps:
            return float("inf")

        return max(
            0.0,
            (now - max(timestamps)) * 1000.0,
        )


class FeatureBook:
    """Collection of feature engines keyed by symbol."""

    def __init__(self):
        self.engines: dict[str, SymbolFeatureEngine] = {}

    def for_symbol(
        self,
        symbol: str,
    ) -> SymbolFeatureEngine:
        symbol = str(symbol).upper()

        if symbol not in self.engines:
            self.engines[symbol] = SymbolFeatureEngine()

        return self.engines[symbol]

    def snapshot(
        self,
        symbol: str,
    ) -> FeatureSnapshot:
        result = self.for_symbol(symbol).snapshot()
        result.symbol = str(symbol).upper()
        return result

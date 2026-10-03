import time
from collections import deque
from dataclasses import dataclass, field

@dataclass
class Trade:
    timestamp: float
    price: float
    quantity: float
    trade_type: int
    trade_id: str

    @property
    def value(self):
        return self.price * self.quantity

@dataclass
class SymbolState:
    symbol: str
    trades: deque = field(default_factory=lambda: deque(maxlen=10000))
    bid: float = 0.0
    ask: float = 0.0
    bid_quantity: float = 0.0
    ask_quantity: float = 0.0
    last_price: float = 0.0
    total_volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0

    def add_trade(self, trade):
        self.trades.append(trade)
        self.last_price = trade.price
        self.total_volume += trade.value
        if trade.trade_type == 1:
            self.buy_volume += trade.value
        elif trade.trade_type == 2:
            self.sell_volume += trade.value

    def cleanup(self, seconds=300):
        cutoff = time.time() - seconds
        while self.trades and self.trades[0].timestamp < cutoff:
            old = self.trades.popleft()
            self.total_volume -= old.value
            if old.trade_type == 1:
                self.buy_volume -= old.value
            elif old.trade_type == 2:
                self.sell_volume -= old.value

    @property
    def spread_pct(self):
        if self.bid <= 0 or self.ask <= 0:
            return 0.0
        return (self.ask - self.bid) / self.bid * 100.0

    @property
    def orderbook_imbalance(self):
        total = self.bid_quantity + self.ask_quantity
        if total <= 0:
            return 0.0
        return (self.bid_quantity - self.ask_quantity) / total

    @property
    def buy_pressure(self):
        total = self.buy_volume + self.sell_volume
        if total <= 0:
            return 0.0
        return self.buy_volume / total

class MarketEngine:
    def __init__(self):
        self.states = {}

    def get_state(self, symbol):
        if symbol not in self.states:
            self.states[symbol] = SymbolState(symbol=symbol)
        return self.states[symbol]

    @staticmethod
    def safe_get(obj, field_name, default=None):
        if obj is None:
            return default
        try:
            return getattr(obj, field_name)
        except (AttributeError, KeyError, TypeError):
            return default

    @staticmethod
    def safe_float(value, default=0.0):
        if value is None:
            return default
        try:
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="ignore")
            if str(value).strip() == "":
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    def process_wrapper(self, wrapper):
        symbol = self.safe_get(wrapper, "symbol", "")

        aggre_deals = self.safe_get(wrapper, "publicAggreDeals")
        if not symbol:
            symbol = self.safe_get(aggre_deals, "symbol", "")

        ticker = self.safe_get(wrapper, "publicAggreBookTicker")
        if not symbol:
            symbol = self.safe_get(ticker, "symbol", "")

        if aggre_deals is None:
            return None

        deals = self.safe_get(aggre_deals, "deals", [])
        if not deals:
            return None

        if not symbol:
            symbol = "BTCUSDT"

        state = self.get_state(symbol)

        for deal in deals:
            price = self.safe_float(self.safe_get(deal, "price", ""))
            quantity = self.safe_float(self.safe_get(deal, "quantity", ""))
            trade_type = int(self.safe_float(self.safe_get(deal, "tradeType", 0)))
            timestamp = self.safe_float(self.safe_get(deal, "time", 0)) / 1000.0
            trade_id = self.safe_get(deal, "tradeId", "")

            if price <= 0 or quantity <= 0:
                continue

            if timestamp <= 0:
                timestamp = time.time()

            state.add_trade(Trade(
                timestamp=timestamp,
                price=price,
                quantity=quantity,
                trade_type=trade_type,
                trade_id=str(trade_id),
            ))

        if ticker is not None:
            state.bid = self.safe_float(
                self.safe_get(
                    ticker,
                    "bidPrice",
                    self.safe_get(ticker, "bidprice", None),
                ),
                state.bid,
            )
            state.ask = self.safe_float(
                self.safe_get(
                    ticker,
                    "askPrice",
                    self.safe_get(ticker, "askprice", None),
                ),
                state.ask,
            )
            state.bid_quantity = self.safe_float(
                self.safe_get(
                    ticker,
                    "bidQuantity",
                    self.safe_get(ticker, "bidquantity", None),
                ),
                state.bid_quantity,
            )
            state.ask_quantity = self.safe_float(
                self.safe_get(
                    ticker,
                    "askQuantity",
                    self.safe_get(ticker, "askquantity", None),
                ),
                state.ask_quantity,
            )

        state.cleanup()
        return state

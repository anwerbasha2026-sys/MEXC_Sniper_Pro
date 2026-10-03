from dataclasses import dataclass

@dataclass
class PaperPosition:
    symbol: str
    quantity: float
    entry_price: float

class PaperBroker:
    def __init__(self, balance=10_000.0):
        self.initial_balance = balance
        self.balance = balance
        self.positions = {}

    def buy(self, symbol, quantity, price):
        cost = quantity * price
        if cost > self.balance:
            raise ValueError("Insufficient paper balance")
        self.balance -= cost
        self.positions[symbol] = PaperPosition(
            symbol=symbol,
            quantity=quantity,
            entry_price=price,
        )

    def sell(self, symbol, price):
        position = self.positions.pop(symbol, None)
        if position is None:
            return 0.0
        proceeds = position.quantity * price
        self.balance += proceeds
        return proceeds

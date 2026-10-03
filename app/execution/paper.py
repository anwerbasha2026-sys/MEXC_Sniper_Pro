import uuid

from .base import ExecutionEngine


class PaperExecution(ExecutionEngine):

    def __init__(self, initial_balance: float):
        self.balance = initial_balance
        self.positions = {}

    async def buy(
        self,
        symbol: str,
        quantity: float,
        price: float,
    ):

        cost = quantity * price

        if cost > self.balance:
            raise ValueError(
                "Insufficient paper balance"
            )

        self.balance -= cost

        self.positions[symbol] = {
            "quantity": quantity,
            "entry_price": price,
        }

        return {
            "order_id": f"PAPER-{uuid.uuid4().hex[:12]}",
            "symbol": symbol,
            "side": "BUY",
            "quantity": quantity,
            "price": price,
            "status": "FILLED",
        }

    async def sell(
        self,
        symbol: str,
        quantity: float,
        price: float,
    ):

        position = self.positions.get(symbol)

        if not position:
            raise ValueError(
                f"No position for {symbol}"
            )

        if quantity > position["quantity"]:
            raise ValueError(
                "Quantity exceeds position"
            )

        revenue = quantity * price
        self.balance += revenue

        position["quantity"] -= quantity

        if position["quantity"] <= 0:
            del self.positions[symbol]

        return {
            "order_id": f"PAPER-{uuid.uuid4().hex[:12]}",
            "symbol": symbol,
            "side": "SELL",
            "quantity": quantity,
            "price": price,
            "status": "FILLED",
        }

    async def cancel(self, order_id: str):

        return {
            "order_id": order_id,
            "status": "CANCELLED",
        }
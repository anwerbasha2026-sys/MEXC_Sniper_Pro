from abc import ABC, abstractmethod


class ExecutionEngine(ABC):

    @abstractmethod
    async def buy(
        self,
        symbol: str,
        quantity: float,
    ):
        pass

    @abstractmethod
    async def sell(
        self,
        symbol: str,
        quantity: float,
    ):
        pass

    @abstractmethod
    async def cancel(
        self,
        order_id: str,
    ):
        pass
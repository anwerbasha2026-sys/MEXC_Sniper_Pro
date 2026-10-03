from abc import ABC, abstractmethod


class Exchange(ABC):

    @abstractmethod
    async def get_symbols(self):
        pass

    @abstractmethod
    async def get_ticker(self, symbol: str):
        pass

    @abstractmethod
    async def close(self):
        pass
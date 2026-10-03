from .base import ExecutionEngine


class LiveExecution(ExecutionEngine):

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        enabled: bool,
    ):

        if not enabled:
            raise RuntimeError(
                "LIVE trading is disabled."
            )

        if not api_key or not api_secret:
            raise RuntimeError(
                "MEXC API credentials are missing."
            )

        self.api_key = api_key
        self.api_secret = api_secret

    async def buy(
        self,
        symbol: str,
        quantity: float,
    ):
        raise NotImplementedError(
            "Live order execution will be "
            "implemented after Paper testing."
        )

    async def sell(
        self,
        symbol: str,
        quantity: float,
    ):
        raise NotImplementedError()

    async def cancel(
        self,
        order_id: str,
    ):
        raise NotImplementedError()
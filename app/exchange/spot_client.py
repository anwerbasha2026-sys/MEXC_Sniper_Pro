import httpx


class SpotClient:
    """Small public MEXC Spot REST client used for discovery/market context."""

    BASE_URL = "https://api.mexc.com"

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    async def get_exchange_info(self):
        async with httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=self.timeout,
        ) as client:
            response = await client.get("/api/v3/exchangeInfo")
            response.raise_for_status()
            return response.json()

    async def get_24h_tickers(self):
        async with httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=self.timeout,
        ) as client:
            response = await client.get("/api/v3/ticker/24hr")
            response.raise_for_status()
            return response.json()

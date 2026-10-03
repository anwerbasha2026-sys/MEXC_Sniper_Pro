import aiohttp

from app.exchange.base import Exchange


class MEXCExchange(Exchange):

    BASE_URL = "https://api.mexc.com"

    def __init__(self):
        self.session = aiohttp.ClientSession()

    async def get_symbols(self):

        url = f"{self.BASE_URL}/api/v3/exchangeInfo"

        async with self.session.get(url) as response:
            response.raise_for_status()
            data = await response.json()

        symbols = []

        for item in data.get("symbols", []):

            if (
                item.get("quoteAsset") == "USDT"
                and item.get("status") == "1"
            ):
                symbols.append(item["symbol"])

        return symbols

    async def get_24h_tickers(self):

        url = f"{self.BASE_URL}/api/v3/ticker/24hr"

        async with self.session.get(url) as response:
            response.raise_for_status()
            return await response.json()

    async def get_liquid_usdt_symbols(
        self,
        min_volume: float,
        max_symbols: int,
    ):

        symbols = set(
            await self.get_symbols()
        )

        tickers = await self.get_24h_tickers()

        candidates = []

        for ticker in tickers:

            symbol = ticker.get("symbol")

            if symbol not in symbols:
                continue

            try:
                quote_volume = float(
                    ticker.get("quoteVolume", 0)
                )
            except (TypeError, ValueError):
                continue

            if quote_volume < min_volume:
                continue

            candidates.append(
                (
                    symbol,
                    quote_volume,
                )
            )

        candidates.sort(
            key=lambda x: x[1],
            reverse=True,
        )

        return [
            symbol
            for symbol, _ in candidates[:max_symbols]
        ]

    async def get_ticker(self, symbol: str):

        url = (
            f"{self.BASE_URL}/api/v3/ticker/24hr"
            f"?symbol={symbol}"
        )

        async with self.session.get(url) as response:
            response.raise_for_status()
            return await response.json()

    async def close(self):

        if not self.session.closed:
            await self.session.close()

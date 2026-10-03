from dataclasses import dataclass

from app.exchange.spot_client import SpotClient


@dataclass(frozen=True)
class SpotSymbol:
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    quote_volume_24h: float
    last_price: float


class SymbolDiscovery:
    """
    Discovers active Spot/USDT symbols and ranks them by 24h quote volume.

    Stablecoins are excluded from the scan universe because the sniper is
    intended to detect directional moves in non-stable assets. The exclusion
    is based on the BASE asset, so pairs such as USDCUSDT and FDUSDUSDT are
    ignored before they ever reach the WebSocket scanner.

    The limit is configurable. The default is 116 because that is the
    current target for the sniper scanner.
    """

    # Stablecoins / USD-pegged assets that should never enter the signal
    # scanner. Keep this list conservative: assets such as PAXG are NOT
    # stablecoins and therefore remain eligible.
    STABLECOIN_BASE_ASSETS = frozenset({
        "USDT", "USDC", "USDS", "USDE", "USD1", "USDD",
        "DAI", "FDUSD", "TUSD", "BUSD", "PYUSD", "GUSD",
        "FRAX", "LUSD", "SUSD", "USDP", "USTC", "UST",
        "CRVUSD", "EURC", "EURT", "EURS", "USDX", "USDXL",
    })

    def __init__(
        self,
        client: SpotClient | None = None,
        limit: int = 116,
        stablecoin_exclusion_enabled: bool = True,
        stablecoin_base_assets=None,
    ):
        self.client = client or SpotClient()
        self.limit = limit
        self.stablecoin_exclusion_enabled = bool(stablecoin_exclusion_enabled)
        if stablecoin_base_assets is None:
            self.stablecoin_base_assets = self.STABLECOIN_BASE_ASSETS
        elif isinstance(stablecoin_base_assets, str):
            self.stablecoin_base_assets = frozenset(
                x.strip().upper()
                for x in stablecoin_base_assets.split(",")
                if x.strip()
            )
        else:
            self.stablecoin_base_assets = frozenset(
                str(x).strip().upper()
                for x in stablecoin_base_assets
                if str(x).strip()
            )

    async def discover(self) -> list[SpotSymbol]:
        exchange_info = await self.client.get_exchange_info()
        tickers = await self.client.get_24h_tickers()

        ticker_map = {}
        if isinstance(tickers, list):
            for ticker in tickers:
                symbol = str(ticker.get("symbol", "")).upper()
                if symbol:
                    ticker_map[symbol] = ticker

        results = []

        symbols = exchange_info.get("symbols", [])
        for item in symbols:
            symbol = str(item.get("symbol", "")).upper()
            status = str(item.get("status", "")).upper()
            quote_asset = str(item.get("quoteAsset", "")).upper()
            base_asset = str(item.get("baseAsset", "")).upper()

            if not symbol or quote_asset != "USDT":
                continue

            # Exclude stablecoin base assets before ranking/limiting.
            # This prevents them from consuming one of the scanner slots.
            if self.stablecoin_exclusion_enabled and base_asset in self.stablecoin_base_assets:
                continue

            if status not in {"ENABLED", "1"}:
                continue

            if item.get("isSpotTradingAllowed") is False:
                continue

            ticker = ticker_map.get(symbol, {})
            quote_volume = self._float(
                ticker.get("quoteVolume"),
                default=0.0,
            )
            last_price = self._float(
                ticker.get("lastPrice"),
                default=0.0,
            )

            results.append(
                SpotSymbol(
                    symbol=symbol,
                    base_asset=base_asset,
                    quote_asset=quote_asset,
                    status=status,
                    quote_volume_24h=quote_volume,
                    last_price=last_price,
                )
            )

        results.sort(
            key=lambda item: item.quote_volume_24h,
            reverse=True,
        )

        return results[: self.limit]

    @staticmethod
    def _float(value, default=0.0):
        try:
            if value is None or str(value).strip() == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

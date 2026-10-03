import pytest

from app.exchange.symbol_discovery import SymbolDiscovery


def test_stablecoins_are_excluded_from_spot_universe():
    assert SymbolDiscovery.STABLECOIN_BASE_ASSETS
    assert "USDT" in SymbolDiscovery.STABLECOIN_BASE_ASSETS
    assert "USDC" in SymbolDiscovery.STABLECOIN_BASE_ASSETS
    assert "DAI" in SymbolDiscovery.STABLECOIN_BASE_ASSETS
    assert "FDUSD" in SymbolDiscovery.STABLECOIN_BASE_ASSETS


def test_non_stable_base_asset_is_not_excluded():
    assert "PAXG" not in SymbolDiscovery.STABLECOIN_BASE_ASSETS
    assert "BTC" not in SymbolDiscovery.STABLECOIN_BASE_ASSETS


class FakeClient:
    async def get_exchange_info(self):
        return {
            "symbols": [
                {"symbol": "USDCUSDT", "status": "ENABLED", "quoteAsset": "USDT", "baseAsset": "USDC"},
                {"symbol": "FDUSDUSDT", "status": "ENABLED", "quoteAsset": "USDT", "baseAsset": "FDUSD"},
                {"symbol": "BTCUSDT", "status": "ENABLED", "quoteAsset": "USDT", "baseAsset": "BTC"},
                {"symbol": "PAXGUSDT", "status": "ENABLED", "quoteAsset": "USDT", "baseAsset": "PAXG"},
            ]
        }

    async def get_24h_tickers(self):
        return [
            {"symbol": "USDCUSDT", "quoteVolume": "999999999", "lastPrice": "1"},
            {"symbol": "FDUSDUSDT", "quoteVolume": "999999998", "lastPrice": "1"},
            {"symbol": "BTCUSDT", "quoteVolume": "100", "lastPrice": "100000"},
            {"symbol": "PAXGUSDT", "quoteVolume": "90", "lastPrice": "3000"},
        ]


@pytest.mark.asyncio
async def test_discovery_does_not_let_stablecoins_consume_limit_slots():
    result = await SymbolDiscovery(client=FakeClient(), limit=2).discover()
    assert [item.symbol for item in result] == ["BTCUSDT", "PAXGUSDT"]

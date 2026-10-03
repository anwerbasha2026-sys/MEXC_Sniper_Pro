# MEXC SPOT SNIPER — Stage 20

Stage 20 keeps the Stage 19 stablecoin filtering and makes it fully configurable from the GUI.

## New GUI controls

In **Settings → TRADE / RISK SETTINGS**:

- **Exclude stablecoins from scanner** — enable/disable the filter.
- **Stablecoin base assets** — comma-separated list, editable from the GUI.

Example:

`USDT,USDC,DAI,FDUSD,TUSD,BUSD,USDE,USD1`

The list is matched against the **BASE asset**, so `USDCUSDT` is excluded when USDC is in the list, while `BTCUSDT` remains eligible.

## Applying changes

1. Open the GUI.
2. Go to **Settings**.
3. Change the checkbox/list.
4. Press **SAVE & APPLY**.
5. Stop the engine.
6. Start the engine again.

The settings are written to `.env` and passed into `SymbolDiscovery` before the WebSocket subscriptions are created. Therefore excluded assets do not consume scanner slots or WebSocket channels.

## Safety

Trading remains PAPER by default. LIVE mode remains separately gated and fail-closed.


## Stage 21 follow-up
For corrected Paper Trading Max Drawdown and persistent signal history, use Stage 21.

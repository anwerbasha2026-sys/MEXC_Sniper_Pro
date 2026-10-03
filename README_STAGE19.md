# MEXC Sniper — Stage 19

## What Stage 19 fixes

Stage 18 could show a healthy WebSocket stream while the Diagnostics tab remained at:

- WS messages processed: very high
- Snapshots: 0
- Ready snapshots: 0
- Score >= trigger: 0
- Confirmed alerts: 0

The root problem was in protobuf oneof handling. Reading `publicAggreDeals` and `publicAggreBookTicker` with ordinary attribute access can return empty protobuf sub-messages even when that body was not present on the wire. Stage 19 now determines the active protobuf body with `WhichOneof("body")`, with a channel-name fallback.

The Spot book-ticker body also does not contain its own symbol; Stage 19 correctly uses the wrapper's `symbol` field for book updates.

## New diagnostics

The GUI Diagnostics tab now shows:

- Deals parsed
- Books parsed
- Symbols with market data
- Last protobuf body kind
- Last market-data age
- Invalid deal/book counts
- Existing snapshot / ready / trigger / alert / paper-trade counters

This makes it possible to distinguish:

1. WebSocket connected but protobuf body not parsed.
2. Deals parsed but not enough rolling history yet.
3. Snapshots ready but score below trigger.
4. Confirmed alerts generated but paper risk rejected them.
5. Paper positions opened and later closed.

## Strategy behavior

Stage 19 keeps the Stage 18 score weights and thresholds unchanged. It does not manufacture signals or lower the trigger simply to create trades. The first objective is to make the market-data pipeline observable and correct.

## Run on Windows

From the Stage 19 project directory:

```powershell
python -m pip install -r requirements.txt
copy .env.example .env
python -m app.gui
```

Or run `run_stage19.bat`.

If PowerShell execution policy blocks `run_gui.ps1`, use the `.bat` launcher or `python -m app.gui` directly.

## First validation

1. Start in PAPER mode.
2. Open **Diagnostics**.
3. Within seconds, `Deals parsed` and `Books parsed` should increase.
4. `Symbols with market data` should become non-zero.
5. After enough trade history, `Snapshots` and `Ready snapshots` should increase.
6. If `Ready snapshots` increases but `Score >= trigger` remains zero, the issue is now strategy thresholds rather than WebSocket ingestion.
7. If `Confirmed alerts` increases but `Paper opens` remains zero, inspect `Paper rejects` and the last rejection reason.

No live order is enabled by this Stage. LIVE remains fail-closed and requires the existing explicit gates.


## Stablecoin exclusion hotfix

The Spot discovery layer excludes stablecoin base assets before ranking the 24h volume list. Examples include USDT, USDC, USDS, USDE, USD1, DAI, FDUSD, TUSD, BUSD, PYUSD, GUSD, FRAX, LUSD, sUSD, USDP, USTC, crvUSD and EURC/EURT/EURS. This means stablecoins cannot consume scanner slots or create WebSocket channels. Assets such as BTC and PAXG remain eligible.

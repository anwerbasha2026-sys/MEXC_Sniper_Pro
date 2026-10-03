# MEXC Spot Sniper — Runbook

## Current state

The project is Spot-only and starts in PAPER mode. Stage 19 includes the protobuf oneof ingestion fix and expanded market-data diagnostics. The WebSocket receives public market data; the console dashboard shows the highest current scores every 5 seconds. No live order is sent while `Trading: DISABLED` is shown.

The scanner converts MEXC aggregated deals and book-ticker updates into rolling features, scores them from 0–100, and passes strong candidates through a state machine. The scanner also opens simulated paper positions when a confirmed alert occurs.

## 1. Start

```powershell
cd C:\Users\FRB\Downloads\mexc_sniper_final_fixed_stage19_integrated
python .\app\exchange\run_spot_manager.py
```

Expected startup:

```text
[ENGINE] Building WebSocket manager...
[ENGINE] Starting WebSocket manager NOW...
[WS] Preparing ...
[WS] Started ...
[WS] #1 CONNECTED
...
```

Then every five seconds a dashboard should appear with `WS x/x connected`, message count, ready symbols and the top scores.

## 2. Interpret the dashboard

- `SCORE`: 0–100 strategy score.
- `BUY%`: buy-side share of recent 5-second traded notional.
- `VOL`: recent volume acceleration.
- `MOM%`: 5-second price change.
- `BOOK`: bid/ask quantity imbalance.
- `STATE`: state-machine status.
- `SETUP`: detected setup category.
- A score of 80+ is the configured strong threshold, but the state machine also requires confirmation and cooldown rules.

## 3. Paper trading

Paper trading is the next validation stage. The configured paper account starts at 1000 USDT with 50 USDT nominal allocation, 1.5% stop loss, 3% take profit, maximum 5 open positions and simulated fees/slippage.

Do not treat a short live run as evidence of profitability. Let the paper engine collect a meaningful sample and review the stored trade history and PnL.

## 4. Telegram

If `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured in `.env`, confirmed alerts are sent to Telegram. Otherwise alerts remain in the console.

## 5. Tests before any live consideration

```powershell
python -m pytest -q
python .\app\trading\test_live_safety.py
python .\app\trading\test_live_gate.py
python .\app\trading\test_live_order.py
```

The last test is intended for API validation/preflight and must not be interpreted as a sandbox trading environment.

## 6. Live trading gate

Live execution remains fail-closed. The live engine requires all configured gates, including `LIVE` mode, the explicit live enable flag, the exact confirmation string, and a live environment. It also enforces a hard 10 USDT maximum order size in the current code.

Do not enable live trading until:

1. WebSocket stability is verified.
2. Signal logic is validated with historical/backtest and paper results.
3. Risk limits are reviewed.
4. API key permissions are restricted to Spot trading and withdrawals are disabled.
5. Live execution is enabled deliberately and tested with the smallest permitted amount.

## 7. If the dashboard is blank

Open **Diagnostics**. Stage 19 exposes `Deals parsed`, `Books parsed`, `Symbols with market data`, `Last body kind`, and `Last data age`. If WebSocket connections show `x/x connected` but parsed counts stay at zero, the issue is protobuf/body decoding rather than the market strategy. Stage 19 uses the protobuf `WhichOneof("body")` value with a channel fallback and uses the wrapper symbol for book-ticker messages.

## 8. If a connection drops

The WebSocket manager automatically reconnects with exponential backoff and jitter. A temporary `disconnected/reconnecting` message is not by itself a scanner failure.

# Stage 15 — Advanced GUI

The project now includes a native Windows/Tkinter dashboard. No additional GUI package is required.

## Start the graphical application

PowerShell:

```powershell
cd C:\Users\FRB\Downloads\mexc_sniper_final_fixed_stage19_integrated
.\run_gui.ps1
```

Or double-click `run_gui.bat`.

The GUI starts the same Spot discovery + multi-connection WebSocket + live scanner pipeline used by the CLI. It does **not** enable live orders.

## Dashboard functions

- 9+ WebSocket connection health
- messages/second
- symbols seen and ready-for-analysis counts
- top signal and score
- sortable live signal table by score
- symbol search
- latest signal feed
- selected-symbol feature detail
- live score history chart
- Paper Trading equity / positions / PnL
- explicit `PAPER • NO ORDERS` status
- Start / Stop engine controls

## Project sequence

1. Spot symbol discovery
2. WebSocket market data
3. Feature calculation
4. Score engine
5. Signal state machine
6. Paper Trading
7. GUI monitoring
8. Paper performance collection
9. Backtest/replay validation
10. Only after validation: separate live-trading preflight (still disabled by default)

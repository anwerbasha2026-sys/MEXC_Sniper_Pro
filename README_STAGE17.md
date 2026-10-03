
## Stage 18 hotfix

- Fixed the `Trading mode must be PAPER or LIVE` Settings error caused by the Python `TradingMode` Enum being rendered as `TradingMode.PAPER` instead of `PAPER`.
- GUI now normalizes both Enum and string forms before validation, persistence, and engine startup.
- PAPER remains the safe default.

# MEXC Sniper — Stage 18 Integrated GUI

Stage 17 is based on the latest Stage 15 GUI/shutdown build and fixes the Settings wiring, adds live diagnostics, and makes the GUI the control surface for the scanner and paper engine.

## Fixed / added

- Fixed the Settings-field mapping bug that caused errors such as `Missing GUI setting: paper_starting_balance`.
- Settings are correctly loaded, validated, written to `.env`, and passed to the next engine start.
- GUI controls for API credentials, trading mode, symbol count, order amount, max positions, SL/TP, signal-capture score, confirmations, cooldown, stale-data limit, and all six score components.
- Added a separate `ARM LIVE` control. Saving LIVE settings does not arm orders.
- Added a Diagnostics tab showing message processing, snapshots, ready states, trigger candidates, confirmed alerts, paper opens/rejections/closes, top scores, and the last paper rejection reason.
- WebSocket per-message debug output remains disabled.
- WebSocket shutdown handles expected cancellation cleanly.
- Scanner symbol count is configurable instead of hard-coded to 116.

## Safety

The `.env` file from the working project is intentionally **not** included in this Stage archive. Copy `.env.example` to `.env` and enter your own credentials.

LIVE remains fail-closed and requires:

1. Trading mode = `LIVE`.
2. LIVE gate enabled.
3. Exact confirmation phrase: `I_UNDERSTAND_REAL_MONEY`.
4. Explicit `ARM LIVE` confirmation in the GUI.
5. Successful MEXC Spot account preflight.
6. LIVE order amount <= the hard 10 USDT ceiling in `LiveSpotEngine`.

## First test: PAPER mode

1. Keep Trading mode = `PAPER`.
2. Keep the six strategies enabled.
3. Start with score trigger `80` and confirmations `2`.
4. Start the engine.
5. Open **Diagnostics**.
6. Watch `Score >= trigger`, `Confirmed alerts`, `Paper opens`, and `Paper rejects`.

This makes it possible to distinguish "no qualifying market setup" from "signal generated but paper risk rejected it" without reading the WebSocket message flood.

## Windows

From the project folder:

```powershell
python -m pip install -r requirements.txt
copy .env.example .env
python .\app\gui.py
```

Or double-click `run_gui.bat` / `run_stage17.bat`.

If PowerShell blocks `.ps1`, use the `.bat` launcher or direct Python command above. The `.bat` launcher does not depend on PowerShell execution policy.

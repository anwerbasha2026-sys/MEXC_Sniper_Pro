# MEXC Sniper — Stage 16 Integrated GUI

This version replaces the previous visual-only dashboard with an integrated native Tkinter terminal.

## Data path

MEXC REST discovery -> WebSocket protobuf -> `LiveSignalScanner` -> FeatureBook -> ScoreEngine -> SignalStateMachine -> PaperTrader -> GUI queue.

The GUI does not generate fake market data and does not create a second scanner. It displays the live objects used by the engine.

## GUI sections

- Dashboard: live ranking, selected-symbol detail, score history, WebSocket health, latest signals.
- Signals: complete signal table with reasons and score components.
- Paper Trading: live paper equity, PnL, open positions and closed trades.
- Risk: actual paper risk configuration and statistics.
- Activity: engine, signal and paper-trade events.
- Settings: active pipeline and safety state.

## Safety

Live exchange orders remain locked/disabled. Paper trading is the only execution model used by the scanner.

## Run

```powershell
cd C:\Users\FRB\Downloads\mexc_sniper_final_fixed
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\run_gui.ps1
```

or double-click `run_gui.bat`.

Install dependencies first if required:

```powershell
python -m pip install -r requirements.txt
```


## GUI Settings Control (integrated)
The Settings tab now controls the scanner/paper engine from the same application:
- MEXC API key/secret are editable and persisted to `.env`.
- Paper order amount, maximum open positions, stop loss and take profit.
- Signal capture threshold (score 0-100), ready/reset thresholds, confirmations, cooldown and stale-data limit.
- Six score components can be enabled/disabled: volume, flow/buy pressure, momentum, order book, volatility and liquidity.
- Changes are applied to the next engine start; this avoids changing risk parameters while an active scan is processing ticks.
- Live trading remains fail-closed and is not enabled merely by entering API keys.

### Windows launch
From the project root:
```powershell
.
un_gui.bat
```
or:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.
un_gui.ps1
```
If PowerShell policy blocks scripts, `run_gui.bat` avoids PowerShell execution policy.

# MEXC SPOT SNIPER — Stage 21 (Paper DD + Signal Journal)

Stage 21 is based directly on Stage 20 and fixes two accounting/observability issues found in Paper Trading.

## 1. Correct mark-to-market Max Drawdown
- Open positions are valued at the latest market price on every tick.
- Max DD is calculated from **equity**, not from free cash balance.
- Opening a 50 USDT paper position no longer appears as a ~50 USDT drawdown simply because cash was reserved.
- The GUI now exposes peak equity, Max DD in USDT, and Max DD %.

## 2. Persistent signal journal
- Every confirmed signal is written to `data/signals.csv`.
- A signal is recorded even when the Paper Risk Manager rejects the simulated order.
- Each record contains symbol, score, setup, state, price, pressure, momentum, volume, book imbalance, spread, reasons, and `paper_action` (`OPENED` / `REJECTED`).
- The GUI Signals tab loads the most recent journal records at startup.

## Validation
The included paper-trading and scanner tests cover the new accounting/journal behavior.

Trading remains PAPER by default and LIVE remains separately gated/fail-closed.

## Stage 22 note
Stage 22 supersedes this document with durable SQLite state for Paper Trading and the signal journal.

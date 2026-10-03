# MEXC SPOT SNIPER — Stage 22 (Durable Paper + Journal + Locked LIVE)

Stage 22 continues Stage 21 without changing the market-data/scoring pipeline.

## Paper Trading is now restart-safe

The source of truth is `data/mexc_sniper.db`.

Persisted data includes:
- Paper balance and starting balance
- Open Paper positions and their entry/SL/TP values
- Last mark price and intratrade high/low
- Closed trades and PnL
- Peak equity and Max Drawdown (USDT and %)
- Daily realized PnL used by the Paper risk limit

A normal stop/restart therefore does **not** reset the Paper account to 1000 USDT or lose its open simulated positions.

## Permanent signal journal

Every confirmed signal is stored in SQLite in the `signals` table. The journal survives restarts and the GUI reads it directly at startup.

`data/signals.csv` and `data/paper_trades.csv` remain as backward-compatible exports for older tools.

## Max DD definition

Max DD is calculated from mark-to-market **equity**:

`equity = free_cash + marked_value_of_open_positions`

`drawdown = peak_equity - current_equity`

This avoids counting reserved paper capital as a loss.

## LIVE remains fail-closed

The live execution layer requires all of the following:

1. `TRADING_MODE=LIVE`
2. `LIVE_TRADING_ENABLED=true`
3. `LIVE_RUNTIME_ARMED=true`
4. `TRADING_ENV=live`
5. `LIVE_TRADING_CONFIRM=I_UNDERSTAND_REAL_MONEY`
6. successful Spot-account preflight
7. per-order safety checks

`LIVE_RUNTIME_ARMED` is intentionally not saved by the GUI and defaults to `false`, so a fresh application start cannot inherit an armed LIVE session.

The GUI's **ARM LIVE** action is therefore a runtime action, not a saved preference.

## Validation

The Stage 22 additions include tests for:
- Paper state restoration
- Open-position restoration
- Max DD persistence
- Signal-journal restoration
- LIVE runtime lock

The market-data protobuf test requires a protobuf runtime compatible with the generated `7.36.2` code in `requirements.txt`.

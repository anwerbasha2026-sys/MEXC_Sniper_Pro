# MEXC Sniper — Spot Live Trading

This build adds a real MEXC Spot execution adapter. **It can place real market BUY/SELL orders when all live gates are intentionally enabled.**

MEXC documents the Spot v3 signed `POST /api/v3/order` endpoint, HMAC-SHA256 signing, Spot permissions, and `POST /api/v3/order/test` for validation without sending an order to the matching engine. Exchange rules such as `quoteOrderQtyMarketAllowed`, minimum quote amount, base size precision, and Spot-trading availability should be checked before trading. citeturn2search0

## Safety

- Spot only.
- No futures.
- No leverage.
- No withdrawals.
- Default mode remains PAPER.
- Live execution requires three independent gates:
  - `TRADING_MODE=LIVE`
  - `LIVE_TRADING_ENABLED=true`
  - `LIVE_TRADING_CONFIRM=I_UNDERSTAND_REAL_MONEY`
- The API key should have Spot trading permissions only. MEXC recommends IP restrictions and says API keys/secrets must not be shared. citeturn1search0

## Configure

Copy `.env.example` to `.env` and fill in your own MEXC API credentials.

For the first real-account verification, keep:

```text
LIVE_ORDER_USDT=10
LIVE_MAX_OPEN_POSITIONS=1
```

The credentials must never be pasted into ChatGPT or committed to Git.

## 1. Credential/account preflight — no order

```powershell
python .\app\trading\test_live_gate.py
```

With live mode intentionally enabled, this calls the account endpoint and verifies the account reports Spot trading capability. It does not place an order.

## 2. MEXC order validation — no real order

```powershell
python .\app\trading\test_live_order.py
```

This uses `/api/v3/order/test`, which MEXC documents as validating an order without sending it to the matching engine. citeturn2search0

## 3. Enable real execution

Only after the two checks above succeed:

```text
TRADING_MODE=LIVE
LIVE_TRADING_ENABLED=true
LIVE_TRADING_CONFIRM=I_UNDERSTAND_REAL_MONEY
TRADING_ENV=live
```

The live engine then uses the same Spot signal pipeline, but confirmed signals can result in real market orders.

## Important execution behavior

The live engine uses Spot MARKET BUY with `quoteOrderQty` and MARKET SELL with base `quantity`, both documented by MEXC. It checks exchange information and rounds sell quantity down to `baseSizePrecision`. citeturn2search0

The bot-managed SL/TP is **not an exchange-native stop order** in this adapter. The process monitors market data and sends a MARKET SELL when the configured threshold is reached. Therefore process/network downtime can prevent the software from sending the protective sell. Do not treat this as guaranteed stop-loss protection.

## Start

```powershell
python .\app\exchange\run_spot_manager.py
```

Keep the first live test at the smallest amount you are comfortable losing and watch the exchange order history directly.


## Stage 19

See `README_STAGE19.md` for the protobuf oneof ingestion fix and the expanded diagnostics used to determine why signals do or do not reach paper trading.

## Stage 22 persistence / safety

Paper Trading and the signal journal use `data/mexc_sniper.db` as the durable source of truth. The GUI remains PAPER/LOCKED on startup. LIVE additionally requires the non-persistent runtime arm plus the explicit confirmation phrase and Spot preflight.

See `README_STAGE22.md` for the Stage 22 changes.


## Final release notes

- Paper entry diagnostics remain enabled: spread, entry drift, and top-ask coverage are checked before a Paper open.
- Persistent SQLite/CSV journaling remains enabled for Paper trades, signals, and entry checks.
- Max Drawdown remains persisted and displayed by the GUI.
- Stablecoin exclusion remains enabled by default.
- LIVE remains fail-closed: the GUI ARM LIVE action and the exact confirmation phrase are required before a real order can be sent.
- Protobuf is pinned to the generated-code major version used by this release (`>=7.36.2,<8`).

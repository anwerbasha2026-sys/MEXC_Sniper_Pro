# Stage 13 — Live Spot Safety Layer

This stage strengthens the real-money boundary while keeping the strategy **Spot-only**.

## Added

- Preflight checks account type and Spot permission.
- Checks free USDT before BUY.
- Reads symbol trading rules before every BUY/SELL.
- Enforces a hard 10 USDT maximum order size.
- Verifies the returned `orderId`.
- Re-queries the order after submission before creating a local position.
- Reconciles SELL execution before removing the local position.
- Adds network/API error handling.
- Adds JSON headers.
- Adds `GET /api/v3/order` reconciliation.
- Adds a local safety test that sends zero real orders.

## Important

MEXC states its API connects directly to the live environment and does not provide a sandbox/test environment. The `/api/v3/order/test` endpoint is therefore useful for API validation, but it is not a simulated exchange account.

The bot's SL/TP is still process-managed. If the process or network fails, it cannot guarantee a protective exit.

## Tests

```powershell
python .\app\trading\test_live_safety.py
python .\app\trading\test_live_gate.py
python .\app\trading\test_live_order.py
```

The final command performs preflight/rules checks only and does not place an order.

Keep API withdrawals disabled and restrict the API key by IP where possible.

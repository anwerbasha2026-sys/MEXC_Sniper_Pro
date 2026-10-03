MEXC SNIPER MOBILE — PROFESSIONAL UI / LATEST FIXES

Included in this release:
- Professional dark mobile/tablet UI with Overview, LIVE Trades, Signals, Settings and Activity pages.
- LIVE order amount is configurable.
- LIVE maximum order amount is configurable; the engine also respects MEXC symbol limits.
- Real MEXC account balance: USDT available/total and account trading status.
- Automatic account/position synchronization for non-zero Spot holdings.
- Existing real positions opened by the app remain tracked with their true executed quantity/price.
- Pre-existing MEXC holdings are tagged ACCOUNT SYNC and can be manually closed with MARKET SELL.
- Manual REAL SELL confirmation before an order is submitted.
- Account refresh and position sync run away from the Kivy UI thread.
- WebSocket scanner remains on the existing async controller.
- LIVE engine remains fail-closed with preflight, balance, spread, slippage, entry drift, depth and order-status checks.
- The confirmation phrase remains I_UNDERSTAND_REAL_MONEY.
- Buildozer configuration remains targeted at ONN GN3 ARMv7 / Android and can be used to produce the APK.

Notes:
- Pre-existing holdings do not have a fabricated historical entry price. The synchronized view uses the current market price as its reference until trade history is available.
- Manual SELL sends a real order to MEXC after confirmation.
- Python syntax was verified with py_compile. Kivy runtime import was not executed in this build container because Kivy is not installed there.

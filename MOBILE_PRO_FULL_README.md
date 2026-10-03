# MEXC Sniper Mobile — PRO FULL BUILD

This package is the complete Android source tree, not only the mobile UI file.

Included fixes:
- Professional Kivy mobile UI with Overview / Signals / LIVE Trades / Settings / Activity.
- REAL/LIVE trades screen with manual MARKET SELL confirmation.
- Immediate and recurring account sync from the MEXC account.
- Existing Spot holdings are imported into LIVE Trades as ACCOUNT SYNC positions.
- LIVE order amount and maximum order amount are editable.
- MEXC symbol/risk/quantity checks remain in the live engine.
- SQLite corruption recovery is included: a malformed local database is preserved as a timestamped .corrupt backup and a fresh database is created.
- The Android build is pinned for the ONN GN3 class device (Kivy 2.3.1 / Android API 33 / armeabi-v7a).

Important:
- This source package does not contain a prebuilt APK.
- LIVE mode sends real orders only after the existing live gate and confirmation are satisfied.
- ACCOUNT SYNC positions imported from the exchange do not invent a historical entry price; their current market price is used as the reference until trade history is available.

# MEXC Sniper Mobile — Background Mode

This release adds an Android foreground service (`sniperd`) so the same trading
controller can continue running after the activity is sent to the background.

## How it works

1. Open the app while visible.
2. Configure API keys and LIVE settings.
3. Arm LIVE only when you intend to allow real orders.
4. Press **START BG**.
5. Android starts the `sniperd` foreground+sticky service.
6. You can press Home or turn off the screen; the service continues its
   WebSocket/scanner/account-sync loop.
7. The app UI reads `.mexc_sniper_mobile_service_state.json` when reopened.
8. Press **STOP** in the app to request a clean service shutdown.

The service starts only from the visible activity, which is required for
Android 12+ foreground-service start restrictions.

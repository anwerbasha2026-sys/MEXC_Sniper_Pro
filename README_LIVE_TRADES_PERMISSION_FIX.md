# LIVE Trades Android permission fix

The Android UI was using `Path.home()` for the mobile config. On the affected device this resolved to `/data`, so the atomic save attempted to create:
`/data/mexc_sniper_mobile.tmp`
which is not writable by the app.

This release stores config and background-service state under Android's private app storage using `android.storage.app_storage_path()` and has a safe direct-write fallback.

The LIVE Trades tab can now refresh account data without touching `/data`.

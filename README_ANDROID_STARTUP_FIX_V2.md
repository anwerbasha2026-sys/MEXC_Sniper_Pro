# Android Startup Fix v2

The Android entrypoint is now bootstrap-safe. `main.py` imports only Kivy first; all
MEXC/API/WebSocket/Protobuf/Pydantic modules are loaded lazily after the UI is visible.

If a runtime dependency is missing, the app should stay open and display the exact
exception instead of silently closing. It also writes `mexc_startup_crash.log`.

Start the background engine only after the UI is visible and configured.

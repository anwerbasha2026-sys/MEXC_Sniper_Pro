# MEXC Sniper Stage 26 — Android Onn GN3 ARMv7

This is an Android port of the Stage 26 Windows project.

## Architecture

- Windows remains unchanged: `app/main.py` launches the existing Tkinter dashboard.
- Android uses the root `main.py` and a Kivy UI.
- Android does **not** import Tkinter or `app.dashboard`.
- The mobile engine launches the existing Stage 26 `LiveSignalScanner`, `SymbolDiscovery`, MEXC Spot WebSocket manager, PaperTrader, risk manager, Max DD tracking and persistent signal/trade journal.
- LIVE execution is not instantiated by the Android entry point and is therefore locked.

## Persistence

Android stores the SQLite/CSV data below the app's writable Kivy user-data directory, so paper positions, trades and signals survive app restarts.

## Reduced Stage 26 conditions

The existing Stage 26 settings are preserved, including the reduced scanner and entry-guard values in `app/config.py`.

## Target

- Onn GN3 / ARMv7 (`armeabi-v7a`)
- Python 3.11.5
- python-for-android `v2024.01.21`
- Kivy 2.3.0

## Build

GitHub Actions workflow:

`.github/workflows/android-apk.yml`

Artifact:

`mexc-sniper-stage26-onn-gn3-armeabi-v7a`

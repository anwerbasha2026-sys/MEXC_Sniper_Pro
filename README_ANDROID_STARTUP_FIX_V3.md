# Android Startup Fix V3

This build changes the Android entry point so the Kivy window is shown before
`app.mobile_main` is imported. The previous design imported the full mobile UI
before `App.run()`, so an import error could terminate Python before a visible
screen appeared.

The new entry point uses `BootstrapApp` and schedules the full UI load after the
first frame. Any exception is written to `mexc_startup_crash.log` and shown in
the running app instead of silently closing it.

The build workflow also verifies that the canonical packaged `main.py` does not
contain the obsolete `android.mobile_main` import.

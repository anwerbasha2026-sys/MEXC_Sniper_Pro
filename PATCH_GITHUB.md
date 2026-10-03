# GitHub Actions fix

The failing step was checking for `BootstrapApp` in `main.py`. The repository version used by the workflow did not contain that class, so the job stopped before Android build began.

This package replaces `.github/workflows/android-apk.yml` with checks that match the actual entry-point contract:
- `main.py` exists
- `app/mobile_main.py` exists
- `service.py` exists
- `main.py` must not reference `android.mobile_main`
- `main.py` must import `app.mobile_main`
- `main.py`, `app/mobile_main.py`, and `service.py` must compile
- the generated Buildozer source is checked with the same rules

Use the `main.py` and workflow from this package together. Do not keep the old `grep -q "BootstrapApp"` line.

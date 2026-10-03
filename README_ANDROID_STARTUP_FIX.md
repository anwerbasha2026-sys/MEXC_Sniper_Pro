# Android startup fix

This release pins the Android protobuf runtime to `protobuf==7.36.2`, matching the checked-in generated protobuf modules (gencode 7.36.2). The previous build allowed a mismatched older runtime, which can terminate the app during the initial import before the UI appears.

The Android Buildozer requirements also pin Python to 3.11.5. `main.py` writes `mexc_startup_crash.log` on an uncaught startup exception before re-raising it.

Background service configuration remains `sniperd:service.py:foreground:sticky`.

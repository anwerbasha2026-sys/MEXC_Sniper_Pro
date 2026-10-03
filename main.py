import os
import sys
import traceback
from pathlib import Path


def _write_startup_error(exc: BaseException) -> None:
    text = "MEXC Sniper Android startup crash\n\n" + traceback.format_exc()
    targets = []
    try:
        targets.append(Path.home() / "mexc_startup_crash.log")
    except Exception:
        pass
    try:
        targets.append(Path.cwd() / "mexc_startup_crash.log")
    except Exception:
        pass
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            break
        except Exception:
            continue


def is_android():
    return sys.platform == "android" or "ANDROID_ARGUMENT" in os.environ


try:
    if is_android():
        from app.mobile_main import MEXCSniperMobileApp
        MEXCSniperMobileApp().run()
    else:
        from app.dashboard.dashboard import Dashboard
        Dashboard().mainloop()
except BaseException as exc:
    _write_startup_error(exc)
    raise

import os
import sys
import traceback
from pathlib import Path


def _write_startup_error(exc: BaseException) -> None:
    text = "MEXC Sniper Android startup crash\n\n" + traceback.format_exc()
    targets = []
    for base in (Path.home(), Path.cwd()):
        try:
            targets.append(base / "mexc_startup_crash.log")
        except Exception:
            pass
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            return
        except Exception:
            continue


def is_android():
    return sys.platform == "android" or "ANDROID_ARGUMENT" in os.environ


# Keep the Android bootstrap tiny. Heavy trading imports are intentionally delayed
# until after the Kivy window is created.
if is_android():
    try:
        from kivy.app import App
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.graphics import Color, Rectangle

        class BootstrapErrorApp(App):
            title = "MEXC Sniper Mobile"
            def __init__(self, error_text=None, **kwargs):
                super().__init__(**kwargs)
                self.error_text = error_text or ""
            def build(self):
                root = BoxLayout(orientation="vertical", padding=24, spacing=16)
                with root.canvas.before:
                    Color(0.025, 0.055, 0.095, 1)
                    self.bg = Rectangle(pos=root.pos, size=root.size)
                root.bind(pos=lambda *_: setattr(self.bg, "pos", root.pos),
                          size=lambda *_: setattr(self.bg, "size", root.size))
                root.add_widget(Label(text="MEXC SNIPER", font_size="28sp", bold=True))
                root.add_widget(Label(text=self.error_text or "Starting…\nPlease wait.", halign="center"))
                return root

        try:
            from app.mobile_main import MEXCSniperMobileApp
            MEXCSniperMobileApp().run()
        except BaseException as exc:
            _write_startup_error(exc)
            BootstrapErrorApp(f"STARTUP ERROR\n\n{type(exc).__name__}: {exc}").run()
    except BaseException as exc:
        _write_startup_error(exc)
        raise
else:
    try:
        from app.dashboard.dashboard import Dashboard
        Dashboard().mainloop()
    except BaseException as exc:
        _write_startup_error(exc)
        raise

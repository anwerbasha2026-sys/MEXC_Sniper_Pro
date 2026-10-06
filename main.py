"""Android-safe entry point for MEXC Sniper Mobile."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def is_android() -> bool:
    return sys.platform == "android" or "ANDROID_ARGUMENT" in os.environ


def _log_startup_error(exc: BaseException) -> None:
    text = "MEXC Sniper startup error\n\n" + traceback.format_exc()
    for base in (Path.home(), Path.cwd(), Path("/sdcard/Download")):
        try:
            target = base / "mexc_startup_crash.log"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            return
        except Exception:
            continue


if is_android():
    from kivy.app import App
    from kivy.clock import Clock
    from kivy.graphics import Color, Rectangle
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label

    class BootstrapApp(App):
        title = "MEXC Sniper Mobile"

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.root_box = None
            self.message = None
            self.detail = None
            self._loaded = False

        def build(self):
            root = BoxLayout(orientation="vertical", padding=24, spacing=14)
            with root.canvas.before:
                Color(0.025, 0.055, 0.095, 1)
                bg = Rectangle(pos=root.pos, size=root.size)
            root.bind(pos=lambda *_: setattr(bg, "pos", root.pos),
                      size=lambda *_: setattr(bg, "size", root.size))
            root.add_widget(Label(text="MEXC SNIPER", font_size="28sp", bold=True,
                                  color=(0.1, 0.88, 0.98, 1), size_hint_y=None, height=60))
            self.message = Label(text="Starting secure mobile terminal…", font_size="17sp",
                                 halign="center", valign="middle")
            self.message.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
            root.add_widget(self.message)
            self.detail = Label(text="Initializing UI…", font_size="12sp",
                                color=(0.65, 0.72, 0.80, 1), halign="center", valign="top")
            self.detail.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
            root.add_widget(self.detail)
            retry = Button(text="RETRY FULL UI", size_hint_y=None, height=52, opacity=0, disabled=True)
            retry.bind(on_release=lambda *_: self._load_full_ui())
            self.retry = retry
            root.add_widget(retry)
            self.root_box = root
            Clock.schedule_once(lambda *_: self._load_full_ui(), 0.35)
            return root

        def _load_full_ui(self):
            if self._loaded:
                return
            try:
                data_dir = Path(self.user_data_dir)
                data_dir.mkdir(parents=True, exist_ok=True)
                os.environ["MEXC_MOBILE_CONFIG"] = str(data_dir / "mexc_sniper_mobile.json")

                # Patch MobileUI BEFORE build() creates any pages/callbacks.
                from app import mobile_main as mobile_module
                from app.mobile_safety_patch import apply
                apply(mobile_module)
                from app.mobile_main import MEXCSniperMobileApp
                full_app = MEXCSniperMobileApp()
                full_root = full_app.build()
                self.root_box.clear_widgets()
                self.root_box.add_widget(full_root)
                self._loaded = True
            except BaseException as exc:
                _log_startup_error(exc)
                self.message.text = "FULL UI LOAD FAILED — APP KEPT OPEN"
                self.message.color = (1.0, 0.35, 0.45, 1)
                self.detail.text = f"{type(exc).__name__}: {exc}\n\nA log was saved as mexc_startup_crash.log"
                self.retry.opacity = 1
                self.retry.disabled = False

else:
    try:
        from app.dashboard.dashboard import Dashboard
        Dashboard().mainloop()
    except BaseException as exc:
        _log_startup_error(exc)
        raise


if is_android():
    BootstrapApp().run()

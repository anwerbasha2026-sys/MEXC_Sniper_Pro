"""Android foreground service entry point for MEXC Sniper.

The service intentionally does not import Kivy. It runs the trading/network
controller headlessly so the UI process and service process remain isolated.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _default_config_path() -> Path:
    configured = os.environ.get("MEXC_MOBILE_CONFIG")
    if configured:
        return Path(configured)

    private = os.environ.get("ANDROID_PRIVATE")
    if private:
        return Path(private) / "mexc_sniper_mobile.json"
    if sys.platform == "android" or os.environ.get("ANDROID_ARGUMENT"):
        return Path("/data/data/org.mexcsniper/files/mexc_sniper_mobile.json")
    return Path.home() / ".mexc_sniper_mobile.json"


CONFIG_PATH = _default_config_path()
STATE_PATH = CONFIG_PATH.with_name(".mexc_sniper_mobile_service_state.json")


class StateWriter:
    def __init__(self):
        self.state = {"status": "STARTING", "account": {}, "events": [], "rows": [], "updated_at": time.time()}

    def _write(self):
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
            tmp.replace(STATE_PATH)
        except Exception:
            pass

    def emit(self, kind, value):
        if kind == "status":
            self.state["status"] = str(value)
        elif kind == "account" and isinstance(value, dict):
            value = dict(value)
            value.pop("_raw_account", None)
            self.state["account"] = value
        elif kind == "row" and isinstance(value, dict):
            rows = self.state.setdefault("rows", [])
            rows.append(value)
            latest = {}
            for row in rows[-400:]:
                sym = str(row.get("symbol", ""))
                if sym:
                    latest[sym] = row
            self.state["rows"] = list(latest.values())[-120:]
        elif kind in {"event", "error"}:
            events = self.state.setdefault("events", [])
            prefix = "ERROR • " if kind == "error" else ""
            events.append(prefix + str(value))
            self.state["events"] = events[-100:]
        elif kind == "preflight" and isinstance(value, dict):
            self.state["preflight"] = value
        self.state["updated_at"] = time.time()
        self._write()


def main():
    writer = StateWriter()
    writer.emit("status", "BACKGROUND STARTING")
    try:
        from app.mobile_main import MobileController, load_config
        controller = MobileController(writer.emit)
        controller._thread(load_config())
    except Exception as exc:
        writer.emit("error", repr(exc))
        writer.emit("status", "BACKGROUND ERROR")
        time.sleep(2)
    finally:
        writer.emit("status", "BACKGROUND STOPPED")


if __name__ == "__main__":
    main()

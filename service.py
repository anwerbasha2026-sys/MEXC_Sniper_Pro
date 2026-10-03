"""Android foreground service entry point for MEXC Sniper.

The service runs the same MobileController used by the UI, so scanner,
WebSocket, LIVE execution, SL/TP checks, account synchronization and reconnect
logic remain in one code path. It is packaged as a foreground+sticky service
and is started explicitly by the visible Android activity.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.mobile_main import MobileController, load_config

CONFIG_PATH = Path(
    os.environ.get(
        "MEXC_MOBILE_CONFIG",
        str(Path.home() / ".mexc_sniper_mobile.json"),
    )
)
STATE_PATH = CONFIG_PATH.with_name(".mexc_sniper_mobile_service_state.json")


class StateWriter:
    def __init__(self):
        self.state = {
            "status": "STARTING",
            "account": {},
            "events": [],
            "rows": [],
            "updated_at": time.time(),
        }

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
            # Keep a compact recent snapshot per symbol.
            latest = {}
            for row in rows[-300:]:
                sym = str(row.get("symbol", ""))
                if sym:
                    latest[sym] = row
            self.state["rows"] = list(latest.values())[-120:]
        elif kind == "event":
            events = self.state.setdefault("events", [])
            events.append(str(value))
            self.state["events"] = events[-80:]
        elif kind == "error":
            events = self.state.setdefault("events", [])
            events.append(f"ERROR • {value}")
            self.state["events"] = events[-80:]
        elif kind == "preflight" and isinstance(value, dict):
            self.state["preflight"] = value
        self.state["updated_at"] = time.time()
        self._write()


def main():
    writer = StateWriter()
    writer.emit("status", "BACKGROUND STARTING")
    controller = MobileController(writer.emit)
    try:
        cfg = load_config()
        controller._thread(cfg)
    except Exception as exc:
        writer.emit("error", repr(exc))
        writer.emit("status", "BACKGROUND ERROR")
        time.sleep(2)
    finally:
        writer.emit("status", "BACKGROUND STOPPED")


if __name__ == "__main__":
    main()

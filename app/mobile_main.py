from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.switch import Switch
from kivy.uix.popup import Popup

from app.config import TradingMode, settings
from app.exchange.spot_client import SpotClient
from app.exchange.symbol_discovery import SymbolDiscovery
from app.exchange.websocket_manager import MEXCSpotWebSocketManager
from app.scanner.live_signal_scanner import LiveSignalScanner
from app.trading.live_engine import LiveSpotEngine

BASE = Path(__file__).resolve().parents[1]
MOBILE_CONFIG = Path(os.environ.get("MEXC_MOBILE_CONFIG", str(Path.home() / ".mexc_sniper_mobile.json")))

DEFAULTS = {
    "trading_mode": "LIVE",
    "trading_env": "live",
    "mexc_api_key": "",
    "mexc_api_secret": "",
    "live_trading_enabled": False,
    "live_runtime_armed": False,
    "live_trading_confirm": "",
    "live_order_usdt": 10.0,
    "live_hard_max_order_usdt": 100.0,
    "live_max_open_positions": 1,
    "live_stop_loss_pct": 1.5,
    "live_take_profit_pct": 3.0,
    "live_max_slippage_pct": 0.30,
    "live_max_spread_pct": 0.20,
    "live_max_entry_drift_pct": 0.30,
    "live_min_top_ask_coverage_pct": 50.0,
    "scanner_symbol_limit": 116,
    "scanner_score_threshold": 65.0,
    "scanner_ready_threshold": 55.0,
    "scanner_reset_threshold": 50.0,
    "scanner_confirmations": 1,
    "scanner_cooldown_seconds": 20.0,
    "scanner_stale_after_ms": 5000.0,
    "stablecoin_exclusion_enabled": True,
    "strategy_volume": True,
    "strategy_flow": True,
    "strategy_momentum": True,
    "strategy_book": True,
    "strategy_volatility": True,
    "strategy_liquidity": True,
}


def load_config():
    data = dict(DEFAULTS)
    try:
        if MOBILE_CONFIG.exists():
            data.update(json.loads(MOBILE_CONFIG.read_text(encoding="utf-8")))
    except Exception:
        pass
    return data


def save_config(data):
    MOBILE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    MOBILE_CONFIG.write_text(json.dumps(data, indent=2), encoding="utf-8")


class MobileController:
    def __init__(self, emit):
        self.emit = emit
        self.thread = None
        self.stop_event = threading.Event()
        self.loop = None
        self.manager = None
        self.scanner = None
        self.live_engine = None
        self.prices = {}

    def start(self, cfg):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._thread, args=(dict(cfg),), daemon=True)
        self.thread.start()

    def open_live_trades(self, *_args):
        box = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(8))
        title = Label(text="REAL / LIVE TRADES", size_hint_y=None, height=dp(36), font_size="18sp")
        box.add_widget(title)
        summary = Label(text="Loading...", size_hint_y=None, height=dp(44))
        box.add_widget(summary)
        scroll = ScrollView()
        trades_box = BoxLayout(orientation="vertical", spacing=dp(5), size_hint_y=None)
        trades_box.bind(minimum_height=trades_box.setter("height"))
        scroll.add_widget(trades_box)
        box.add_widget(scroll)
        controls = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(5))
        refresh_btn = Button(text="REFRESH")
        close_btn = Button(text="CLOSE")
        controls.add_widget(refresh_btn)
        controls.add_widget(close_btn)
        box.add_widget(controls)
        popup = Popup(title="MEXC — REAL TRADES", content=box, size_hint=(0.96, 0.90), auto_dismiss=True)

        def render(_btn=None):
            trades_box.clear_widgets()
            engine = self.controller.live_engine
            if engine is None:
                summary.text = "LIVE engine is not running / API not initialized."
                trades_box.add_widget(Label(text="No live trades available.", size_hint_y=None, height=dp(40)))
                return
            positions = list(engine.positions.values())
            if not positions:
                summary.text = "OPEN REAL TRADES: 0"
                trades_box.add_widget(Label(text="No open real trades.", size_hint_y=None, height=dp(40)))
                return
            summary.text = f"OPEN REAL TRADES: {len(positions)} / {engine.max_open_positions}"
            for pos in positions:
                current = float(self.controller.prices.get(pos.symbol, pos.entry_price))
                pnl_pct = ((current - pos.entry_price) / pos.entry_price * 100.0) if pos.entry_price else 0.0
                pnl_usdt = (current - pos.entry_price) * pos.quantity
                card = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(150), padding=dp(5), spacing=dp(2))
                card.add_widget(Label(text=f"{pos.symbol}   LIVE", size_hint_y=None, height=dp(26), font_size="16sp"))
                card.add_widget(Label(text=f"Qty: {pos.quantity:.10f} | Entry: {pos.entry_price:.10f}", size_hint_y=None, height=dp(24)))
                card.add_widget(Label(text=f"Current: {current:.10f} | PnL: {pnl_usdt:+.6f} USDT ({pnl_pct:+.3f}%)", size_hint_y=None, height=dp(24)))
                card.add_widget(Label(text=f"SL: {pos.stop_loss:.10f} | TP: {pos.take_profit:.10f}", size_hint_y=None, height=dp(24)))
                card.add_widget(Label(text=f"BUY Order: {pos.entry_order_id}", size_hint_y=None, height=dp(24)))
                close_one = Button(text=f"SELL {pos.symbol} NOW", size_hint_y=None, height=dp(34))
                def sell(_btn, symbol=pos.symbol):
                    confirm_box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
                    confirm_box.add_widget(Label(
                        text=f"Close {symbol} with a MARKET SELL using real MEXC funds?",
                        halign="center",
                    ))
                    row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
                    yes = Button(text="SELL NOW")
                    no = Button(text="CANCEL")
                    row.add_widget(yes); row.add_widget(no)
                    confirm_box.add_widget(row)
                    confirm = Popup(title="CONFIRM REAL SELL", content=confirm_box, size_hint=(0.90, 0.34), auto_dismiss=False)

                    def do_sell(*_):
                        confirm.dismiss()
                        self.emit("event", f"MANUAL SELL REQUESTED {symbol}")
                        def worker():
                            try:
                                result = engine.close(symbol, "MANUAL")
                                order_id = (result or {}).get("order", {}).get("orderId", "")
                                Clock.schedule_once(lambda *_: self.emit("event", f"MANUAL SELL {symbol} | order={order_id}"), 0)
                                Clock.schedule_once(lambda *_: render(), 0)
                            except Exception as exc:
                                Clock.schedule_once(lambda *_: self.emit("error", f"MANUAL SELL FAILED {symbol}: {exc}"), 0)
                                Clock.schedule_once(lambda *_: render(), 0)
                        threading.Thread(target=worker, daemon=True).start()

                    yes.bind(on_release=do_sell)
                    no.bind(on_release=lambda *_: confirm.dismiss())
                    confirm.open()

                close_one.bind(on_release=sell)
                card.add_widget(close_one)
                trades_box.add_widget(card)

        refresh_btn.bind(on_release=render)
        close_btn.bind(on_release=lambda *_: popup.dismiss())
        popup.open()
        render()

    def stop(self):
        self.stop_event.set()
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: None)

    def _thread(self, cfg):
        try:
            asyncio.run(self._run(cfg))
        except Exception as exc:
            self.emit("error", str(exc))
        finally:
            self.emit("status", "STOPPED")

    async def _run(self, c):
        self.loop = asyncio.get_running_loop()
        settings.trading_mode = TradingMode(str(c.get("trading_mode", "LIVE")).upper())
        settings.trading_env = str(c.get("trading_env", "live"))
        settings.live_runtime_armed = bool(c.get("live_runtime_armed", False))
        settings.live_trading_enabled = bool(c.get("live_trading_enabled", False)) and settings.live_runtime_armed
        settings.live_trading_confirm = str(c.get("live_trading_confirm", ""))
        settings.live_order_usdt = float(c.get("live_order_usdt", 10))
        settings.live_hard_max_order_usdt = float(c.get("live_hard_max_order_usdt", 100))
        settings.live_max_open_positions = int(c.get("live_max_open_positions", 1))
        settings.live_stop_loss_pct = float(c.get("live_stop_loss_pct", 1.5))
        settings.live_take_profit_pct = float(c.get("live_take_profit_pct", 3.0))
        settings.live_max_slippage_pct = float(c.get("live_max_slippage_pct", .30))
        settings.live_max_spread_pct = float(c.get("live_max_spread_pct", .20))
        settings.live_max_entry_drift_pct = float(c.get("live_max_entry_drift_pct", .30))
        settings.live_min_top_ask_coverage_pct = float(c.get("live_min_top_ask_coverage_pct", 50))
        settings.mexc_api_key = str(c.get("mexc_api_key", ""))
        settings.mexc_api_secret = str(c.get("mexc_api_secret", ""))
        settings.stablecoin_exclusion_enabled = bool(c.get("stablecoin_exclusion_enabled", True))

        self.emit("status", "STARTING")
        self.live_engine = None
        if settings.trading_mode == TradingMode.LIVE and settings.live_trading_enabled:
            self.live_engine = LiveSpotEngine()
            pre = await asyncio.to_thread(self.live_engine.preflight)
            self.emit("account", await asyncio.to_thread(self.live_engine.account_snapshot))
            self.emit("status", "LIVE READY")
            self.emit("preflight", pre)

        strategies = {k: bool(c.get("strategy_" + k, True)) for k in ("volume", "flow", "momentum", "book", "volatility", "liquidity")}
        self.scanner = LiveSignalScanner(
            strong_threshold=float(c.get("scanner_score_threshold", 65)),
            ready_threshold=float(c.get("scanner_ready_threshold", 55)),
            reset_threshold=float(c.get("scanner_reset_threshold", 50)),
            confirmations_required=int(c.get("scanner_confirmations", 1)),
            cooldown_seconds=float(c.get("scanner_cooldown_seconds", 20)),
            stale_after_ms=float(c.get("scanner_stale_after_ms", 5000)),
            paper_starting_balance=1000.0, paper_order_usdt=50.0,
            paper_stop_loss_pct=1.5, paper_take_profit_pct=3.0,
            paper_max_open_positions=5, paper_max_spread_pct=.40,
            paper_max_entry_drift_pct=.60, paper_min_top_ask_coverage_pct=25,
            enabled_strategies=strategies,
        )
        discovery = SymbolDiscovery(client=SpotClient(), limit=max(1, int(c.get("scanner_symbol_limit", 116))), stablecoin_exclusion_enabled=bool(c.get("stablecoin_exclusion_enabled", True)))
        symbols = await discovery.discover()
        if not symbols:
            raise RuntimeError("No eligible Spot/USDT symbols were found")
        self.emit("status", f"SCANNING {len(symbols)} SYMBOLS")

        async def on_message(wrapper):
            decisions = self.scanner.process_wrapper(wrapper)
            for snapshot, result, decision in decisions:
                self.prices[snapshot.symbol] = float(snapshot.price)
                self.emit("row", {"symbol": snapshot.symbol, "score": float(result.score), "price": float(snapshot.price), "state": decision.state.value, "setup": result.setup, "ready": bool(snapshot.ready)})
                if decision.should_alert and self.live_engine and snapshot.price > 0:
                    try:
                        p = await asyncio.to_thread(self.live_engine.open_long, snapshot.symbol, snapshot.price, result.score)
                        if p:
                            self.emit("event", f"BUY {p.symbol} | {p.entry_price:.8f} | {p.entry_order_id}")
                    except Exception as exc:
                        self.emit("event", f"BUY FAILED {snapshot.symbol}: {exc}")
                if self.live_engine and snapshot.price > 0:
                    try:
                        closed = await asyncio.to_thread(self.live_engine.update_price, snapshot.symbol, snapshot.price)
                        if closed:
                            self.emit("event", f"SELL {snapshot.symbol} | {closed.get('reason','')}")
                    except Exception as exc:
                        self.emit("event", f"SELL FAILED {snapshot.symbol}: {exc}")

        self.manager = MEXCSpotWebSocketManager(symbols=[x.symbol for x in symbols], on_message=on_message, channels_per_connection=28, deal_interval="10ms", book_interval="100ms", ping_interval=20.0)
        await self.manager.start()

    def refresh_balance(self):
        if not self.live_engine:
            # Build a non-trading client solely for read-only account information.
            if not settings.mexc_api_key or not settings.mexc_api_secret:
                raise RuntimeError("Enter MEXC API key and secret first")
            self.live_engine = LiveSpotEngine()
        return self.live_engine.account_snapshot()


class MobileUI(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(6), padding=dp(8), **kwargs)
        self.cfg = load_config()
        self.controller = MobileController(self.emit)
        self.fields = {}
        self.rows = {}
        self.status = Label(text="MEXC SNIPER MOBILE", size_hint_y=None, height=dp(34), font_size="18sp")
        self.add_widget(self.status)
        self._build()

    def _field(self, grid, key, label, password=False):
        grid.add_widget(Label(text=label, size_hint_y=None, height=dp(38)))
        w = TextInput(text=str(self.cfg.get(key, "")), multiline=False, password=password, size_hint_y=None, height=dp(38))
        self.fields[key] = w
        grid.add_widget(w)

    def _build(self):
        scroll = ScrollView()
        root = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        root.bind(minimum_height=root.setter("height"))

        account = GridLayout(cols=2, size_hint_y=None, height=dp(150), spacing=dp(4))
        self.account_labels = {}
        for k in ("USDT available", "USDT total", "Can Trade", "API permission"):
            account.add_widget(Label(text=k))
            lab = Label(text="-")
            self.account_labels[k] = lab
            account.add_widget(lab)
        root.add_widget(account)

        settings_grid = GridLayout(cols=2, size_hint_y=None, spacing=dp(4))
        settings_grid.bind(minimum_height=settings_grid.setter("height"))
        for key, label, pwd in [
            ("mexc_api_key", "MEXC API Key", False), ("mexc_api_secret", "MEXC API Secret", True),
            ("live_order_usdt", "Order USDT", False), ("live_hard_max_order_usdt", "Maximum Order USDT", False),
            ("live_max_open_positions", "Max Open Positions", False), ("live_stop_loss_pct", "Stop Loss %", False),
            ("live_take_profit_pct", "Take Profit %", False), ("live_max_slippage_pct", "Max Slippage %", False),
            ("live_max_spread_pct", "Max Spread %", False), ("live_max_entry_drift_pct", "Max Entry Drift %", False),
            ("scanner_symbol_limit", "Scanner Symbols", False), ("scanner_score_threshold", "Score Threshold", False),
            ("scanner_ready_threshold", "Ready Threshold", False), ("scanner_confirmations", "Confirmations", False),
        ]:
            self._field(settings_grid, key, label, pwd)
        root.add_widget(Label(text="TRADING SETTINGS", size_hint_y=None, height=dp(30)))
        root.add_widget(settings_grid)

        for key, text in [("live_trading_enabled", "Enable LIVE"), ("live_runtime_armed", "Arm LIVE"), ("stablecoin_exclusion_enabled", "Exclude Stablecoins")]:
            box = BoxLayout(size_hint_y=None, height=dp(42))
            box.add_widget(Label(text=text))
            sw = Switch(active=bool(self.cfg.get(key, False)))
            self.fields[key] = sw
            box.add_widget(sw)
            root.add_widget(box)

        self.confirm = TextInput(text=self.cfg.get("live_trading_confirm", ""), hint_text="Type I_UNDERSTAND_REAL_MONEY to arm", multiline=False, size_hint_y=None, height=dp(42))
        root.add_widget(self.confirm)
        self.fields["live_trading_confirm"] = self.confirm

        buttons = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(5))
        for text, fn in [("SAVE", self.save), ("REFRESH BALANCE", self.refresh), ("LIVE TRADES", self.open_live_trades), ("START", self.start), ("STOP", self.stop)]:
            b = Button(text=text)
            b.bind(on_release=lambda _b, f=fn: f())
            buttons.add_widget(b)
        root.add_widget(buttons)

        root.add_widget(Label(text="TOP SIGNALS", size_hint_y=None, height=dp(30)))
        self.signal_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        self.signal_box.bind(minimum_height=self.signal_box.setter("height"))
        root.add_widget(self.signal_box)
        root.add_widget(Label(text="EVENTS", size_hint_y=None, height=dp(30)))
        self.events = Label(text="", halign="left", valign="top", size_hint_y=None)
        self.events.bind(texture_size=lambda *_: setattr(self.events, "height", max(dp(100), self.events.texture_size[1])))
        root.add_widget(self.events)
        scroll.add_widget(root)
        self.add_widget(scroll)

    def collect(self):
        for key, w in self.fields.items():
            if isinstance(w, Switch):
                self.cfg[key] = bool(w.active)
            else:
                self.cfg[key] = w.text
        self.cfg["live_trading_confirm"] = self.confirm.text
        numeric = ["live_order_usdt", "live_hard_max_order_usdt", "live_stop_loss_pct", "live_take_profit_pct", "live_max_slippage_pct", "live_max_spread_pct", "live_max_entry_drift_pct", "scanner_score_threshold", "scanner_ready_threshold"]
        ints = ["live_max_open_positions", "scanner_symbol_limit", "scanner_confirmations"]
        for k in numeric:
            self.cfg[k] = float(self.cfg[k])
        for k in ints:
            self.cfg[k] = int(float(self.cfg[k]))
        self.cfg["trading_mode"] = "LIVE"
        self.cfg["trading_env"] = "live"
        return self.cfg

    def save(self):
        try:
            save_config(self.collect())
            self.status.text = "SAVED"
        except Exception as exc:
            self.status.text = f"SAVE ERROR: {exc}"

    def start(self):
        try:
            c = self.collect(); save_config(c)
            if c["live_trading_enabled"] and c["live_runtime_armed"] and c["live_trading_confirm"] != LiveSpotEngine.CONFIRMATION:
                raise RuntimeError("LIVE confirmation is incorrect")
            self.controller.start(c)
        except Exception as exc:
            self.status.text = f"ERROR: {exc}"

    def open_live_trades(self, *_args):
        box = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(8))
        title = Label(text="REAL / LIVE TRADES", size_hint_y=None, height=dp(36), font_size="18sp")
        box.add_widget(title)
        summary = Label(text="Loading...", size_hint_y=None, height=dp(44))
        box.add_widget(summary)
        scroll = ScrollView()
        trades_box = BoxLayout(orientation="vertical", spacing=dp(5), size_hint_y=None)
        trades_box.bind(minimum_height=trades_box.setter("height"))
        scroll.add_widget(trades_box)
        box.add_widget(scroll)
        controls = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(5))
        refresh_btn = Button(text="REFRESH")
        close_btn = Button(text="CLOSE")
        controls.add_widget(refresh_btn)
        controls.add_widget(close_btn)
        box.add_widget(controls)
        popup = Popup(title="MEXC — REAL TRADES", content=box, size_hint=(0.96, 0.90), auto_dismiss=True)

        def render(_btn=None):
            trades_box.clear_widgets()
            engine = self.controller.live_engine
            if engine is None:
                summary.text = "LIVE engine is not running / API not initialized."
                trades_box.add_widget(Label(text="No live trades available.", size_hint_y=None, height=dp(40)))
                return
            positions = list(engine.positions.values())
            if not positions:
                summary.text = "OPEN REAL TRADES: 0"
                trades_box.add_widget(Label(text="No open real trades.", size_hint_y=None, height=dp(40)))
                return
            summary.text = f"OPEN REAL TRADES: {len(positions)} / {engine.max_open_positions}"
            for pos in positions:
                current = float(self.controller.prices.get(pos.symbol, pos.entry_price))
                pnl_pct = ((current - pos.entry_price) / pos.entry_price * 100.0) if pos.entry_price else 0.0
                pnl_usdt = (current - pos.entry_price) * pos.quantity
                card = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(150), padding=dp(5), spacing=dp(2))
                card.add_widget(Label(text=f"{pos.symbol}   LIVE", size_hint_y=None, height=dp(26), font_size="16sp"))
                card.add_widget(Label(text=f"Qty: {pos.quantity:.10f} | Entry: {pos.entry_price:.10f}", size_hint_y=None, height=dp(24)))
                card.add_widget(Label(text=f"Current: {current:.10f} | PnL: {pnl_usdt:+.6f} USDT ({pnl_pct:+.3f}%)", size_hint_y=None, height=dp(24)))
                card.add_widget(Label(text=f"SL: {pos.stop_loss:.10f} | TP: {pos.take_profit:.10f}", size_hint_y=None, height=dp(24)))
                card.add_widget(Label(text=f"BUY Order: {pos.entry_order_id}", size_hint_y=None, height=dp(24)))
                close_one = Button(text=f"SELL {pos.symbol} NOW", size_hint_y=None, height=dp(34))
                def sell(_btn, symbol=pos.symbol):
                    confirm_box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
                    confirm_box.add_widget(Label(
                        text=f"Close {symbol} with a MARKET SELL using real MEXC funds?",
                        halign="center",
                    ))
                    row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
                    yes = Button(text="SELL NOW")
                    no = Button(text="CANCEL")
                    row.add_widget(yes); row.add_widget(no)
                    confirm_box.add_widget(row)
                    confirm = Popup(title="CONFIRM REAL SELL", content=confirm_box, size_hint=(0.90, 0.34), auto_dismiss=False)

                    def do_sell(*_):
                        confirm.dismiss()
                        self.emit("event", f"MANUAL SELL REQUESTED {symbol}")
                        def worker():
                            try:
                                result = engine.close(symbol, "MANUAL")
                                order_id = (result or {}).get("order", {}).get("orderId", "")
                                Clock.schedule_once(lambda *_: self.emit("event", f"MANUAL SELL {symbol} | order={order_id}"), 0)
                                Clock.schedule_once(lambda *_: render(), 0)
                            except Exception as exc:
                                Clock.schedule_once(lambda *_: self.emit("error", f"MANUAL SELL FAILED {symbol}: {exc}"), 0)
                                Clock.schedule_once(lambda *_: render(), 0)
                        threading.Thread(target=worker, daemon=True).start()

                    yes.bind(on_release=do_sell)
                    no.bind(on_release=lambda *_: confirm.dismiss())
                    confirm.open()

                close_one.bind(on_release=sell)
                card.add_widget(close_one)
                trades_box.add_widget(card)

        refresh_btn.bind(on_release=render)
        close_btn.bind(on_release=lambda *_: popup.dismiss())
        popup.open()
        render()

    def stop(self):
        self.controller.stop(); self.status.text = "STOPPING..."

    def refresh(self):
        try:
            c = self.collect(); save_config(c)
            # create engine with current API settings without arming live orders
            settings.mexc_api_key = c["mexc_api_key"]; settings.mexc_api_secret = c["mexc_api_secret"]
            settings.trading_mode = TradingMode.LIVE
            settings.live_trading_enabled = False
            settings.live_runtime_armed = False
            settings.live_trading_confirm = ""
            self.controller.live_engine = LiveSpotEngine()
            data = self.controller.live_engine.account_snapshot()
            self.emit("account", data)
        except Exception as exc:
            self.status.text = f"BALANCE ERROR: {exc}"

    def emit(self, kind, data):
        Clock.schedule_once(lambda _dt: self._emit_ui(kind, data), 0)

    def _emit_ui(self, kind, data):
        if kind == "status": self.status.text = str(data)
        elif kind == "error": self.status.text = f"ERROR: {data}"
        elif kind == "account":
            self.account_labels["USDT available"].text = f"{float(data.get('usdt_free',0)):.4f}"
            self.account_labels["USDT total"].text = f"{float(data.get('usdt_total',0)):.4f}"
            self.account_labels["Can Trade"].text = str(data.get("canTrade"))
            self.account_labels["API permission"].text = str(data.get("permissions", []))
        elif kind == "row":
            txt = f"{data['symbol']} | score {data['score']:.1f} | {data['price']:.8f} | {data['state']}"
            lab = Label(text=txt, size_hint_y=None, height=dp(28))
            self.signal_box.add_widget(lab, index=0)
            while len(self.signal_box.children) > 12:
                self.signal_box.remove_widget(self.signal_box.children[-1])
        elif kind == "event":
            lines = (self.events.text.splitlines() if self.events.text else [])
            lines.insert(0, time.strftime("%H:%M:%S ") + str(data))
            self.events.text = "\n".join(lines[:30])


class MEXCSniperMobileApp(App):
    def build(self):
        self.title = "MEXC Sniper Mobile"
        return MobileUI()


if __name__ == "__main__":
    MEXCSniperMobileApp().run()

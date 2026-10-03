from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle, Rectangle
from kivy.metrics import dp
from kivy.properties import ColorProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.switch import Switch
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget


def is_android_platform() -> bool:
    return sys.platform == "android" or "ANDROID_ARGUMENT" in os.environ

from app.config import TradingMode, settings
from app.exchange.spot_client import SpotClient
from app.exchange.symbol_discovery import SymbolDiscovery
from app.exchange.websocket_manager import MEXCSpotWebSocketManager
from app.scanner.live_signal_scanner import LiveSignalScanner
from app.trading.live_engine import LiveSpotEngine

MOBILE_CONFIG = Path(
    os.environ.get(
        "MEXC_MOBILE_CONFIG",
        str(Path.home() / ".mexc_sniper_mobile.json"),
    )
)
SERVICE_STATE = MOBILE_CONFIG.with_name(".mexc_sniper_mobile_service_state.json")

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


def load_config() -> dict:
    data = dict(DEFAULTS)
    try:
        if MOBILE_CONFIG.exists():
            data.update(json.loads(MOBILE_CONFIG.read_text(encoding="utf-8")))
    except Exception:
        pass
    return data


def save_config(data: dict) -> None:
    MOBILE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = MOBILE_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(MOBILE_CONFIG)


# ---- Visual system -------------------------------------------------------
NAVY = (0.025, 0.055, 0.095, 1)
NAVY_2 = (0.040, 0.080, 0.135, 1)
PANEL = (0.050, 0.105, 0.165, 1)
PANEL_2 = (0.060, 0.125, 0.195, 1)
CYAN = (0.10, 0.88, 0.98, 1)
TEAL = (0.05, 0.72, 0.63, 1)
WHITE = (0.93, 0.97, 1.0, 1)
MUTED = (0.56, 0.66, 0.76, 1)
GREEN = (0.20, 0.88, 0.56, 1)
RED = (1.0, 0.30, 0.42, 1)
AMBER = (1.0, 0.70, 0.18, 1)
LINE = (0.10, 0.20, 0.30, 1)


def apply_bg(widget, color=PANEL, radius=16, border=None):
    with widget.canvas.before:
        Color(*color)
        widget._bg = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(radius)])
        if border:
            Color(*border)
            widget._border = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(radius)],
                                               segments=12, line_width=dp(1))
    def update(*_):
        widget._bg.pos = widget.pos
        widget._bg.size = widget.size
        if hasattr(widget, "_border"):
            widget._border.pos = widget.pos
            widget._border.size = widget.size
    widget.bind(pos=update, size=update)


class Card(BoxLayout):
    def __init__(self, color=PANEL, radius=16, **kwargs):
        super().__init__(**kwargs)
        apply_bg(self, color=color, radius=radius)


class PillButton(Button):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = TEAL
        self.color = WHITE
        self.bold = True
        self.font_size = "12sp"
        self.size_hint_y = None
        self.height = dp(42)


class SectionTitle(Label):
    def __init__(self, text, **kwargs):
        super().__init__(text=text, **kwargs)
        self.color = CYAN
        self.bold = True
        self.font_size = "15sp"
        self.size_hint_y = None
        self.height = dp(30)
        self.halign = "left"
        self.valign = "middle"
        self.text_size = (None, None)


class StatCard(Card):
    def __init__(self, title, value="—", accent=CYAN, **kwargs):
        super().__init__(orientation="vertical", padding=dp(12), spacing=dp(2), **kwargs)
        self.size_hint_y = None
        self.height = dp(84)
        title_lab = Label(text=title.upper(), color=MUTED, font_size="10sp", bold=True,
                          size_hint_y=None, height=dp(20), halign="left")
        self.value_label = Label(text=value, color=accent, font_size="20sp", bold=True,
                                 size_hint_y=None, height=dp(40), halign="left")
        self.add_widget(title_lab)
        self.add_widget(self.value_label)


class IconNavButton(Button):
    def __init__(self, title, **kwargs):
        super().__init__(text=title, **kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.color = MUTED
        self.bold = True
        self.font_size = "11sp"
        self.size_hint_y = None
        self.height = dp(46)

    def set_active(self, active: bool):
        self.color = CYAN if active else MUTED
        self.background_color = (0.08, 0.20, 0.29, 1) if active else (0, 0, 0, 0)


class MobileController:
    """Runs the scanner/network work away from the Kivy UI thread."""

    def __init__(self, emit):
        self.emit = emit
        self.thread = None
        self.stop_event = threading.Event()
        self.loop = None
        self.manager = None
        self.scanner = None
        self.live_engine = None
        self.prices: dict[str, float] = {}
        self.exchange_lock = threading.RLock()
        self.message_count = 0
        self.started_at = 0.0

    def start(self, cfg):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._thread, args=(dict(cfg),), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.loop and self.manager:
            try:
                asyncio.run_coroutine_threadsafe(self.manager.stop(), self.loop)
            except Exception:
                pass

    def _thread(self, cfg):
        self.started_at = time.time()
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
        settings.live_max_slippage_pct = float(c.get("live_max_slippage_pct", 0.30))
        settings.live_max_spread_pct = float(c.get("live_max_spread_pct", 0.20))
        settings.live_max_entry_drift_pct = float(c.get("live_max_entry_drift_pct", 0.30))
        settings.live_min_top_ask_coverage_pct = float(c.get("live_min_top_ask_coverage_pct", 50.0))
        settings.mexc_api_key = str(c.get("mexc_api_key", ""))
        settings.mexc_api_secret = str(c.get("mexc_api_secret", ""))
        settings.stablecoin_exclusion_enabled = bool(c.get("stablecoin_exclusion_enabled", True))

        self.emit("status", "CONNECTING")
        self.live_engine = None
        if settings.trading_mode == TradingMode.LIVE and settings.live_trading_enabled:
            with self.exchange_lock:
                self.live_engine = LiveSpotEngine()
                pre = await asyncio.to_thread(self.live_engine.preflight)
                account = await asyncio.to_thread(self.live_engine.account_snapshot)
                raw = account.get("_raw_account") or account
                imported = await asyncio.to_thread(self.live_engine.sync_account_positions, 1.0, raw)
            self.emit("account", account)
            if imported:
                self.emit("event", f"ACCOUNT SYNC • {len(imported)} LIVE HOLDINGS")
            self.emit("preflight", pre)
            self.emit("event", "LIVE GATE PASSED")
        else:
            # read-only engine still allows Account / Trades screens to work
            if settings.mexc_api_key and settings.mexc_api_secret:
                with self.exchange_lock:
                    self.live_engine = LiveSpotEngine()
                try:
                    account = await asyncio.to_thread(self.live_engine.account_snapshot)
                    raw = account.get("_raw_account") or account
                    imported = await asyncio.to_thread(self.live_engine.sync_account_positions, 1.0, raw)
                    self.emit("account", account)
                    if imported:
                        self.emit("event", f"ACCOUNT SYNC • {len(imported)} LIVE HOLDINGS")
                except Exception as exc:
                    self.emit("event", f"ACCOUNT READ ERROR: {exc}")

        strategies = {
            k: bool(c.get("strategy_" + k, True))
            for k in ("volume", "flow", "momentum", "book", "volatility", "liquidity")
        }
        self.scanner = LiveSignalScanner(
            strong_threshold=float(c.get("scanner_score_threshold", 65)),
            ready_threshold=float(c.get("scanner_ready_threshold", 55)),
            reset_threshold=float(c.get("scanner_reset_threshold", 50)),
            confirmations_required=int(c.get("scanner_confirmations", 1)),
            cooldown_seconds=float(c.get("scanner_cooldown_seconds", 20)),
            stale_after_ms=float(c.get("scanner_stale_after_ms", 5000)),
            paper_starting_balance=1000.0,
            paper_order_usdt=50.0,
            paper_stop_loss_pct=1.5,
            paper_take_profit_pct=3.0,
            paper_max_open_positions=5,
            paper_max_spread_pct=.40,
            paper_max_entry_drift_pct=.60,
            paper_min_top_ask_coverage_pct=25,
            enabled_strategies=strategies,
        )
        discovery = SymbolDiscovery(
            client=SpotClient(),
            limit=max(1, int(c.get("scanner_symbol_limit", 116))),
            stablecoin_exclusion_enabled=bool(c.get("stablecoin_exclusion_enabled", True)),
        )
        symbols = await discovery.discover()
        if not symbols:
            raise RuntimeError("No eligible Spot/USDT symbols were found")
        self.emit("status", f"ONLINE • {len(symbols)} SYMBOLS")

        async def on_message(wrapper):
            self.message_count += 1
            decisions = self.scanner.process_wrapper(wrapper)
            for snapshot, result, decision in decisions:
                self.prices[snapshot.symbol] = float(snapshot.price)
                self.emit("row", {
                    "symbol": snapshot.symbol,
                    "score": float(result.score),
                    "price": float(snapshot.price),
                    "state": decision.state.value,
                    "setup": result.setup,
                    "ready": bool(snapshot.ready),
                })
                if decision.should_alert and self.live_engine and snapshot.price > 0:
                    try:
                        with self.exchange_lock:
                            p = await asyncio.to_thread(
                                self.live_engine.open_long,
                                snapshot.symbol,
                                snapshot.price,
                                result.score,
                            )
                        if p:
                            self.emit("event", f"BUY {p.symbol} • {p.entry_order_id}")
                    except Exception as exc:
                        self.emit("event", f"BUY BLOCKED {snapshot.symbol} • {exc}")
                if self.live_engine and snapshot.price > 0:
                    try:
                        with self.exchange_lock:
                            closed = await asyncio.to_thread(
                                self.live_engine.update_price,
                                snapshot.symbol,
                                snapshot.price,
                            )
                        if closed:
                            self.emit("event", f"AUTO SELL {snapshot.symbol} • {closed.get('reason', '')}")
                    except Exception as exc:
                        self.emit("event", f"SELL CHECK ERROR {snapshot.symbol} • {exc}")

        self.manager = MEXCSpotWebSocketManager(
            symbols=[x.symbol for x in symbols],
            on_message=on_message,
            channels_per_connection=28,
            deal_interval="10ms",
            book_interval="100ms",
            ping_interval=20.0,
        )

        async def account_loop():
            # Keep the real-account view and imported holdings synchronized while
            # the service runs in the foreground/background.
            while not self.stop_event.is_set():
                try:
                    await asyncio.to_thread(self.refresh_account, True)
                except Exception as exc:
                    self.emit("event", f"ACCOUNT SYNC ERROR • {exc}")
                await asyncio.sleep(10.0)

        account_task = asyncio.create_task(account_loop(), name="mobile-account-sync")
        try:
            await self.manager.start()
        finally:
            account_task.cancel()
            await asyncio.gather(account_task, return_exceptions=True)

    def refresh_account(self, sync_positions=True):
        if not settings.mexc_api_key or not settings.mexc_api_secret:
            raise RuntimeError("Enter MEXC API key and secret first")
        with self.exchange_lock:
            if self.live_engine is None:
                self.live_engine = LiveSpotEngine()
            account = self.live_engine.account_snapshot()
            raw = account.get("_raw_account") or account
            imported = self.live_engine.sync_account_positions(1.0, raw) if sync_positions else []
        self.emit("account", account)
        if imported:
            self.emit("event", f"ACCOUNT SYNC • {len(imported)} LIVE HOLDINGS")
        return account

    def manual_sell(self, symbol: str):
        with self.exchange_lock:
            if self.live_engine is None:
                raise RuntimeError("LIVE engine is not initialized")
            result = self.live_engine.close(symbol, "MANUAL")
            return result


class MobileUI(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=0, padding=0, **kwargs)
        self.cfg = load_config()
        self.controller = MobileController(self.emit)
        self.fields = {}
        self.pages = {}
        self.nav_buttons = {}
        self.current_page = "Overview"
        self.last_error = ""
        self.account_data = {}
        self.signal_data = []
        self.event_lines: list[str] = []
        self.last_account_refresh = 0.0

        with self.canvas.before:
            Color(*NAVY)
            self._root_bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda *_: setattr(self._root_bg, "pos", self.pos),
                  size=lambda *_: setattr(self._root_bg, "size", self.size))

        self._build_header()
        self._build_nav()
        self._build_content()
        self._show_page("Overview")

        Clock.schedule_interval(self._clock_tick, 1.0)
        Clock.schedule_interval(self._auto_refresh, 12.0)
        Clock.schedule_interval(self._poll_background_state, 2.0)

    # Header ---------------------------------------------------------------
    def _build_header(self):
        header = BoxLayout(size_hint_y=None, height=dp(82), padding=(dp(18), dp(10)), spacing=dp(12))
        apply_bg(header, color=NAVY_2, radius=0)

        brand = BoxLayout(orientation="vertical", size_hint_x=.48, spacing=0)
        brand.add_widget(Label(text="MEXC", color=CYAN, bold=True, font_size="12sp",
                               size_hint_y=None, height=dp(18), halign="left"))
        brand.add_widget(Label(text="SNIPER MOBILE", color=WHITE, bold=True, font_size="23sp",
                               size_hint_y=None, height=dp(34), halign="left"))
        brand.add_widget(Label(text="SPOT • LIVE SIGNAL TERMINAL", color=MUTED, font_size="9sp",
                               size_hint_y=None, height=dp(16), halign="left"))
        header.add_widget(brand)

        self.status_chip = Label(text="OFFLINE", color=WHITE, bold=True, font_size="11sp",
                                 size_hint_x=.22, size_hint_y=None, height=dp(34))
        apply_bg(self.status_chip, color=(0.10, 0.15, 0.22, 1), radius=17)
        header.add_widget(self.status_chip)

        action = BoxLayout(spacing=dp(6), size_hint_x=.42)
        self.arm_button = PillButton(text="ARM LIVE")
        self.arm_button.background_color = AMBER
        self.arm_button.bind(on_release=self._toggle_arm)
        self.start_button = PillButton(text="START BG" if is_android_platform() else "START")
        self.start_button.bind(on_release=lambda *_: self.start())
        self.stop_button = PillButton(text="STOP")
        self.stop_button.background_color = RED
        self.stop_button.bind(on_release=lambda *_: self.stop())
        action.add_widget(self.arm_button)
        action.add_widget(self.start_button)
        action.add_widget(self.stop_button)
        header.add_widget(action)
        self.add_widget(header)

    def _build_nav(self):
        nav = BoxLayout(size_hint_y=None, height=dp(52), padding=(dp(8), dp(5)), spacing=dp(4))
        apply_bg(nav, color=(0.03, 0.07, 0.115, 1), radius=0)
        for name in ("Overview", "LIVE Trades", "Signals", "Settings", "Activity"):
            btn = IconNavButton(name.upper())
            btn.bind(on_release=lambda _b, page=name: self._show_page(page))
            self.nav_buttons[name] = btn
            nav.add_widget(btn)
        self.add_widget(nav)

    # Content --------------------------------------------------------------
    def _build_content(self):
        self.content_host = BoxLayout(orientation="vertical")
        self.add_widget(self.content_host)
        self.pages["Overview"] = self._page_overview()
        self.pages["LIVE Trades"] = self._page_live_trades()
        self.pages["Signals"] = self._page_signals()
        self.pages["Settings"] = self._page_settings()
        self.pages["Activity"] = self._page_activity()

    def _show_page(self, page):
        self.current_page = page
        self.content_host.clear_widgets()
        self.content_host.add_widget(self.pages[page])
        for name, btn in self.nav_buttons.items():
            btn.set_active(name == page)
        if page == "LIVE Trades":
            self._request_account_refresh(sync=True)

    def _scroll_page(self, inner):
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(4))
        inner.bind(minimum_height=inner.setter("height"))
        scroll.add_widget(inner)
        return scroll

    def _page_overview(self):
        root = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(14), size_hint_y=None)

        stats = GridLayout(cols=4, spacing=dp(10), size_hint_y=None, height=dp(84))
        self.stat_usdt_free = StatCard("USDT Available")
        self.stat_usdt_total = StatCard("USDT Total")
        self.stat_open = StatCard("Open LIVE", accent=AMBER)
        self.stat_mode = StatCard("Execution", value="PAPER / LOCKED", accent=RED)
        for w in (self.stat_usdt_free, self.stat_usdt_total, self.stat_open, self.stat_mode):
            stats.add_widget(w)
        root.add_widget(stats)

        root.add_widget(SectionTitle("LIVE CONTROL CENTER"))
        control = Card(orientation="vertical", padding=dp(14), spacing=dp(8), size_hint_y=None, height=dp(148))
        self.overview_gate = Label(text="LIVE gate: DISARMED", color=MUTED, bold=True,
                                   size_hint_y=None, height=dp(24), halign="left")
        control.add_widget(self.overview_gate)
        self.overview_info = Label(text="Configure API and settings, then ARM LIVE before starting real execution.",
                                   color=WHITE, font_size="11sp", halign="left", valign="middle")
        control.add_widget(self.overview_info)
        row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        b_refresh = PillButton(text="REFRESH ACCOUNT")
        b_refresh.bind(on_release=lambda *_: self._request_account_refresh(sync=True))
        b_trades = PillButton(text="OPEN REAL TRADES")
        b_trades.background_color = PANEL_2
        b_trades.bind(on_release=lambda *_: self._show_page("LIVE Trades"))
        row.add_widget(b_refresh)
        row.add_widget(b_trades)
        control.add_widget(row)
        root.add_widget(control)

        root.add_widget(SectionTitle("TOP SIGNALS"))
        sig_card = Card(orientation="vertical", padding=dp(10), spacing=dp(5), size_hint_y=None, height=dp(310))
        self.overview_signal_box = BoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None)
        self.overview_signal_box.bind(minimum_height=self.overview_signal_box.setter("height"))
        sig_scroll = ScrollView(do_scroll_x=False, bar_width=dp(4))
        sig_scroll.add_widget(self.overview_signal_box)
        sig_card.add_widget(sig_scroll)
        root.add_widget(sig_card)
        root.add_widget(Widget(size_hint_y=None, height=dp(8)))
        return self._scroll_page(root)

    def _page_live_trades(self):
        root = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(14), size_hint_y=None)
        stats = GridLayout(cols=4, spacing=dp(10), size_hint_y=None, height=dp(84))
        self.live_free = StatCard("USDT Available")
        self.live_total = StatCard("USDT Total")
        self.live_count = StatCard("Open LIVE", accent=AMBER)
        self.live_account = StatCard("Account", value="—", accent=CYAN)
        for w in (self.live_free, self.live_total, self.live_count, self.live_account):
            stats.add_widget(w)
        root.add_widget(stats)

        bar = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        refresh = PillButton(text="SYNC MEXC ACCOUNT")
        refresh.bind(on_release=lambda *_: self._request_account_refresh(sync=True))
        bar.add_widget(refresh)
        root.add_widget(bar)

        root.add_widget(SectionTitle("REAL POSITIONS"))
        self.live_positions_box = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        self.live_positions_box.bind(minimum_height=self.live_positions_box.setter("height"))
        pos_scroll = ScrollView(do_scroll_x=False, bar_width=dp(4), size_hint_y=None, height=dp(545))
        pos_scroll.add_widget(self.live_positions_box)
        root.add_widget(pos_scroll)
        self.live_empty = Label(text="No synchronized real holdings.", color=MUTED,
                                size_hint_y=None, height=dp(40))
        self.live_positions_box.add_widget(self.live_empty)
        return self._scroll_page(root)

    def _page_signals(self):
        root = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(14), size_hint_y=None)
        root.add_widget(SectionTitle("LIVE SIGNAL MONITOR"))
        self.signal_box = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None)
        self.signal_box.bind(minimum_height=self.signal_box.setter("height"))
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(4), size_hint_y=None, height=dp(580))
        scroll.add_widget(self.signal_box)
        root.add_widget(scroll)
        return self._scroll_page(root)

    def _page_settings(self):
        root = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(14), size_hint_y=None)
        root.add_widget(SectionTitle("ACCOUNT & LIVE EXECUTION"))

        grid = GridLayout(cols=2, spacing=dp(7), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        fields = [
            ("mexc_api_key", "MEXC API KEY", False),
            ("mexc_api_secret", "MEXC API SECRET", True),
            ("live_order_usdt", "ORDER USDT", False),
            ("live_hard_max_order_usdt", "MAX ORDER USDT", False),
            ("live_max_open_positions", "MAX OPEN POSITIONS", False),
            ("live_stop_loss_pct", "STOP LOSS %", False),
            ("live_take_profit_pct", "TAKE PROFIT %", False),
            ("live_max_slippage_pct", "MAX SLIPPAGE %", False),
            ("live_max_spread_pct", "MAX SPREAD %", False),
            ("live_max_entry_drift_pct", "MAX ENTRY DRIFT %", False),
            ("live_min_top_ask_coverage_pct", "MIN ASK COVERAGE %", False),
            ("scanner_symbol_limit", "SCANNER SYMBOLS", False),
            ("scanner_score_threshold", "SCORE THRESHOLD", False),
            ("scanner_ready_threshold", "READY THRESHOLD", False),
            ("scanner_reset_threshold", "RESET THRESHOLD", False),
            ("scanner_confirmations", "CONFIRMATIONS", False),
            ("scanner_cooldown_seconds", "COOLDOWN SEC", False),
            ("scanner_stale_after_ms", "STALE AFTER MS", False),
        ]
        for key, label, pwd in fields:
            self._field(grid, key, label, pwd)
        root.add_widget(grid)

        root.add_widget(SectionTitle("STRATEGY & SAFETY"))
        toggles = GridLayout(cols=2, spacing=dp(7), size_hint_y=None)
        toggles.bind(minimum_height=toggles.setter("height"))
        for key, label in [
            ("live_trading_enabled", "ENABLE LIVE ENGINE"),
            ("live_runtime_armed", "ARM LIVE RUNTIME"),
            ("stablecoin_exclusion_enabled", "EXCLUDE STABLECOINS"),
            ("strategy_volume", "VOLUME"),
            ("strategy_flow", "BUY FLOW"),
            ("strategy_momentum", "MOMENTUM"),
            ("strategy_book", "ORDER BOOK"),
            ("strategy_volatility", "VOLATILITY"),
            ("strategy_liquidity", "LIQUIDITY / SPREAD"),
        ]:
            box = Card(orientation="horizontal", padding=(dp(10), dp(5)), spacing=dp(6),
                       size_hint_y=None, height=dp(46), color=PANEL_2)
            box.add_widget(Label(text=label, color=WHITE, font_size="10sp"))
            sw = Switch(active=bool(self.cfg.get(key, False)), size_hint_x=None, width=dp(62))
            self.fields[key] = sw
            box.add_widget(sw)
            toggles.add_widget(box)
        root.add_widget(toggles)

        root.add_widget(SectionTitle("LIVE CONFIRMATION"))
        self.confirm = TextInput(text=self.cfg.get("live_trading_confirm", ""), multiline=False,
                                 hint_text="I_UNDERSTAND_REAL_MONEY", password=False,
                                 background_normal="", background_color=PANEL_2,
                                 foreground_color=WHITE, hint_text_color=MUTED,
                                 size_hint_y=None, height=dp(44), padding=(dp(12), dp(10)))
        self.fields["live_trading_confirm"] = self.confirm
        root.add_widget(self.confirm)

        action = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        save = PillButton(text="SAVE SETTINGS")
        save.bind(on_release=lambda *_: self.save())
        reset = PillButton(text="RESET DEFAULTS")
        reset.background_color = PANEL_2
        reset.bind(on_release=lambda *_: self._reset_defaults())
        action.add_widget(save)
        action.add_widget(reset)
        root.add_widget(action)

        note = Label(text="LIVE orders remain fail-closed: account permission, balance, spread, slippage, depth and exchange symbol limits are checked before BUY.",
                     color=MUTED, font_size="10sp", halign="left", valign="top", size_hint_y=None, height=dp(58))
        root.add_widget(note)
        return self._scroll_page(root)

    def _page_activity(self):
        root = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(14), size_hint_y=None)
        root.add_widget(SectionTitle("ACTIVITY LOG"))
        card = Card(orientation="vertical", padding=dp(10), spacing=dp(5), size_hint_y=None, height=dp(520))
        self.activity_label = Label(text="", color=WHITE, font_size="10sp", halign="left", valign="top")
        self.activity_label.bind(texture_size=lambda *_: setattr(self.activity_label, "size", self.activity_label.texture_size))
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(4))
        scroll.add_widget(self.activity_label)
        card.add_widget(scroll)
        root.add_widget(card)
        clear = PillButton(text="CLEAR LOG")
        clear.bind(on_release=lambda *_: self._clear_log())
        root.add_widget(clear)
        return self._scroll_page(root)

    # Settings helpers ----------------------------------------------------
    def _field(self, grid, key, label, password=False):
        lab = Label(text=label, color=MUTED, font_size="10sp", bold=True,
                    size_hint_y=None, height=dp(42), halign="left", valign="middle")
        lab.text_size = (None, dp(42))
        box = TextInput(text=str(self.cfg.get(key, "")), multiline=False, password=password,
                        background_normal="", background_color=PANEL_2,
                        foreground_color=WHITE, cursor_color=CYAN,
                        hint_text_color=MUTED, font_size="12sp",
                        size_hint_y=None, height=dp(42), padding=(dp(10), dp(10)))
        self.fields[key] = box
        grid.add_widget(lab)
        grid.add_widget(box)

    def _reset_defaults(self):
        self.cfg = dict(DEFAULTS)
        for key, widget in self.fields.items():
            if isinstance(widget, Switch):
                widget.active = bool(self.cfg.get(key, False))
            elif hasattr(widget, "text"):
                widget.text = str(self.cfg.get(key, ""))
        self._log("Settings reset to defaults")

    # Actions --------------------------------------------------------------
    def collect(self):
        data = dict(self.cfg)
        for key, widget in self.fields.items():
            if isinstance(widget, Switch):
                data[key] = bool(widget.active)
            else:
                data[key] = widget.text
        numeric = [
            "live_order_usdt", "live_hard_max_order_usdt", "live_stop_loss_pct",
            "live_take_profit_pct", "live_max_slippage_pct", "live_max_spread_pct",
            "live_max_entry_drift_pct", "live_min_top_ask_coverage_pct",
            "scanner_score_threshold", "scanner_ready_threshold", "scanner_reset_threshold",
            "scanner_cooldown_seconds", "scanner_stale_after_ms",
        ]
        ints = ["live_max_open_positions", "scanner_symbol_limit", "scanner_confirmations"]
        for k in numeric:
            data[k] = float(data[k])
        for k in ints:
            data[k] = int(float(data[k]))
        data["trading_mode"] = "LIVE"
        data["trading_env"] = "live"
        return data

    def save(self):
        try:
            self.cfg = self.collect()
            save_config(self.cfg)
            self._log("SETTINGS SAVED")
            self.status_chip.text = "SAVED"
        except Exception as exc:
            self._log(f"SAVE ERROR • {exc}")
            self.status_chip.text = "SAVE ERROR"

    def _toggle_arm(self, *_):
        armed = not bool(self.cfg.get("live_runtime_armed", False))
        if armed:
            if str(self.cfg.get("live_trading_confirm", "")) != LiveSpotEngine.CONFIRMATION:
                self._popup_message("LIVE ARM", "Enter the exact confirmation phrase in Settings first.")
                return
            self.cfg["live_trading_enabled"] = True
            self.cfg["live_runtime_armed"] = True
            self.arm_button.text = "DISARM LIVE"
            self.arm_button.background_color = RED
            self._log("LIVE RUNTIME ARMED")
        else:
            self.cfg["live_runtime_armed"] = False
            self.arm_button.text = "ARM LIVE"
            self.arm_button.background_color = AMBER
            self._log("LIVE RUNTIME DISARMED")
        save_config(self.cfg)
        self.overview_gate.text = "LIVE gate: ARMED" if armed else "LIVE gate: DISARMED"
        self.overview_gate.color = GREEN if armed else MUTED

    def start(self):
        try:
            self.cfg = self.collect()
            save_config(self.cfg)
            if self.cfg["live_runtime_armed"] and self.cfg["live_trading_enabled"]:
                if self.cfg["live_trading_confirm"] != LiveSpotEngine.CONFIRMATION:
                    raise RuntimeError("LIVE confirmation is incorrect")
            if is_android_platform():
                self._start_background_service()
            else:
                self.controller.start(self.cfg)
            self._log("BACKGROUND ENGINE START REQUESTED" if is_android_platform() else "ENGINE START REQUESTED")
            self.start_button.text = "RUNNING BG" if is_android_platform() else "RUNNING"
            self.start_button.background_color = TEAL
        except Exception as exc:
            self._log(f"START ERROR • {exc}")
            self._popup_message("START ERROR", str(exc))

    def stop(self):
        try:
            if is_android_platform():
                self._stop_background_service()
                self._log("BACKGROUND ENGINE STOP REQUESTED")
                self.start_button.text = "START BG"
                self.start_button.background_color = TEAL
            else:
                self.controller.stop()
                self._log("ENGINE STOP REQUESTED")
                self.start_button.text = "START"
        except Exception as exc:
            self._log(f"STOP ERROR • {exc}")

    def _start_background_service(self):
        from jnius import autoclass
        service = autoclass("org.mexcsniper.mexcsniper.ServiceSniperd")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([Permission.POST_NOTIFICATIONS])
        except Exception:
            pass
        service.start(activity, "mexc")

    def _stop_background_service(self):
        from jnius import autoclass
        service = autoclass("org.mexcsniper.mexcsniper.ServiceSniperd")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        service.stop(activity, "mexc")

    def _load_service_state(self):
        try:
            if not SERVICE_STATE.exists():
                return {}
            return json.loads(SERVICE_STATE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _apply_service_state(self, state):
        if not state:
            return
        status = state.get("status")
        if status:
            self.status_chip.text = str(status)[:24]
        account = state.get("account")
        if isinstance(account, dict):
            self.account_data = account
        events = state.get("events")
        if isinstance(events, list):
            self.event_lines = [str(x) for x in events][-80:]
        rows = state.get("rows")
        if isinstance(rows, list):
            self.signal_data = rows[-100:]
        self._refresh_live_positions_view()
        if self.cfg.get("live_runtime_armed") and status and "ONLINE" in str(status):
            self.start_button.text = "RUNNING BG" if is_android_platform() else "RUNNING"
            self.start_button.background_color = TEAL

    def _poll_background_state(self, *_):
        if is_android_platform():
            self._apply_service_state(self._load_service_state())

    def _request_account_refresh(self, sync=True):
        self.status_chip.text = "SYNCING"
        self._log("ACCOUNT REFRESH REQUESTED")
        def worker():
            try:
                self.controller.refresh_account(sync_positions=sync)
                Clock.schedule_once(lambda *_: self._refresh_live_positions_view(), 0)
            except Exception as exc:
                Clock.schedule_once(lambda *_: self.emit("error", f"ACCOUNT SYNC FAILED • {exc}"), 0)
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_live_positions_view(self):
        self._render_account_cards()
        self._render_live_positions()

    # Account / trades ----------------------------------------------------
    def _render_account_cards(self):
        free = float(self.account_data.get("usdt_free", 0) or 0)
        total = float(self.account_data.get("usdt_total", 0) or 0)
        positions = list(self.controller.live_engine.positions.values()) if self.controller.live_engine else []
        can_trade = self.account_data.get("canTrade")
        acct = self.account_data.get("accountType") or "—"
        self.stat_usdt_free.value_label.text = f"{free:.4f}"
        self.stat_usdt_total.value_label.text = f"{total:.4f}"
        self.stat_open.value_label.text = str(len(positions))
        self.stat_mode.value_label.text = "LIVE / ARMED" if self.cfg.get("live_runtime_armed") else "LIVE / LOCKED"
        self.live_free.value_label.text = f"{free:.4f}"
        self.live_total.value_label.text = f"{total:.4f}"
        self.live_count.value_label.text = str(len(positions))
        self.live_account.value_label.text = "OK" if can_trade else acct
        self.overview_gate.text = "LIVE gate: ARMED" if self.cfg.get("live_runtime_armed") else "LIVE gate: DISARMED"
        self.overview_gate.color = GREEN if self.cfg.get("live_runtime_armed") else MUTED

    def _render_live_positions(self):
        self.live_positions_box.clear_widgets()
        engine = self.controller.live_engine
        if engine is None:
            self.live_positions_box.add_widget(Label(text="Connect the account first.", color=MUTED,
                                                     size_hint_y=None, height=dp(40)))
            return
        positions = sorted(engine.positions.values(), key=lambda p: p.symbol)
        if not positions:
            self.live_positions_box.add_widget(Label(text="No synchronized real holdings.", color=MUTED,
                                                     size_hint_y=None, height=dp(40)))
            return
        for pos in positions:
            current = float(self.controller.prices.get(pos.symbol, pos.entry_price))
            pnl_pct = ((current - pos.entry_price) / pos.entry_price * 100.0) if pos.entry_price else 0.0
            pnl_usdt = (current - pos.entry_price) * pos.quantity if pos.entry_price else 0.0
            synced = pos.entry_order_id == "ACCOUNT_SYNC"
            card = Card(orientation="vertical", padding=dp(12), spacing=dp(6), size_hint_y=None, height=dp(188),
                        color=PANEL_2)
            top = BoxLayout(size_hint_y=None, height=dp(30))
            top.add_widget(Label(text=pos.symbol, color=WHITE, bold=True, font_size="18sp", halign="left"))
            src = Label(text="ACCOUNT SYNC" if synced else "LIVE TRADE", color=AMBER if synced else GREEN,
                        bold=True, font_size="10sp", halign="right")
            top.add_widget(src)
            card.add_widget(top)
            card.add_widget(Label(text=f"QTY  {pos.quantity:.10f}    ENTRY  {pos.entry_price:.10f}",
                                  color=MUTED, font_size="10sp", halign="left", size_hint_y=None, height=dp(20)))
            pnl_color = GREEN if pnl_usdt >= 0 else RED
            card.add_widget(Label(text=f"CURRENT  {current:.10f}     P/L  {pnl_usdt:+.6f} USDT  ({pnl_pct:+.3f}%)",
                                  color=pnl_color, font_size="11sp", bold=True, size_hint_y=None, height=dp(24)))
            if synced:
                sltp = "SL / TP  reference unavailable for pre-existing holding"
            else:
                sltp = f"SL  {pos.stop_loss:.10f}    TP  {pos.take_profit:.10f}"
            card.add_widget(Label(text=sltp, color=MUTED, font_size="10sp", size_hint_y=None, height=dp(20)))
            card.add_widget(Label(text=f"ORDER  {pos.entry_order_id}", color=MUTED, font_size="9sp",
                                  size_hint_y=None, height=dp(18)))
            sell = PillButton(text=f"SELL {pos.symbol} NOW")
            sell.background_color = RED
            sell.bind(on_release=lambda _b, symbol=pos.symbol: self._confirm_sell(symbol))
            card.add_widget(sell)
            self.live_positions_box.add_widget(card)

    def _confirm_sell(self, symbol):
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(16))
        content.add_widget(Label(text=f"MARKET SELL {symbol}\n\nThis sends a REAL order to MEXC.",
                                  color=WHITE, halign="center", valign="middle"))
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        yes = PillButton(text="SELL NOW")
        yes.background_color = RED
        no = PillButton(text="CANCEL")
        no.background_color = PANEL_2
        row.add_widget(yes)
        row.add_widget(no)
        content.add_widget(row)
        popup = Popup(title="CONFIRM REAL SELL", content=content, size_hint=(.88, .35), auto_dismiss=False)

        def do_sell(*_):
            popup.dismiss()
            self._log(f"MANUAL SELL REQUESTED • {symbol}")
            def worker():
                try:
                    result = self.controller.manual_sell(symbol)
                    order_id = (result or {}).get("order", {}).get("orderId", "")
                    self.emit("event", f"MANUAL SELL OK • {symbol} • {order_id}")
                    self.controller.refresh_account(sync_positions=True)
                except Exception as exc:
                    self.emit("error", f"MANUAL SELL FAILED • {symbol} • {exc}")
                finally:
                    Clock.schedule_once(lambda *_: self._refresh_live_positions_view(), 0)
            threading.Thread(target=worker, daemon=True).start()

        yes.bind(on_release=do_sell)
        no.bind(on_release=lambda *_: popup.dismiss())
        popup.open()

    # Signal view ---------------------------------------------------------
    def _render_signal_row(self, data):
        line = Card(orientation="horizontal", padding=(dp(10), dp(4)), spacing=dp(8),
                    size_hint_y=None, height=dp(52), color=PANEL_2)
        line.add_widget(Label(text=data["symbol"], color=WHITE, bold=True, font_size="12sp", size_hint_x=.22))
        score = float(data["score"])
        score_color = GREEN if score >= self.cfg.get("scanner_score_threshold", 65) else AMBER
        line.add_widget(Label(text=f"{score:.1f}", color=score_color, bold=True, size_hint_x=.12))
        line.add_widget(Label(text=f"{float(data['price']):.8g}", color=WHITE, size_hint_x=.26))
        line.add_widget(Label(text=data["state"], color=CYAN, bold=True, size_hint_x=.18))
        line.add_widget(Label(text=data["setup"], color=MUTED, font_size="9sp", size_hint_x=.22))
        return line

    # UI events -----------------------------------------------------------
    def emit(self, kind, data):
        Clock.schedule_once(lambda _dt: self._emit_ui(kind, data), 0)

    def _emit_ui(self, kind, data):
        if kind == "status":
            self.status_chip.text = str(data)
            if "ONLINE" in str(data) or "READY" in str(data):
                self.status_chip.color = GREEN
            elif "STOP" in str(data):
                self.status_chip.color = MUTED
            else:
                self.status_chip.color = AMBER
        elif kind == "error":
            self.status_chip.text = "ERROR"
            self.status_chip.color = RED
            self._log(str(data), error=True)
        elif kind == "account":
            self.account_data = dict(data)
            self.last_account_refresh = time.time()
            self._render_account_cards()
            self._render_live_positions()
            perms = ", ".join(map(str, data.get("permissions", []))) or "none"
            self._log(f"ACCOUNT • canTrade={data.get('canTrade')} • permissions={perms}")
        elif kind == "preflight":
            self._log(f"PREFLIGHT OK • order={data.get('live_order_usdt')} • max={data.get('hard_max_order_usdt')}")
        elif kind == "row":
            self.signal_data.insert(0, dict(data))
            self.signal_data = self.signal_data[:30]
            self.signal_box.clear_widgets()
            self.overview_signal_box.clear_widgets()
            for row in self.signal_data[:20]:
                self.signal_box.add_widget(self._render_signal_row(row))
            for row in self.signal_data[:6]:
                self.overview_signal_box.add_widget(self._render_signal_row(row))
        elif kind == "event":
            self._log(str(data))
        self._update_armed_visuals()

    def _clock_tick(self, *_):
        armed = bool(self.cfg.get("live_runtime_armed", False))
        self._update_armed_visuals(armed)

    def _auto_refresh(self, *_):
        if self.controller.live_engine and self.controller.thread and self.controller.thread.is_alive():
            if time.time() - self.last_account_refresh >= 10:
                self._request_account_refresh(sync=True)

    def _update_armed_visuals(self, armed=None):
        if armed is None:
            armed = bool(self.cfg.get("live_runtime_armed", False))
        self.arm_button.text = "DISARM LIVE" if armed else "ARM LIVE"
        self.arm_button.background_color = RED if armed else AMBER
        self.stat_mode.value_label.text = "LIVE / ARMED" if armed else "LIVE / LOCKED"
        self.overview_gate.text = "LIVE gate: ARMED" if armed else "LIVE gate: DISARMED"
        self.overview_gate.color = GREEN if armed else MUTED

    def _log(self, message: str, error=False):
        stamp = time.strftime("%H:%M:%S")
        prefix = "ERROR" if error else "INFO"
        self.event_lines.insert(0, f"{stamp}  {prefix:<5}  {message}")
        self.event_lines = self.event_lines[:120]
        if hasattr(self, "activity_label"):
            self.activity_label.text = "\n".join(self.event_lines)

    def _clear_log(self):
        self.event_lines.clear()
        self.activity_label.text = ""

    def _popup_message(self, title, message):
        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        content.add_widget(Label(text=message, color=WHITE, halign="center", valign="middle"))
        ok = PillButton(text="OK")
        content.add_widget(ok)
        popup = Popup(title=title, content=content, size_hint=(.86, .30))
        ok.bind(on_release=lambda *_: popup.dismiss())
        popup.open()


class MEXCSniperMobileApp(App):
    title = "MEXC Sniper Mobile"

    def build(self):
        return MobileUI()


if __name__ == "__main__":
    MEXCSniperMobileApp().run()

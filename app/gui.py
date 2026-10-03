from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
import sys
import os
import csv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import TradingMode, settings
from app.storage.database import Database
from app.exchange.spot_client import SpotClient
from app.exchange.symbol_discovery import SymbolDiscovery
from app.exchange.websocket_manager import MEXCSpotWebSocketManager
from app.scanner.live_signal_scanner import LiveSignalScanner
from app.trading.live_engine import LiveSpotEngine

# Keep console output quiet: the GUI is the primary monitoring surface.
logging.getLogger("mexc.websocket").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

BG = "#07111f"
PANEL = "#0b1728"
PANEL2 = "#0e1d31"
BORDER = "#17385b"
TEXT = "#dcecff"
MUTED = "#7895b5"
CYAN = "#00d9ff"
GREEN = "#00d68f"
YELLOW = "#f6c84c"
RED = "#ff5577"
PURPLE = "#8d7cff"


def price_fmt(price: float) -> str:
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:.4f}"
    return f"{price:.8f}"


class EngineController:
    """Owns the real async market pipeline behind the Tk GUI."""

    def __init__(self, state_queue: queue.Queue, config: dict | None = None):
        self.q = state_queue
        self.config = config or {}
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.manager: MEXCSpotWebSocketManager | None = None
        self.scanner: LiveSignalScanner | None = None
        self.running = False
        self.stop_requested = False
        self.symbol_count = 0
        self._prices: dict[str, float] = {}
        self.live_engine: LiveSpotEngine | None = None
        self._last_diag_emit = 0.0

    def start(self):
        if self.running:
            return
        self.stop_requested = False
        self.thread = threading.Thread(target=self._thread_main, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_requested = True
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: None)

    def _thread_main(self):
        self.running = True
        try:
            asyncio.run(self._run())
        except asyncio.CancelledError:
            # Expected during an explicit GUI stop.
            pass
        except Exception as exc:
            logging.exception("Engine failure")
            self.q.put(("error", repr(exc)))
        finally:
            self.running = False
            self.q.put(("stopped", None))

    async def _run(self):
        self.loop = asyncio.get_running_loop()
        c = self.config

        # Synchronize GUI configuration into the shared Settings object before
        # constructing any scanner/execution objects.
        try:
            settings.trading_mode = TradingMode(str(c.get("trading_mode", "PAPER")).upper())
        except ValueError:
            settings.trading_mode = TradingMode.PAPER
        settings.trading_env = str(c.get("trading_env", "paper"))
        settings.live_runtime_armed = bool(c.get("live_runtime_armed", False))
        settings.live_trading_enabled = (
            bool(c.get("live_trading_enabled", False))
            and settings.live_runtime_armed
        )
        settings.live_trading_confirm = str(c.get("live_trading_confirm", ""))
        settings.live_order_usdt = float(c.get("live_order_usdt", 10.0))
        settings.live_max_open_positions = int(c.get("live_max_open_positions", 1))
        settings.live_stop_loss_pct = float(c.get("live_stop_loss_pct", 1.5))
        settings.live_take_profit_pct = float(c.get("live_take_profit_pct", 3.0))
        settings.live_max_slippage_pct = float(c.get("live_max_slippage_pct", 0.30))
        settings.live_max_spread_pct = float(c.get("live_max_spread_pct", 0.20))
        settings.live_max_entry_drift_pct = float(c.get("live_max_entry_drift_pct", 0.30))
        settings.live_min_top_ask_coverage_pct = float(c.get("live_min_top_ask_coverage_pct", 50.0))
        settings.stablecoin_exclusion_enabled = bool(c.get("stablecoin_exclusion_enabled", True))
        settings.stablecoin_base_assets = str(c.get("stablecoin_base_assets", "USDT,USDC,USDS,USDE,USD1,USDD,DAI,FDUSD,TUSD,BUSD,PYUSD,GUSD,FRAX,LUSD,SUSD,USDP,USTC,UST,CRVUSD,EURC,EURT,EURS,USDX,USDXL"))
        settings.mexc_api_key = str(c.get("mexc_api_key", ""))
        settings.mexc_api_secret = str(c.get("mexc_api_secret", ""))

        self.live_engine = None
        if settings.trading_mode == TradingMode.LIVE and settings.live_trading_enabled:
            self.live_engine = LiveSpotEngine()
            try:
                preflight = await asyncio.to_thread(self.live_engine.preflight)
                self.q.put(("live", {"event": "PREFLIGHT_OK", "data": preflight}))
            except Exception as exc:
                self.live_engine = None
                self.q.put(("live", {"event": "PREFLIGHT_FAILED", "error": str(exc)}))
                raise RuntimeError(f"LIVE preflight failed: {exc}") from exc

        strategies = {
            "volume": c.get("strategy_volume", True),
            "flow": c.get("strategy_flow", True),
            "momentum": c.get("strategy_momentum", True),
            "book": c.get("strategy_book", True),
            "volatility": c.get("strategy_volatility", True),
            "liquidity": c.get("strategy_liquidity", True),
        }
        self.scanner = LiveSignalScanner(
            strong_threshold=float(c.get("scanner_score_threshold", 80.0)),
            ready_threshold=float(c.get("scanner_ready_threshold", 70.0)),
            reset_threshold=float(c.get("scanner_reset_threshold", 60.0)),
            confirmations_required=int(c.get("scanner_confirmations", 2)),
            cooldown_seconds=float(c.get("scanner_cooldown_seconds", 60.0)),
            stale_after_ms=float(c.get("scanner_stale_after_ms", 3000.0)),
            paper_starting_balance=float(c.get("paper_starting_balance", 1000.0)),
            paper_order_usdt=float(c.get("paper_order_usdt", 50.0)),
            paper_stop_loss_pct=float(c.get("paper_stop_loss_pct", 1.5)),
            paper_take_profit_pct=float(c.get("paper_take_profit_pct", 3.0)),
            paper_max_open_positions=int(c.get("paper_max_open_positions", 5)),
            paper_max_spread_pct=float(c.get("paper_max_spread_pct", 0.20)),
            paper_max_entry_drift_pct=float(c.get("paper_max_entry_drift_pct", 0.30)),
            paper_min_top_ask_coverage_pct=float(c.get("paper_min_top_ask_coverage_pct", 50.0)),
            enabled_strategies=strategies,
        )

        self.q.put(("status", {"phase": "discovering"}))
        discovery = SymbolDiscovery(client=SpotClient(), limit=max(1, int(c.get("scanner_symbol_limit", 116))),
                                     stablecoin_exclusion_enabled=bool(c.get("stablecoin_exclusion_enabled", True)),
                                     stablecoin_base_assets=c.get("stablecoin_base_assets", ""))
        symbols = await discovery.discover()
        if not symbols:
            raise RuntimeError("No eligible Spot/USDT symbols were found.")

        self.symbol_count = len(symbols)
        self.q.put(("status", {"phase": "starting", "symbols": len(symbols)}))

        async def on_message(wrapper):
            decisions = self.scanner.process_wrapper(wrapper)
            for snapshot, result, decision in decisions:
                self.q.put(("row", {
                    "symbol": snapshot.symbol,
                    "score": float(result.score),
                    "price": float(snapshot.price),
                    "pressure": float(snapshot.buy_pressure_5s),
                    "volume": float(snapshot.volume_acceleration),
                    "momentum": float(snapshot.price_change_5s_pct),
                    "imbalance": float(snapshot.book_imbalance),
                    "spread": float(snapshot.spread_pct),
                    "state": decision.state.value,
                    "setup": result.setup,
                    "ready": bool(snapshot.ready),
                    "reasons": list(result.reasons),
                    "components": {
                        "volume": result.volume_score,
                        "flow": result.flow_score,
                        "momentum": result.momentum_score,
                        "book": result.book_score,
                        "volatility": result.volatility_score,
                        "liquidity": result.liquidity_score,
                    },
                }))

                if decision.should_alert:
                    self.q.put(("signal", {
                        "time": time.time(),
                        "symbol": snapshot.symbol,
                        "score": float(result.score),
                        "setup": result.setup,
                        "state": decision.state.value,
                        "price": float(snapshot.price),
                        "pressure": float(snapshot.buy_pressure_5s),
                        "momentum": float(snapshot.price_change_5s_pct),
                        "reasons": list(result.reasons),
                    }))

                    # LIVE is opt-in and independently armed. Paper trading
                    # continues to run as the diagnostic baseline.
                    if self.live_engine is not None and snapshot.price > 0:
                        try:
                            position = await asyncio.to_thread(
                                self.live_engine.open_long,
                                snapshot.symbol,
                                snapshot.price,
                                result.score,
                            )
                            if position is not None:
                                self.q.put(("live", {
                                    "event": "BUY",
                                    "symbol": position.symbol,
                                    "price": position.entry_price,
                                    "score": position.entry_score,
                                    "order_id": position.entry_order_id,
                                }))
                        except Exception as exc:
                            self.q.put(("live", {"event": "BUY_FAILED", "symbol": snapshot.symbol, "error": str(exc)}))

                if self.live_engine is not None and snapshot.price > 0:
                    try:
                        closed = await asyncio.to_thread(
                            self.live_engine.update_price,
                            snapshot.symbol,
                            snapshot.price,
                        )
                        if closed is not None:
                            self.q.put(("live", {
                                "event": "SELL",
                                "symbol": snapshot.symbol,
                                "reason": closed.get("reason", ""),
                                "order_id": closed.get("order", {}).get("orderId", ""),
                            }))
                    except Exception as exc:
                        self.q.put(("live", {"event": "SELL_FAILED", "symbol": snapshot.symbol, "error": str(exc)}))

            for snapshot, result, decision in decisions:
                self._prices[snapshot.symbol] = float(snapshot.price)

            self.q.put(("paper", self._paper_snapshot()))
            for event in self.scanner.last_trade_events:
                self.q.put(("trade", event))

            now = time.monotonic()
            if now - self._last_diag_emit >= 1.0:
                self._last_diag_emit = now
                self.q.put(("diag", self._diagnostics()))

        self.manager = MEXCSpotWebSocketManager(
            symbols=[item.symbol for item in symbols],
            on_message=on_message,
            channels_per_connection=28,
            deal_interval="10ms",
            book_interval="100ms",
            ping_interval=20.0,
        )

        self.q.put(("status", {"phase": "starting_ws", "symbols": len(symbols)}))
        stopper = asyncio.create_task(self._stop_monitor())
        try:
            await self.manager.start()
        finally:
            stopper.cancel()
            await asyncio.gather(stopper, return_exceptions=True)
            if self.scanner is not None:
                try:
                    self.scanner.close()
                except Exception:
                    logging.exception("Failed to close persistent scanner journal")

    def _diagnostics(self) -> dict:
        if not self.scanner:
            return {}
        data = self.scanner.diagnostics()
        data["live_enabled"] = bool(self.live_engine and self.live_engine.enabled)
        data["live_positions"] = len(self.live_engine.positions) if self.live_engine else 0
        return data

    def _paper_snapshot(self) -> dict:
        if not self.scanner:
            return {}
        pt = self.scanner.paper_trader
        prices = dict(self._prices)
        return {
            "summary": pt.summary(prices),
            "signal_history": list(self.scanner.signal_history[-200:]),
            "positions": [
                {
                    "symbol": p.symbol,
                    "entry": p.entry_price,
                    "quantity": p.quantity,
                    "stop": p.stop_loss,
                    "take": p.take_profit,
                    "score": p.entry_score,
                    "setup": p.entry_setup,
                }
                for p in pt.positions.values()
            ],
            "closed": [
                {
                    "symbol": t.symbol,
                    "pnl": t.pnl_usdt,
                    "pnl_pct": t.pnl_pct,
                    "reason": t.reason,
                    "score": t.entry_score,
                    "setup": t.entry_setup,
                    "closed_at": t.closed_at,
                }
                for t in pt.closed_trades[-50:]
            ],
        }

    async def _stop_monitor(self):
        while True:
            await asyncio.sleep(0.2)
            if self.stop_requested and self.manager:
                await self.manager.stop()
                return


class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MEXC Sniper — Integrated Spot Signal Terminal")
        # Responsive initial size: fit common 1366x768 / 1280x800 displays.
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(1540, max(1180, sw - 40))
        height = min(940, max(700, sh - 70))
        self.geometry(f"{width}x{height}")
        self.minsize(1050, 650)
        self.configure(bg=BG)

        self.q: queue.Queue = queue.Queue()
        self.config = self._load_gui_config()
        self.controller = EngineController(self.q, self.config)
        self.rows: dict[str, dict] = {}
        self.signals: list[dict] = self._load_signal_history()
        self.activities: list[str] = []
        self.paper: dict = {"summary": {}, "positions": [], "closed": []}
        self.selected_symbol = ""
        self.score_history: dict[str, list[float]] = {}
        self.last_rate_time = time.time()
        self.last_rate_count = 0
        self.msg_rate = 0.0

        self._setup_style()
        self._build_ui()
        self.after(150, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=32, borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#10243b", foreground="#9dc6eb",
                        relief="flat", font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", "#143d61")], foreground=[("selected", "white")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(16, 9))
        style.map("TNotebook.Tab", background=[("selected", "#123253")], foreground=[("selected", TEXT)])

    def _card(self, parent):
        return tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)

    def _metric(self, parent, title, value, accent=CYAN):
        card = self._card(parent)
        card.pack(side="left", fill="both", expand=True, padx=4)
        tk.Label(card, text=title, bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=12, pady=(8, 1))
        var = tk.StringVar(value=value)
        tk.Label(card, textvariable=var, bg=PANEL, fg=accent, font=("Segoe UI Semibold", 17)).pack(anchor="w", padx=12, pady=(0, 8))
        return var

    def _build_ui(self):
        top = tk.Frame(self, bg=BG, height=72)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="▲", bg=BG, fg=CYAN, font=("Segoe UI", 28, "bold")).pack(side="left", padx=(18, 7))
        brand = tk.Frame(top, bg=BG)
        brand.pack(side="left")
        tk.Label(brand, text="MEXC SNIPER", bg=BG, fg=TEXT, font=("Segoe UI Semibold", 19)).pack(anchor="w")
        tk.Label(brand, text="SPOT • INTEGRATED LIVE SIGNAL TERMINAL", bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")

        self.connection_badge = tk.Label(top, text="● OFFLINE", bg="#211522", fg=RED,
                                         font=("Segoe UI Semibold", 9), padx=12, pady=7)
        self.connection_badge.pack(side="left", padx=20)
        self.clock = tk.Label(top, bg=BG, fg=MUTED, font=("Consolas", 9))
        self.clock.pack(side="left")

        self.arm_btn = tk.Button(top, text="ARM LIVE", command=self._toggle_live_arm, bg="#5b4312", fg="#ffe8a3",
                                 activebackground="#7a5b17", relief="flat", padx=12, pady=7,
                                 font=("Segoe UI Semibold", 9))
        self.arm_btn.pack(side="right", padx=7)
        self.stop_btn = tk.Button(top, text="STOP", command=self._stop, bg="#422033", fg="#ffb8c7",
                                  activebackground="#5b2840", relief="flat", padx=15, pady=7,
                                  font=("Segoe UI Semibold", 9), state="disabled")
        self.stop_btn.pack(side="right", padx=7)
        self.start_btn = tk.Button(top, text="START ENGINE", command=self._start, bg="#0c6e5b", fg="white",
                                   activebackground="#0e8c72", relief="flat", padx=15, pady=7,
                                   font=("Segoe UI Semibold", 9))
        self.start_btn.pack(side="right")

        metrics = tk.Frame(self, bg=BG)
        metrics.pack(fill="x", padx=9, pady=(0, 9))
        self.ws_var = self._metric(metrics, "WebSocket", "0/0", GREEN)
        self.msg_var = self._metric(metrics, "Messages / sec", "0", CYAN)
        self.symbol_var = self._metric(metrics, "Symbols", "0", TEXT)
        self.ready_var = self._metric(metrics, "Ready", "0", CYAN)
        self.topscore_var = self._metric(metrics, "Top Signal", "—", YELLOW)
        self.paper_eq_var = self._metric(metrics, "Paper Equity", "1000.00", GREEN)
        self.mode_var = self._metric(metrics, "Execution", "LOCKED", RED)

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=9, pady=(0, 8))
        self.dashboard_tab = tk.Frame(self.tabs, bg=BG)
        self.signals_tab = tk.Frame(self.tabs, bg=BG)
        self.paper_tab = tk.Frame(self.tabs, bg=BG)
        self.risk_tab = tk.Frame(self.tabs, bg=BG)
        self.activity_tab = tk.Frame(self.tabs, bg=BG)
        self.diagnostics_tab = tk.Frame(self.tabs, bg=BG)
        self.settings_tab = tk.Frame(self.tabs, bg=BG)
        for tab, title in ((self.dashboard_tab, "Dashboard"), (self.signals_tab, "Signals"),
                           (self.paper_tab, "Paper Trading"), (self.risk_tab, "Risk"),
                           (self.activity_tab, "Activity"), (self.diagnostics_tab, "Diagnostics"),
                           (self.settings_tab, "Settings")):
            self.tabs.add(tab, text=title)

        self._build_dashboard_tab()
        self._build_signals_tab()
        self._build_paper_tab()
        self._build_risk_tab()
        self._build_activity_tab()
        self._build_diagnostics_tab()
        self._build_settings_tab()

        status = tk.Frame(self, bg="#06101b", height=28)
        status.pack(fill="x", side="bottom")
        self.status_label = tk.Label(status, text="System ready • Trading disabled • Paper analysis available",
                                     bg="#06101b", fg=MUTED, font=("Segoe UI", 8))
        self.status_label.pack(side="left", padx=12)
        tk.Label(status, text="MEXC SPOT SNIPER • INTEGRATED", bg="#06101b", fg="#4c7195",
                 font=("Segoe UI", 8)).pack(side="right", padx=12)

    def _build_dashboard_tab(self):
        self.dashboard_tab.columnconfigure(0, weight=1)
        self.dashboard_tab.columnconfigure(1, weight=3)
        self.dashboard_tab.columnconfigure(2, weight=1)
        self.dashboard_tab.rowconfigure(0, weight=1)
        self.dashboard_tab.rowconfigure(1, weight=1)

        detail = self._card(self.dashboard_tab)
        detail.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 7))
        tk.Label(detail, text="SELECTED SIGNAL", bg=PANEL, fg=TEXT, font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=13, pady=(12, 5))
        self.detail_var = tk.StringVar(value="Select a symbol from the live table.")
        tk.Label(detail, textvariable=self.detail_var, justify="left", anchor="nw", bg=PANEL, fg=TEXT,
                 font=("Consolas", 9), padx=13, pady=8).pack(fill="both", expand=True)
        self.chart = tk.Canvas(detail, bg=PANEL, highlightthickness=0, height=190)
        self.chart.pack(fill="x", padx=10, pady=10)

        table = self._card(self.dashboard_tab)
        table.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        table.rowconfigure(1, weight=1)
        table.columnconfigure(0, weight=1)
        head = tk.Frame(table, bg=PANEL)
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        tk.Label(head, text="LIVE MARKET RANKING", bg=PANEL, fg=TEXT, font=("Segoe UI Semibold", 12)).pack(side="left")
        self.search_var = tk.StringVar()
        search = tk.Entry(head, textvariable=self.search_var, bg="#081522", fg=TEXT, insertbackground=TEXT,
                          relief="flat", width=18, font=("Segoe UI", 9))
        search.pack(side="right")
        search.insert(0, "Search symbol")
        search.bind("<FocusIn>", lambda e: search.delete(0, "end") if search.get() == "Search symbol" else None)
        cols = ("#", "symbol", "score", "price", "pressure", "volume", "momentum", "book", "state", "setup")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="browse")
        headings = {"#":"#", "symbol":"SYMBOL", "score":"SCORE", "price":"PRICE", "pressure":"BUY %",
                    "volume":"VOL", "momentum":"MOM %", "book":"BOOK", "state":"STATE", "setup":"SETUP"}
        widths = {"#":34, "symbol":108, "score":65, "price":105, "pressure":70, "volume":65, "momentum":72, "book":70, "state":92, "setup":115}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=1, column=1, sticky="ns", pady=(0, 8))
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._select_symbol)

        side = self._card(self.dashboard_tab)
        side.grid(row=0, column=2, sticky="nsew", padx=(7, 0))
        tk.Label(side, text="LATEST SIGNALS", bg=PANEL, fg=TEXT, font=("Segoe UI Semibold", 11)).pack(anchor="w", padx=12, pady=(12, 6))
        self.signal_list = tk.Listbox(side, bg=PANEL, fg=TEXT, selectbackground="#143d61", relief="flat", borderwidth=0,
                                      height=20, font=("Consolas", 8))
        self.signal_list.pack(fill="both", expand=True, padx=8, pady=5)

        health = self._card(self.dashboard_tab)
        health.grid(row=1, column=1, columnspan=2, sticky="nsew", pady=(7, 0))
        self.health_var = tk.StringVar(value="Waiting for engine…")
        tk.Label(health, text="ENGINE HEALTH", bg=PANEL, fg=TEXT, font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(health, textvariable=self.health_var, bg=PANEL, fg=MUTED, justify="left", anchor="nw",
                 font=("Consolas", 9)).pack(fill="both", expand=True, padx=12, pady=8)

    def _build_signals_tab(self):
        self.signals_tab.rowconfigure(0, weight=1)
        self.signals_tab.columnconfigure(0, weight=1)
        card = self._card(self.signals_tab)
        card.grid(row=0, column=0, sticky="nsew")
        cols = ("time", "symbol", "score", "setup", "state", "action", "price", "buy", "momentum", "reasons")
        self.signal_tree = ttk.Treeview(card, columns=cols, show="headings")
        heads = {"time":"TIME", "symbol":"SYMBOL", "score":"SCORE", "setup":"SETUP", "state":"STATE",
                 "action":"PAPER", "price":"PRICE", "buy":"BUY %", "momentum":"MOM %", "reasons":"REASONS"}
        for c in cols:
            self.signal_tree.heading(c, text=heads[c])
            self.signal_tree.column(c, width=100 if c != "reasons" else 360, anchor="center")
        self.signal_tree.column("time", width=80)
        self.signal_tree.column("symbol", width=110)
        self.signal_tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        card.rowconfigure(0, weight=1); card.columnconfigure(0, weight=1)

    def _build_paper_tab(self):
        self.paper_tab.rowconfigure(1, weight=1); self.paper_tab.rowconfigure(2, weight=1); self.paper_tab.columnconfigure(0, weight=1)
        top = tk.Frame(self.paper_tab, bg=BG); top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.pt_balance = self._metric(top, "Balance", "1000.00", GREEN)
        self.pt_equity = self._metric(top, "Equity", "1000.00", CYAN)
        self.pt_pnl = self._metric(top, "Net PnL", "+0.00", GREEN)
        self.pt_wr = self._metric(top, "Win Rate", "0.0%", YELLOW)
        self.pt_pf = self._metric(top, "Profit Factor", "0.00", PURPLE)
        self.pt_dd = self._metric(top, "Max DD", "0.00", RED)

        pos = self._card(self.paper_tab); pos.grid(row=1, column=0, sticky="nsew", pady=(0, 8)); pos.rowconfigure(0, weight=1); pos.columnconfigure(0, weight=1)
        self.position_tree = ttk.Treeview(pos, columns=("symbol","entry","stop","take","qty","score","setup"), show="headings")
        for c, h in (("symbol","SYMBOL"),("entry","ENTRY"),("stop","STOP"),("take","TAKE"),("qty","QTY"),("score","SCORE"),("setup","SETUP")):
            self.position_tree.heading(c, text=h); self.position_tree.column(c, width=130 if c == "setup" else 105, anchor="center")
        self.position_tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        closed = self._card(self.paper_tab); closed.grid(row=2, column=0, sticky="nsew"); closed.rowconfigure(0, weight=1); closed.columnconfigure(0, weight=1)
        self.closed_tree = ttk.Treeview(closed, columns=("time","symbol","pnl","pct","reason","score","setup"), show="headings")
        for c, h in (("time","TIME"),("symbol","SYMBOL"),("pnl","PNL"),("pct","PNL %"),("reason","REASON"),("score","ENTRY SCORE"),("setup","SETUP")):
            self.closed_tree.heading(c, text=h); self.closed_tree.column(c, width=120 if c in ("reason","setup") else 95, anchor="center")
        self.closed_tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _build_risk_tab(self):
        card = self._card(self.risk_tab); card.pack(fill="both", expand=True)
        tk.Label(card, text="PAPER RISK / SAFETY", bg=PANEL, fg=TEXT, font=("Segoe UI Semibold", 14)).pack(anchor="w", padx=18, pady=(18, 8))
        self.risk_text = tk.StringVar(value="Risk manager is initialized with the scanner.")
        tk.Label(card, textvariable=self.risk_text, bg=PANEL, fg=TEXT, justify="left", anchor="nw", font=("Consolas", 10)).pack(fill="both", expand=True, padx=18, pady=12)

    def _build_activity_tab(self):
        card = self._card(self.activity_tab); card.pack(fill="both", expand=True)
        self.activity_list = tk.Listbox(card, bg=PANEL, fg=TEXT, relief="flat", font=("Consolas", 9))
        self.activity_list.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_diagnostics_tab(self):
        self.diagnostics_tab.rowconfigure(1, weight=1)
        self.diagnostics_tab.columnconfigure(0, weight=1)
        top = tk.Frame(self.diagnostics_tab, bg=BG)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.diag_vars = {}
        diag_groups = [
            (("wrappers_processed", "WS messages processed"),
             ("deal_messages_parsed", "Deals parsed"),
             ("book_messages_parsed", "Books parsed"),
             ("symbols_with_market_data", "Symbols with data"),
             ("snapshots_calculated", "Snapshots"),
             ("ready_snapshots", "Ready snapshots")),
            (("score_candidates", "Score >= trigger"),
             ("signal_alerts", "Confirmed alerts"),
             ("paper_opens", "Paper opens"),
             ("paper_open_rejections", "Paper rejects"),
             ("paper_guard_rejections", "Entry guard rejects"),
             ("paper_closes", "Paper closes")),
        ]
        for group in diag_groups:
            row = tk.Frame(top, bg=BG)
            row.pack(fill="x", pady=2)
            for key, title in group:
                self.diag_vars[key] = self._metric(row, title, "0", CYAN)

        card = self._card(self.diagnostics_tab)
        card.grid(row=1, column=0, sticky="nsew")
        card.rowconfigure(1, weight=1); card.columnconfigure(0, weight=1)
        tk.Label(card, text="WHY A SIGNAL DID / DID NOT BECOME A TRADE", bg=PANEL, fg=TEXT,
                 font=("Segoe UI Semibold", 12)).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))
        self.diag_text = tk.StringVar(value="Waiting for live diagnostics…")
        tk.Label(card, textvariable=self.diag_text, bg=PANEL, fg=MUTED, justify="left", anchor="nw",
                 font=("Consolas", 10)).grid(row=1, column=0, sticky="nsew", padx=14, pady=8)

    def _build_settings_tab(self):
        # Settings contains more controls than fit vertically on a small screen.
        # Put the whole page inside a scrollable canvas so every section remains reachable.
        host = tk.Frame(self.settings_tab, bg=BG)
        host.pack(fill="both", expand=True, padx=2, pady=2)

        canvas = tk.Canvas(host, bg=BG, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        outer = tk.Frame(canvas, bg=BG)
        window_id = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)

        def update_scrollregion(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def fit_width(event):
            canvas.itemconfigure(window_id, width=event.width)

        outer.bind("<Configure>", update_scrollregion)
        canvas.bind("<Configure>", fit_width)

        def wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", wheel)

        def section(parent, title, row, col, colspan=1):
            card = self._card(parent)
            card.grid(row=row, column=col, columnspan=colspan, sticky="new", padx=6, pady=6)
            tk.Label(card, text=title, bg=PANEL, fg=TEXT,
                     font=("Segoe UI Semibold", 12)).pack(anchor="w", padx=14, pady=(12, 8))
            return card

        api = section(outer, "MEXC API / ACCOUNT", 0, 0)
        self.api_key_var = tk.StringVar(value=self.config.get("mexc_api_key", ""))
        self.api_secret_var = tk.StringVar(value=self.config.get("mexc_api_secret", ""))
        self.live_enabled_var = tk.BooleanVar(value=bool(self.config.get("live_trading_enabled", False)))
        self._show_credentials = False
        self._credential_entries = []
        for label, var in (("API Key", self.api_key_var), ("API Secret", self.api_secret_var)):
            r=tk.Frame(api,bg=PANEL); r.pack(fill="x",padx=14,pady=4)
            tk.Label(r,text=label,width=18,anchor="w",bg=PANEL,fg=MUTED).pack(side="left")
            ent=tk.Entry(r,textvariable=var,show="*",bg=PANEL2,fg=TEXT,insertbackground=TEXT,
                         relief="flat")
            ent.pack(side="left",fill="x",expand=True)
            self._credential_entries.append(ent)
        tk.Button(api,text="SHOW / HIDE",command=self._toggle_credentials,bg="#25364b",fg=TEXT,
                  relief="flat",padx=10,pady=3).pack(anchor="w",padx=14,pady=(0,6))
        tk.Checkbutton(api,text="Enable LIVE trading gate (ARM LIVE still required)",variable=self.live_enabled_var,
                       bg=PANEL,fg=YELLOW,selectcolor=PANEL2,activebackground=PANEL,activeforeground=YELLOW).pack(anchor="w",padx=14,pady=6)

        trading = section(outer, "TRADE / RISK SETTINGS", 0, 1)
        self.setting_vars={}
        mode_row = tk.Frame(trading, bg=PANEL); mode_row.pack(fill="x", padx=14, pady=4)
        tk.Label(mode_row, text="Trading mode", width=28, anchor="w", bg=PANEL, fg=MUTED).pack(side="left")
        self.trading_mode_var = tk.StringVar(value=str(self.config.get("trading_mode", "PAPER")).upper())
        ttk.Combobox(mode_row, textvariable=self.trading_mode_var, values=("PAPER", "LIVE"), state="readonly", width=12).pack(side="right")

        fields=[
            ("scanner_symbol_limit","Symbols to monitor",116),
            ("paper_starting_balance","Paper starting balance USDT",1000.0),
            ("paper_order_usdt","Paper order USDT",50.0),
            ("paper_max_open_positions","Paper max open positions",5),
            ("paper_stop_loss_pct","Paper stop loss %",1.5),
            ("paper_take_profit_pct","Paper take profit %",3.0),
            ("paper_max_spread_pct","Paper max spread %",0.40),
            ("paper_max_entry_drift_pct","Paper max entry drift %",0.60),
            ("paper_min_top_ask_coverage_pct","Paper min top-ask coverage %",50.0),
            ("live_order_usdt","LIVE order USDT (max 10)",10.0),
            ("live_max_open_positions","LIVE max open positions",1),
            ("live_stop_loss_pct","LIVE stop loss %",1.5),
            ("live_take_profit_pct","LIVE take profit %",3.0),
            ("live_max_slippage_pct","LIVE max slippage %",0.30),
            ("live_max_spread_pct","LIVE max spread %",0.20),
            ("live_max_entry_drift_pct","LIVE max entry drift %",0.30),
            ("live_min_top_ask_coverage_pct","LIVE min top-ask coverage %",50.0),
            ("scanner_score_threshold","Signal capture / score",65.0),
            ("scanner_ready_threshold","Ready threshold",55.0),
            ("scanner_reset_threshold","Reset threshold",50.0),
            ("scanner_confirmations","Confirmations",1),
            ("scanner_cooldown_seconds","Cooldown seconds",20.0),
            ("scanner_stale_after_ms","Stale data ms",3000.0),
        ]
        for key,label,default in fields:
            v=tk.StringVar(value=str(self.config.get(key,default))); self.setting_vars[key]=v
            r=tk.Frame(trading,bg=PANEL); r.pack(fill="x",padx=14,pady=3)
            tk.Label(r,text=label,width=30,anchor="w",bg=PANEL,fg=MUTED).pack(side="left")
            tk.Entry(r,textvariable=v,width=14,bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat").pack(side="right")

        self.stablecoin_exclusion_var = tk.BooleanVar(value=bool(self.config.get("stablecoin_exclusion_enabled", True)))
        stable_toggle = tk.Frame(trading, bg=PANEL)
        stable_toggle.pack(fill="x", padx=14, pady=(8, 3))
        tk.Checkbutton(
            stable_toggle,
            text="Exclude stablecoins from scanner",
            variable=self.stablecoin_exclusion_var,
            bg=PANEL, fg=YELLOW, selectcolor=PANEL2,
            activebackground=PANEL, activeforeground=YELLOW,
        ).pack(anchor="w")
        stable_row = tk.Frame(trading, bg=PANEL)
        stable_row.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(stable_row, text="Stablecoin base assets (comma separated)", width=30, anchor="w", bg=PANEL, fg=MUTED).pack(side="left")
        self.stablecoin_assets_var = tk.StringVar(value=str(self.config.get("stablecoin_base_assets", "USDT,USDC,USDS,USDE,USD1,USDD,DAI,FDUSD,TUSD,BUSD,PYUSD,GUSD,FRAX,LUSD,SUSD,USDP,USTC,UST,CRVUSD,EURC,EURT,EURS,USDX,USDXL")))
        tk.Entry(stable_row, textvariable=self.stablecoin_assets_var, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat").pack(side="right", fill="x", expand=True)
        tk.Label(trading, text="Changes apply after STOP + START ENGINE. The list is matched against the BASE asset.", bg=PANEL, fg=MUTED, wraplength=430, justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        confirm_row = tk.Frame(trading, bg=PANEL); confirm_row.pack(fill="x", padx=14, pady=4)
        tk.Label(confirm_row, text="LIVE confirmation phrase", width=30, anchor="w", bg=PANEL, fg=MUTED).pack(side="left")
        self.live_confirm_var = tk.StringVar(value=str(self.config.get("live_trading_confirm", "")))
        tk.Entry(confirm_row, textvariable=self.live_confirm_var, width=30, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", show="*").pack(side="right")

        strat=section(outer,"STRATEGIES / SCORE COMPONENTS",1,0)
        self.strategy_vars={}
        labels=[("volume","Volume acceleration"),("flow","Buy pressure / flow"),("momentum","Price momentum"),
                ("book","Order book imbalance"),("volatility","Volatility"),("liquidity","Liquidity / spread")]
        for key,label in labels:
            v=tk.BooleanVar(value=bool(self.config.get("strategy_"+key,True))); self.strategy_vars[key]=v
            tk.Checkbutton(strat,text=label,variable=v,bg=PANEL,fg=TEXT,selectcolor=PANEL2,
                           activebackground=PANEL,activeforeground=TEXT).pack(anchor="w",padx=18,pady=3)

        actions=section(outer,"APPLY",1,1)
        tk.Label(actions,text="Settings are written to .env and used by the next engine start.\n"
                 "LIVE is enabled in this build, but real orders require the separate ARM LIVE action.\n"
                 "Fresh spread/slippage/liquidity checks run before every LIVE BUY.",
                 bg=PANEL,fg=MUTED,justify="left").pack(anchor="w",padx=14,pady=8)
        tk.Button(actions,text="SAVE & APPLY",command=self._save_settings,bg="#0c6e5b",fg="white",
                  relief="flat",padx=18,pady=9).pack(anchor="w",padx=14,pady=8)
        tk.Button(actions,text="RESET DEFAULTS",command=self._reset_settings,bg="#25364b",fg=TEXT,
                  relief="flat",padx=18,pady=8).pack(anchor="w",padx=14,pady=4)
        self.settings_status=tk.StringVar(value="Ready")
        tk.Label(actions,textvariable=self.settings_status,bg=PANEL,fg=CYAN).pack(anchor="w",padx=14,pady=10)

        self._settings_help = "LIVE-capable build: real orders require SAVE & APPLY and the separate ARM LIVE action. Scroll to view all settings."
        self._settings_canvas = canvas

    @staticmethod
    def _normalize_trading_mode(value) -> str:
        """Return the GUI-safe trading mode string (PAPER or LIVE).

        Pydantic/Enum values can arrive here as ``TradingMode.PAPER`` rather
        than ``PAPER``.  The previous GUI compared the Enum string form
        directly and therefore rejected an otherwise valid PAPER setting.
        """
        if isinstance(value, TradingMode):
            return value.value
        text = str(value or "").strip().upper()
        if text.startswith("TRADINGMODE."):
            text = text.split(".", 1)[1]
        if text not in ("PAPER", "LIVE"):
            return "PAPER"
        return text

    def _load_gui_config(self):
        keys = [
            "mexc_api_key", "mexc_api_secret", "live_trading_enabled", "live_trading_confirm",
            "trading_mode", "trading_env",
            "live_order_usdt", "live_max_open_positions", "live_stop_loss_pct",
            "live_take_profit_pct", "live_max_slippage_pct", "live_max_spread_pct",
            "live_max_entry_drift_pct", "live_min_top_ask_coverage_pct",
            "scanner_score_threshold", "scanner_ready_threshold", "scanner_reset_threshold",
            "scanner_confirmations", "scanner_cooldown_seconds", "scanner_stale_after_ms",
            "scanner_symbol_limit", "stablecoin_exclusion_enabled", "stablecoin_base_assets",
            "paper_starting_balance", "paper_order_usdt", "paper_max_open_positions",
            "paper_stop_loss_pct", "paper_take_profit_pct", "paper_max_spread_pct",
            "paper_max_entry_drift_pct", "paper_min_top_ask_coverage_pct",
            "strategy_volume", "strategy_flow", "strategy_momentum", "strategy_book",
            "strategy_volatility", "strategy_liquidity",
        ]
        defaults = {
            "mexc_api_key": "", "mexc_api_secret": "", "live_trading_enabled": True, "live_trading_confirm": "I_UNDERSTAND_REAL_MONEY",
            "trading_mode": "LIVE", "trading_env": "live",
            "live_order_usdt": 10.0, "live_max_open_positions": 1,
            "live_stop_loss_pct": 1.5, "live_take_profit_pct": 3.0,
            "live_max_slippage_pct": 0.30, "live_max_spread_pct": 0.20,
            "live_max_entry_drift_pct": 0.30, "live_min_top_ask_coverage_pct": 50.0,
            "scanner_symbol_limit": 116,
            "stablecoin_exclusion_enabled": True,
            "stablecoin_base_assets": "USDT,USDC,USDS,USDE,USD1,USDD,DAI,FDUSD,TUSD,BUSD,PYUSD,GUSD,FRAX,LUSD,SUSD,USDP,USTC,UST,CRVUSD,EURC,EURT,EURS,USDX,USDXL",
            "scanner_score_threshold": 65.0, "scanner_ready_threshold": 55.0,
            "scanner_reset_threshold": 50.0, "scanner_confirmations": 1,
            "scanner_cooldown_seconds": 20.0, "scanner_stale_after_ms": 5000.0,
            "paper_starting_balance": 1000.0, "paper_order_usdt": 50.0,
            "paper_max_open_positions": 5, "paper_stop_loss_pct": 1.5,
            "paper_take_profit_pct": 3.0, "paper_max_spread_pct": 0.40,
            "paper_max_entry_drift_pct": 0.60, "paper_min_top_ask_coverage_pct": 25.0,
            "strategy_volume": True, "strategy_flow": True, "strategy_momentum": True,
            "strategy_book": True, "strategy_volatility": True, "strategy_liquidity": True,
        }
        values = {k: getattr(settings, k, defaults[k]) for k in keys}
        # TradingMode is a str Enum, but str(TradingMode.PAPER) is
        # "TradingMode.PAPER".  The GUI Combobox and validation require the
        # actual persisted value "PAPER"/"LIVE".
        values["trading_mode"] = self._normalize_trading_mode(values.get("trading_mode"))
        values["trading_env"] = "live" if values["trading_mode"] == "LIVE" else "paper"
        return values

    def _toggle_credentials(self):
        self._show_credentials = not self._show_credentials
        for ent in self._credential_entries:
            ent.configure(show="" if self._show_credentials else "*")

    def _save_settings(self):
        try:
            values = dict(self.config)
            values.update({
                "mexc_api_key": self.api_key_var.get().strip(),
                "mexc_api_secret": self.api_secret_var.get().strip(),
                "live_trading_enabled": bool(self.live_enabled_var.get()),
                "live_trading_confirm": self.live_confirm_var.get().strip(),
                "trading_mode": self._normalize_trading_mode(self.trading_mode_var.get()),
                "trading_env": "live" if self._normalize_trading_mode(self.trading_mode_var.get()) == "LIVE" else "paper",
                "stablecoin_exclusion_enabled": bool(self.stablecoin_exclusion_var.get()),
                "stablecoin_base_assets": self.stablecoin_assets_var.get().strip().upper(),
            })

            defaults = {
                "scanner_symbol_limit": 116, "paper_starting_balance": 1000.0, "paper_order_usdt": 50.0,
                "paper_max_open_positions": 5, "paper_stop_loss_pct": 1.5,
                "paper_take_profit_pct": 3.0, "live_order_usdt": 10.0,
                "live_max_open_positions": 1, "live_stop_loss_pct": 1.5,
                "live_take_profit_pct": 3.0, "live_max_slippage_pct": 0.30,
                "live_max_spread_pct": 0.20, "live_max_entry_drift_pct": 0.30,
                "live_min_top_ask_coverage_pct": 50.0, "scanner_score_threshold": 65.0,
                "scanner_ready_threshold": 55.0, "scanner_reset_threshold": 50.0,
                "scanner_confirmations": 1, "scanner_cooldown_seconds": 20.0,
                "scanner_stale_after_ms": 5000.0,
                "stablecoin_exclusion_enabled": True,
                "stablecoin_base_assets": "USDT,USDC,USDS,USDE,USD1,USDD,DAI,FDUSD,TUSD,BUSD,PYUSD,GUSD,FRAX,LUSD,SUSD,USDP,USTC,UST,CRVUSD,EURC,EURT,EURS,USDX,USDXL",
            }
            casts = {
                "scanner_symbol_limit": int, "paper_starting_balance": float, "paper_order_usdt": float,
                "paper_max_open_positions": int, "paper_stop_loss_pct": float,
                "paper_take_profit_pct": float, "paper_max_spread_pct": float,
                "paper_max_entry_drift_pct": float, "paper_min_top_ask_coverage_pct": float,
                "live_order_usdt": float,
                "live_max_open_positions": int, "live_stop_loss_pct": float,
                "live_take_profit_pct": float, "live_max_slippage_pct": float,
                "live_max_spread_pct": float, "live_max_entry_drift_pct": float,
                "live_min_top_ask_coverage_pct": float, "scanner_score_threshold": float,
                "scanner_ready_threshold": float, "scanner_reset_threshold": float,
                "scanner_confirmations": int, "scanner_cooldown_seconds": float,
                "scanner_stale_after_ms": float,
            }
            # Be tolerant of an older GUI window/cache that was created before a
            # setting was added. Never fail with "Missing GUI setting"; create
            # the missing variable from the canonical default and continue.
            for key, cast in casts.items():
                raw = self.setting_vars.get(key)
                if raw is None:
                    raw = tk.StringVar(value=str(self.config.get(key, defaults[key])))
                    self.setting_vars[key] = raw
                text = raw.get().strip()
                if not text:
                    text = str(defaults[key])
                    raw.set(text)
                values[key] = cast(text)

            for key, var in self.strategy_vars.items():
                values["strategy_" + key] = bool(var.get())

            if values["scanner_symbol_limit"] < 1:
                raise ValueError("Symbols to monitor must be >= 1.")
            if values["paper_order_usdt"] <= 0 or values["paper_max_open_positions"] < 1:
                raise ValueError("Paper order amount must be > 0 and max positions must be >= 1.")
            if values["paper_max_spread_pct"] < 0 or values["paper_max_entry_drift_pct"] < 0:
                raise ValueError("Paper spread/drift limits cannot be negative.")
            if not (0 <= values["paper_min_top_ask_coverage_pct"] <= 100):
                raise ValueError("Paper min top-ask coverage must be between 0 and 100%.")
            if values["paper_starting_balance"] <= 0:
                raise ValueError("Paper starting balance must be > 0.")
            if values["live_order_usdt"] <= 0 or values["live_order_usdt"] > 10:
                raise ValueError("LIVE order amount must be between 0 and 10 USDT (hard safety ceiling).")
            if values["trading_mode"] not in ("PAPER", "LIVE"):
                raise ValueError("Trading mode must be PAPER or LIVE.")
            if values["trading_mode"] == "LIVE" and values["live_trading_enabled"] and values["live_trading_confirm"] != LiveSpotEngine.CONFIRMATION:
                raise ValueError("LIVE mode requires the exact confirmation phrase I_UNDERSTAND_REAL_MONEY.")
            if values["live_max_open_positions"] < 1:
                raise ValueError("LIVE max open positions must be >= 1.")
            if values["live_max_slippage_pct"] > 2.0 or values["live_max_spread_pct"] > 2.0 or values["live_max_entry_drift_pct"] > 2.0:
                raise ValueError("LIVE market protection limits must not exceed 2%.")
            if not (0 <= values["live_min_top_ask_coverage_pct"] <= 100):
                raise ValueError("LIVE min top-ask coverage must be between 0 and 100%.")
            for key in ("paper_stop_loss_pct", "paper_take_profit_pct", "live_stop_loss_pct", "live_take_profit_pct", "live_max_slippage_pct", "live_max_spread_pct", "live_max_entry_drift_pct"):
                if values[key] < 0:
                    raise ValueError(f"{key} cannot be negative.")
            if not (0 < values["scanner_score_threshold"] <= 100):
                raise ValueError("Signal score must be between 0 and 100.")
            if not (0 <= values["scanner_reset_threshold"] <= 100 and 0 <= values["scanner_ready_threshold"] <= 100):
                raise ValueError("Ready/reset thresholds must be between 0 and 100.")
            if values["scanner_confirmations"] < 1:
                raise ValueError("Confirmations must be >= 1.")
            if values["stablecoin_exclusion_enabled"] and not values["stablecoin_base_assets"].strip():
                raise ValueError("Stablecoin exclusion is enabled, but the stablecoin list is empty.")

            for key, value in values.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
            self.config = values
            self.controller.config = values
            self._write_env(values)
            self.settings_status.set("Saved. Stop then START ENGINE to apply scanner settings.")
            self._activity("SETTINGS SAVED")
        except Exception as exc:
            messagebox.showerror("Settings", str(exc))

    def _write_env(self, values):
        env_path = PROJECT_ROOT / ".env"
        existing={}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8",errors="ignore").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k,v=line.split("=",1); existing[k.strip()]=v
        mapping={
            "MEXC_API_KEY":"mexc_api_key","MEXC_API_SECRET":"mexc_api_secret",
            "TRADING_MODE":"trading_mode","TRADING_ENV":"trading_env",
            "LIVE_TRADING_ENABLED":"live_trading_enabled","LIVE_TRADING_CONFIRM":"live_trading_confirm",
            "LIVE_ORDER_USDT":"live_order_usdt","LIVE_MAX_OPEN_POSITIONS":"live_max_open_positions",
            "LIVE_STOP_LOSS_PCT":"live_stop_loss_pct","LIVE_TAKE_PROFIT_PCT":"live_take_profit_pct",
            "LIVE_MAX_SLIPPAGE_PCT":"live_max_slippage_pct","LIVE_MAX_SPREAD_PCT":"live_max_spread_pct",
            "LIVE_MAX_ENTRY_DRIFT_PCT":"live_max_entry_drift_pct","LIVE_MIN_TOP_ASK_COVERAGE_PCT":"live_min_top_ask_coverage_pct",
            "SCANNER_SCORE_THRESHOLD":"scanner_score_threshold",
            "SCANNER_READY_THRESHOLD":"scanner_ready_threshold",
            "SCANNER_RESET_THRESHOLD":"scanner_reset_threshold",
            "SCANNER_CONFIRMATIONS":"scanner_confirmations",
            "SCANNER_COOLDOWN_SECONDS":"scanner_cooldown_seconds",
            "SCANNER_STALE_AFTER_MS":"scanner_stale_after_ms","SCANNER_SYMBOL_LIMIT":"scanner_symbol_limit",
            "PAPER_STARTING_BALANCE":"paper_starting_balance",
            "PAPER_ORDER_USDT":"paper_order_usdt","PAPER_MAX_OPEN_POSITIONS":"paper_max_open_positions",
            "PAPER_STOP_LOSS_PCT":"paper_stop_loss_pct","PAPER_TAKE_PROFIT_PCT":"paper_take_profit_pct",
            "PAPER_MAX_SPREAD_PCT":"paper_max_spread_pct","PAPER_MAX_ENTRY_DRIFT_PCT":"paper_max_entry_drift_pct",
            "PAPER_MIN_TOP_ASK_COVERAGE_PCT":"paper_min_top_ask_coverage_pct",
            "STABLECOIN_EXCLUSION_ENABLED":"stablecoin_exclusion_enabled",
            "STABLECOIN_BASE_ASSETS":"stablecoin_base_assets",
        }
        for env,key in mapping.items(): existing[env]=str(values.get(key,""))
        for key in ("volume","flow","momentum","book","volatility","liquidity"):
            existing["STRATEGY_"+key.upper()]=str(bool(values.get("strategy_"+key,True))).lower()
        env_path.write_text("\n".join(f"{k}={v}" for k,v in existing.items())+"\n",encoding="utf-8")

    def _reset_settings(self):
        defaults={"scanner_symbol_limit":116,"paper_starting_balance":1000.0,"paper_order_usdt":50.0,"paper_max_open_positions":5,
                  "paper_stop_loss_pct":1.5,"paper_take_profit_pct":3.0,"paper_max_spread_pct":0.20,"paper_max_entry_drift_pct":0.30,"paper_min_top_ask_coverage_pct":50.0,"live_order_usdt":10.0,
                  "live_max_open_positions":1,"live_stop_loss_pct":1.5,"live_take_profit_pct":3.0,
                  "live_max_slippage_pct":0.30,"live_max_spread_pct":0.20,"live_max_entry_drift_pct":0.30,"live_min_top_ask_coverage_pct":50.0,
                  "scanner_score_threshold":80.0,"scanner_ready_threshold":70.0,
                  "scanner_reset_threshold":60.0,"scanner_confirmations":2,"scanner_cooldown_seconds":60.0,
                  "scanner_stale_after_ms":3000.0,
                  "stablecoin_exclusion_enabled":True,
                  "stablecoin_base_assets":"USDT,USDC,USDS,USDE,USD1,USDD,DAI,FDUSD,TUSD,BUSD,PYUSD,GUSD,FRAX,LUSD,SUSD,USDP,USTC,UST,CRVUSD,EURC,EURT,EURS,USDX,USDXL"}
        for k,v in defaults.items():
            var = self.setting_vars.get(k)
            if var is not None:
                var.set(str(v))
        # These two settings use dedicated Boolean/StringVars rather than
        # self.setting_vars, so reset them explicitly below. This keeps RESET
        # compatible with the stablecoin controls added in Stage 19/20.
        self.trading_mode_var.set("PAPER")
        self.live_confirm_var.set("")
        self.live_enabled_var.set(False)
        self.stablecoin_exclusion_var.set(True)
        self.stablecoin_assets_var.set("USDT,USDC,USDS,USDE,USD1,USDD,DAI,FDUSD,TUSD,BUSD,PYUSD,GUSD,FRAX,LUSD,SUSD,USDP,USTC,UST,CRVUSD,EURC,EURT,EURS,USDX,USDXL")
        for k,var in self.strategy_vars.items(): var.set(True)
        self.settings_status.set("Defaults loaded. Press SAVE & APPLY to persist.")

    def _toggle_live_arm(self):
        if getattr(self, "live_armed", False):
            self.live_armed = False
            self.controller.config["live_runtime_armed"] = False
            self.arm_btn.configure(text="ARM LIVE", bg="#5b4312")
            self._activity("LIVE DISARMED")
            self.mode_var.set("PAPER / LOCKED")
            return
        if self.trading_mode_var.get().upper() != "LIVE" or not self.live_enabled_var.get():
            messagebox.showwarning("LIVE", "Set Trading mode=LIVE and enable the LIVE trading gate first, then SAVE & APPLY.")
            return
        if self.live_confirm_var.get().strip() != LiveSpotEngine.CONFIRMATION:
            messagebox.showwarning("LIVE", "Enter the exact confirmation phrase before arming LIVE.")
            return
        if not messagebox.askyesno("ARM LIVE", "This arms real MEXC Spot orders. Continue?"):
            return
        self.live_armed = True
        self.controller.config["live_runtime_armed"] = True
        self.arm_btn.configure(text="DISARM LIVE", bg="#7a1f35")
        self.mode_var.set("LIVE / ARMED")
        self._activity("LIVE ARMED")

    def _start(self):
        self.rows.clear(); self.signals.clear(); self.activities.clear(); self.paper = {"summary": {}, "positions": [], "closed": []}
        self.start_btn.configure(state="disabled"); self.stop_btn.configure(state="normal")
        self.controller.config["live_runtime_armed"] = bool(getattr(self, "live_armed", False))
        self.status_label.configure(text="Starting discovery and WebSocket engine…", fg=CYAN)
        self._activity("START requested")
        self.controller.start()

    def _stop(self):
        self.status_label.configure(text="Stopping WebSocket connections…", fg=YELLOW)
        self._activity("STOP requested")
        self.controller.stop()

    def _select_symbol(self, _event=None):
        selection = self.tree.selection()
        if not selection: return
        values = self.tree.item(selection[0], "values")
        if not values: return
        self.selected_symbol = values[1]
        row = self.rows.get(self.selected_symbol)
        if row:
            self.score_history.setdefault(self.selected_symbol, []).append(row["score"])
            self.score_history[self.selected_symbol] = self.score_history[self.selected_symbol][-100:]
            self._update_detail(row); self._draw_chart()

    def _update_detail(self, row):
        comp = row.get("components", {})
        reasons = ", ".join(row.get("reasons", [])) or "—"
        text = (f"{row['symbol']}\n\nScore        {row['score']:.2f} / 100\nPrice        {price_fmt(row['price'])}\n"
                f"Buy pressure {row['pressure']*100:.1f}%\nVolume       {row['volume']:.2f}x\nMomentum     {row['momentum']:+.3f}%\n"
                f"Book         {row['imbalance']*100:+.1f}%\nSpread       {row['spread']:.4f}%\nState        {row['state']}\nSetup        {row['setup']}\n"
                f"Ready        {'YES' if row['ready'] else 'WAITING'}\n\nComponents\n"
                f"Volume {comp.get('volume',0):.1f} | Flow {comp.get('flow',0):.1f}\nMomentum {comp.get('momentum',0):.1f} | Book {comp.get('book',0):.1f}\n"
                f"Volatility {comp.get('volatility',0):.1f} | Liquidity {comp.get('liquidity',0):.1f}\n\nReasons\n{reasons}\n\nExecution  LOCKED")
        self.detail_var.set(text)

    def _draw_chart(self):
        c = self.chart; c.delete("all")
        w = max(c.winfo_width(), 280); h = max(c.winfo_height(), 190); pad = 28
        for i in range(5):
            y = pad + i * (h - 2*pad)/4
            c.create_line(pad, y, w-pad, y, fill="#14304a")
            c.create_text(5, y, text=str(100-i*25), fill=MUTED, font=("Segoe UI", 8), anchor="w")
        vals = self.score_history.get(self.selected_symbol, []) or [0]
        if len(vals) == 1:
            x=w/2; y=h-pad-vals[0]/100*(h-2*pad); c.create_oval(x-3,y-3,x+3,y+3,fill=CYAN,outline=""); return
        pts=[]
        for i,v in enumerate(vals):
            x=pad+i*(w-2*pad)/(len(vals)-1); y=h-pad-max(0,min(100,v))/100*(h-2*pad); pts.extend((x,y))
        c.create_line(*pts, fill=CYAN, width=2, smooth=True)
        c.create_text(w-pad,pad,text=f"{vals[-1]:.1f}",fill=CYAN,anchor="ne",font=("Segoe UI Semibold",10))

    def _load_signal_history(self):
        """Load persistent signals directly from SQLite, with CSV fallback."""
        try:
            db = Database(PROJECT_ROOT / "data" / "mexc_sniper.db")
            rows = db.load_signals(limit=200)
            db.close()
            if rows:
                import json
                result = []
                for row in rows:
                    try:
                        reasons = json.loads(row["reasons"] or "[]")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        reasons = []
                    result.append({
                        "time": float(row["event_time"]),
                        "symbol": row["symbol"], "score": float(row["score"]),
                        "setup": row["setup"], "state": row["state"],
                        "price": float(row["price"]), "pressure": float(row["pressure"]),
                        "momentum": float(row["momentum"]), "volume": float(row["volume"]),
                        "imbalance": float(row["imbalance"]), "spread": float(row["spread"]),
                        "reasons": reasons, "paper_action": row["paper_action"],
                    })
                return result
        except Exception:
            pass

        path = PROJECT_ROOT / "data" / "signals.csv"
        if not path.exists():
            return []
        try:
            with path.open("r", newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))[-200:]
            result = []
            for row in rows:
                for key in ("time", "score", "price", "pressure", "momentum"):
                    row[key] = float(row.get(key) or 0)
                row["reasons"] = [x for x in row.get("reasons", "").split(" | ") if x]
                result.append(row)
            return list(reversed(result))
        except (OSError, ValueError, TypeError):
            return []

    def _poll(self):
        while True:
            try: kind, payload = self.q.get_nowait()
            except queue.Empty: break
            if kind == "status": self._handle_status(payload)
            elif kind == "row":
                self.rows[payload["symbol"]] = payload
                if payload["symbol"] == self.selected_symbol:
                    self.score_history.setdefault(self.selected_symbol, []).append(payload["score"])
                    self.score_history[self.selected_symbol] = self.score_history[self.selected_symbol][-100:]
                    self._update_detail(payload)
            elif kind == "signal":
                self.signals.insert(0,payload); self.signals=self.signals[:200]
                self._activity(f"SIGNAL {payload['symbol']} score={payload['score']:.1f} {payload['setup']}")
            elif kind == "paper": self.paper = payload
            elif kind == "diag":
                self._update_diagnostics(payload)
            elif kind == "live":
                event = payload.get("event", "LIVE")
                if event == "PREFLIGHT_OK":
                    self._activity("LIVE PREFLIGHT OK")
                elif event == "PREFLIGHT_FAILED":
                    self._activity(f"LIVE PREFLIGHT FAILED: {payload.get('error','')}")
                elif event == "BUY":
                    self._activity(f"LIVE BUY {payload.get('symbol','')} @ {price_fmt(payload.get('price',0))} score={payload.get('score',0):.1f}")
                elif event == "SELL":
                    self._activity(f"LIVE SELL {payload.get('symbol','')} {payload.get('reason','')}")
                else:
                    self._activity(f"{event} {payload.get('symbol','')} {payload.get('error','')}")
            elif kind == "trade":
                if payload.get("type") == "OPEN":
                    self._activity(f"PAPER OPEN {payload['symbol']} @ {price_fmt(payload['price'])} score={payload['score']:.1f}")
                else:
                    self._activity(f"PAPER CLOSE {payload['symbol']} PnL={payload.get('pnl',0):+.4f} {payload.get('reason','')}")
            elif kind == "error":
                self.status_label.configure(text=f"Engine error: {payload}", fg=RED); self._activity(f"ERROR {payload}")
                messagebox.showerror("Engine error", payload)
            elif kind == "stopped":
                self.start_btn.configure(state="normal"); self.stop_btn.configure(state="disabled")
                self.connection_badge.configure(text="● OFFLINE", bg="#211522", fg=RED)
                self.status_label.configure(text="Engine stopped • Trading remains disabled", fg=MUTED)
                self._activity("ENGINE stopped")
        self._refresh_all()
        self.clock.configure(text=time.strftime("%Y-%m-%d  %H:%M:%S"))
        self.after(250, self._poll)

    def _handle_status(self, data):
        phase=data.get("phase")
        if phase=="discovering": self.status_label.configure(text="Discovering Spot/USDT symbols…", fg=CYAN)
        elif phase=="starting": self.status_label.configure(text=f"Discovered {data.get('symbols',0)} symbols • preparing WebSockets…", fg=CYAN); self._activity(f"DISCOVERY selected={data.get('symbols',0)}")
        elif phase=="starting_ws": self.status_label.configure(text=f"Starting WebSocket manager for {data.get('symbols',0)} symbols…", fg=CYAN)

    def _refresh_all(self):
        manager=self.controller.manager
        if manager:
            connected=sum(1 for c in manager.connections if c.connected); total=len(manager.connections)
            self.ws_var.set(f"{connected}/{total}")
            now=time.time(); dt=now-self.last_rate_time
            if dt>=1:
                current=manager._messages_received; self.msg_rate=(current-self.last_rate_count)/dt; self.last_rate_count=current; self.last_rate_time=now
            self.msg_var.set(f"{self.msg_rate:,.0f}")
            self.connection_badge.configure(text=f"● ONLINE {connected}/{total}", bg="#083629" if connected==total and total else "#3a3011", fg=GREEN if connected==total and total else YELLOW)
            live_state = "LIVE / ARMED" if (self.controller.live_engine and self.controller.live_engine.enabled) else "PAPER / LOCKED"
            self.mode_var.set(live_state)
            self.health_var.set(f"Connections       {connected}/{total}\nMessages          {manager._messages_received:,}\nBook messages     {manager._book_messages:,}\nDeal messages     {manager._deal_messages:,}\nLast symbol       {manager._last_symbol or '-'}\nChannels          {sum(len(c.channels) for c in manager.connections)}\nMode              {live_state}")
        self.symbol_var.set(str(self.controller.symbol_count or len(self.rows)))
        self.ready_var.set(str(sum(1 for r in self.rows.values() if r.get("ready"))))
        if self.rows:
            top=max(self.rows.values(),key=lambda r:r["score"]); self.topscore_var.set(f"{top['symbol']} {top['score']:.1f}")
        summary=self.paper.get("summary",{})
        if summary:
            self.paper_eq_var.set(f"{summary.get('equity',0):.2f}")
            self.pt_balance.set(f"{summary.get('balance',0):.2f}"); self.pt_equity.set(f"{summary.get('equity',0):.2f}")
            self.pt_pnl.set(f"{summary.get('net_pnl_usdt',0):+.2f}"); self.pt_wr.set(f"{summary.get('win_rate_pct',0):.1f}%")
            self.pt_pf.set(str(summary.get('profit_factor',0))); self.pt_dd.set(f"{summary.get('max_drawdown_usdt',0):.2f}")
            self.risk_text.set(self._risk_text(summary))
        self._refresh_table(); self._refresh_signals(); self._refresh_signal_tree(); self._refresh_paper_tables()

    def _update_diagnostics(self, d):
        for key, var in getattr(self, "diag_vars", {}).items():
            var.set(f"{d.get(key, 0):,}")
        tops = d.get("top_scores", [])
        last_age = d.get("last_market_data_age_ms")
        last_age_text = "—" if last_age is None else f"{last_age:.0f} ms"
        lines = [
            f"Messages processed       {d.get('wrappers_processed', 0):,}",
            f"Deals parsed             {d.get('deal_messages_parsed', 0):,}",
            f"Books parsed             {d.get('book_messages_parsed', 0):,}",
            f"Symbols with market data {d.get('symbols_with_market_data', 0):,}",
            f"Snapshots calculated     {d.get('snapshots_calculated', 0):,}",
            f"Ready snapshots          {d.get('ready_snapshots', 0):,}",
            f"Score >= trigger         {d.get('score_candidates', 0):,}",
            f"Confirmed alerts         {d.get('signal_alerts', 0):,}",
            f"Signal journal records   {d.get('signal_history_count', 0):,}",
            f"Paper opens              {d.get('paper_opens', 0):,}",
            f"Paper rejects            {d.get('paper_open_rejections', 0):,}",
            f"Entry guard rejects      {d.get('paper_guard_rejections', 0):,}",
            f"  Spread rejects         {d.get('paper_spread_rejections', 0):,}",
            f"  Drift rejects          {d.get('paper_drift_rejections', 0):,}",
            f"  Coverage rejects       {d.get('paper_coverage_rejections', 0):,}",
            f"  Risk rejects           {d.get('paper_risk_rejections', 0):,}",
            f"Paper closes             {d.get('paper_closes', 0):,}",
            f"Live positions           {d.get('live_positions', 0):,}",
            f"Live enabled             {d.get('live_enabled', False)}",
            f"Last body kind           {d.get('last_body_kind') or '—'}",
            f"Last data age            {last_age_text}",
            f"Invalid deals/books      {d.get('invalid_deals', 0):,} / {d.get('invalid_books', 0):,}",
            "",
            "TOP SCORES",
        ]
        lines.extend(f"{i:>2}. {symbol:<16} {score:>6.2f}" for i, (symbol, score) in enumerate(tops, 1))
        last_entry = d.get("last_entry_diagnostics") or {}
        lines.extend([
            "",
            f"Last paper rejection: {d.get('last_rejection_reason') or '—'}",
            f"Last entry check: {last_entry.get('decision') or '—'}",
            f"  symbol={last_entry.get('symbol') or '—'}  spread={float(last_entry.get('spread_pct', 0.0)):.4f}%  drift={float(last_entry.get('entry_drift_pct', 0.0)):.4f}%",
            f"  top-ask coverage={float(last_entry.get('top_ask_coverage_pct', 0.0)):.1f}%",
            f"  failed checks={', '.join(last_entry.get('failed_checks', [])) or 'none'}",
            f"  reason={last_entry.get('rejection_reason') or '—'}",
        ])
        self.diag_text.set("\n".join(lines))

    def _risk_text(self, s):
        return (
            f"Paper allocation      {float(self.config.get('paper_order_usdt', 50.0)):.2f} USDT\n"
            f"Paper max positions   {int(self.config.get('paper_max_open_positions', 5))}\n"
            f"Paper stop loss       {float(self.config.get('paper_stop_loss_pct', 1.5)):.2f}%\n"
            f"Paper take profit     {float(self.config.get('paper_take_profit_pct', 3.0)):.2f}%\n"
            f"Max risk / trade      0.50%\nMax daily loss        2.00%\n"
            f"Max total exposure   50.00%\nMax position          10.00%\n"
            f"Peak equity           {s.get('peak_equity',0):.4f} USDT\n"
            f"Max drawdown          {s.get('max_drawdown_usdt',0):.4f} USDT ({s.get('max_drawdown_pct',0):.2f}%)\n\n"
            f"Closed trades         {s.get('closed_trades',0)}\n"
            f"Wins / losses         {s.get('wins',0)} / {s.get('losses',0)}\n"
            f"Net PnL               {s.get('net_pnl_usdt',0):+.4f} USDT"
        )

    def _refresh_table(self):
        query=self.search_var.get().strip().upper(); rows=sorted(self.rows.values(),key=lambda r:r["score"],reverse=True)
        if query and query!="SEARCH SYMBOL": rows=[r for r in rows if query in r["symbol"]]
        rows=rows[:30]
        for item in self.tree.get_children(): self.tree.delete(item)
        selected=None
        for i,r in enumerate(rows,1):
            iid=self.tree.insert("","end",values=(i,r["symbol"],f"{r['score']:.1f}",price_fmt(r["price"]),f"{r['pressure']*100:.1f}%",f"{r['volume']:.2f}x",f"{r['momentum']:+.2f}%",f"{r['imbalance']*100:+.1f}%",r["state"],r["setup"]))
            if r["symbol"]==self.selected_symbol: selected=iid
        if selected: self.tree.selection_set(selected)

    def _refresh_signals(self):
        self.signal_list.delete(0,"end")
        for s in self.signals[:30]:
            stamp=time.strftime("%H:%M:%S",time.localtime(s.get("time",time.time())))
            self.signal_list.insert("end",f"{stamp} {s['symbol']:<13} {s['score']:>5.1f} {s['setup']}")

    def _refresh_signal_tree(self):
        for item in self.signal_tree.get_children(): self.signal_tree.delete(item)
        for s in self.signals:
            stamp=time.strftime("%H:%M:%S",time.localtime(s.get("time",time.time())))
            self.signal_tree.insert("","end",values=(stamp,s["symbol"],f"{s['score']:.1f}",s["setup"],s["state"],s.get("paper_action","—"),price_fmt(s["price"]),f"{s['pressure']*100:.1f}%",f"{s['momentum']:+.2f}%",", ".join(s.get("reasons",[])) or "—"))

    def _refresh_paper_tables(self):
        for item in self.position_tree.get_children(): self.position_tree.delete(item)
        for p in self.paper.get("positions",[]):
            self.position_tree.insert("","end",values=(p["symbol"],price_fmt(p["entry"]),price_fmt(p["stop"]),price_fmt(p["take"]),f"{p['quantity']:.6f}",f"{p['score']:.1f}",p["setup"]))
        for item in self.closed_tree.get_children(): self.closed_tree.delete(item)
        for t in reversed(self.paper.get("closed",[]) [-50:]):
            stamp=time.strftime("%H:%M:%S",time.localtime(t["closed_at"]))
            self.closed_tree.insert("","end",values=(stamp,t["symbol"],f"{t['pnl']:+.4f}",f"{t['pnl_pct']:+.2f}%",t["reason"],f"{t['score']:.1f}",t["setup"]))

    def _activity(self,text):
        line=f"{time.strftime('%H:%M:%S')}  {text}"
        self.activities.insert(0,line); self.activities=self.activities[:300]
        if hasattr(self,"activity_list"):
            self.activity_list.delete(0,"end")
            for item in self.activities: self.activity_list.insert("end",item)

    def _close(self):
        self.live_armed = False
        self.controller.config["live_runtime_armed"] = False
        if self.controller.running:
            self.controller.stop(); self.after(400,self._close); return
        self.destroy()


if __name__ == "__main__":
    Dashboard().mainloop()

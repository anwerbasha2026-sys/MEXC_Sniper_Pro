"""Android entry point for MEXC Sniper Stage 26.

This file is intentionally Kivy-only. The Windows Tkinter Dashboard remains in
app/main.py and is not imported on Android.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput


class MobileEngine:
    def __init__(self, on_update):
        self.on_update = on_update
        self.thread = None
        self.loop = None
        self.manager = None
        self.scanner = None
        self.stop_requested = threading.Event()
        self.running = False

    def start(self, data_dir: Path):
        if self.running:
            return
        self.stop_requested.clear()
        self.thread = threading.Thread(
            target=self._thread_main,
            args=(data_dir,),
            daemon=True,
            name="mexc-mobile-engine",
        )
        self.thread.start()

    def _thread_main(self, data_dir: Path):
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            os.chdir(data_dir.parent)
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._run(data_dir))
        except Exception as exc:
            self._emit("ERROR", f"Engine stopped: {type(exc).__name__}: {exc}")
        finally:
            self.running = False
            self.loop = None
            self._emit("STOPPED", "Engine stopped. PAPER / LOCKED remains active.")

    async def _run(self, data_dir: Path):
        # Imports happen only after Kivy has created the Android app and after
        # the writable user-data directory has been selected.
        from app.config import settings
        from app.exchange.spot_client import SpotClient
        from app.exchange.symbol_discovery import SymbolDiscovery
        from app.exchange.websocket_manager import MEXCSpotWebSocketManager
        from app.scanner.live_signal_scanner import LiveSignalScanner

        self.running = True

        scanner = LiveSignalScanner(
            strong_threshold=65.0,
            ready_threshold=55.0,
            reset_threshold=50.0,
            confirmations_required=1,
            cooldown_seconds=20,
            stale_after_ms=settings.scanner_stale_after_ms,
            paper_starting_balance=settings.paper_starting_balance,
            paper_order_usdt=settings.paper_order_usdt,
            paper_stop_loss_pct=settings.paper_stop_loss_pct,
            paper_take_profit_pct=settings.paper_take_profit_pct,
            paper_max_open_positions=settings.paper_max_open_positions,
            paper_max_spread_pct=settings.paper_max_spread_pct,
            paper_max_entry_drift_pct=settings.paper_max_entry_drift_pct,
            paper_min_top_ask_coverage_pct=settings.paper_min_top_ask_coverage_pct,
            enabled_strategies={
                "volume": settings.strategy_volume,
                "flow": settings.strategy_flow,
                "momentum": settings.strategy_momentum,
                "book": settings.strategy_book,
                "volatility": settings.strategy_volatility,
                "liquidity": settings.strategy_liquidity,
            },
        )
        self.scanner = scanner

        async def on_message(wrapper):
            decisions = scanner.process_wrapper(wrapper)
            if decisions:
                snapshot, result, decision = decisions[-1]
                self._emit(
                    "MARKET",
                    f"{snapshot.symbol} | score {result.score:.1f} | "
                    f"state={decision.state.value} | price={snapshot.price:.8f}",
                )
                if decision.should_alert:
                    self._emit(
                        "SIGNAL",
                        f"{snapshot.symbol} | score={result.score:.1f} | "
                        f"setup={result.setup} | PAPER signal",
                    )
                if scanner.last_trade_events:
                    event = scanner.last_trade_events[-1]
                    self._emit(
                        "TRADE",
                        f"{event.get('type')} {event.get('symbol')} "
                        f"price={event.get('price', 0):.8f} "
                        f"pnl={event.get('pnl', 0):+.4f}",
                    )

        discovery = SymbolDiscovery(
            client=SpotClient(),
            limit=max(1, int(settings.scanner_symbol_limit)),
            stablecoin_exclusion_enabled=bool(settings.stablecoin_exclusion_enabled),
            stablecoin_base_assets=settings.stablecoin_base_assets,
        )

        self._emit("START", "Discovering Spot/USDT symbols...")
        symbols = await discovery.discover()
        if not symbols:
            raise RuntimeError("No eligible Spot/USDT symbols were found")

        self._emit("START", f"Selected {len(symbols)} symbols")

        manager = MEXCSpotWebSocketManager(
            symbols=[item.symbol for item in symbols],
            on_message=on_message,
            channels_per_connection=28,
            deal_interval="10ms",
            book_interval="100ms",
            ping_interval=20.0,
        )
        self.manager = manager

        self._emit(
            "READY",
            "WebSocket starting | PAPER TRADING | LIVE LOCKED",
        )

        try:
            await manager.start()
        finally:
            try:
                scanner.close()
            except Exception:
                pass
            self.scanner = None
            self.manager = None

    def stop(self):
        self.stop_requested.set()
        loop = self.loop
        manager = self.manager
        if loop is not None and manager is not None:
            try:
                asyncio.run_coroutine_threadsafe(manager.stop(), loop)
            except Exception:
                pass

    def _emit(self, kind, message):
        text = f"[{kind}] {message}"
        Clock.schedule_once(lambda _dt: self.on_update(text), 0)


class MobileRoot(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=dp(12), spacing=dp(8), **kwargs)

        self.title = Label(
            text="MEXC SNIPER\nANDROID • PAPER / LOCKED",
            font_size="22sp",
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(82),
        )
        self.add_widget(self.title)

        self.status = Label(
            text="Ready — LIVE execution is LOCKED",
            size_hint_y=None,
            height=dp(42),
        )
        self.add_widget(self.status)

        controls = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(8))
        self.start_btn = Button(text="START PAPER")
        self.stop_btn = Button(text="STOP")
        self.start_btn.bind(on_release=self.start_engine)
        self.stop_btn.bind(on_release=self.stop_engine)
        controls.add_widget(self.start_btn)
        controls.add_widget(self.stop_btn)
        self.add_widget(controls)

        self.log = TextInput(
            text="PAPER / LOCKED\nLIVE orders are disabled.\n",
            readonly=True,
            multiline=True,
            font_size="14sp",
        )
        scroll = ScrollView()
        scroll.add_widget(self.log)
        self.add_widget(scroll)

        self.engine = MobileEngine(self.append_log)
        self._last_update = time.monotonic()

    def append_log(self, text):
        self.log.text += text + "\n"
        self.log.cursor = (0, len(self.log.text))
        if len(self.log.text) > 30000:
            self.log.text = self.log.text[-24000:]
        self.status.text = text[:100]

    def start_engine(self, *_):
        if self.engine.running:
            return
        data_dir = Path(App.get_running_app().user_data_dir) / "data"
        self.log.text += "\n[START] Starting real Stage 26 scanner...\n"
        self.status.text = "Starting engine..."
        self.engine.start(data_dir)

    def stop_engine(self, *_):
        self.engine.stop()
        self.status.text = "Stopping..."


class MEXCSniperAndroidApp(App):
    title = "MEXC Sniper"

    def build(self):
        return MobileRoot()


if __name__ == "__main__":
    MEXCSniperAndroidApp().run()

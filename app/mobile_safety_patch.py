from __future__ import annotations

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label


def apply(m):
    Card = m.Card
    StatCard = m.StatCard
    PillButton = m.PillButton
    SectionTitle = m.SectionTitle
    Switch = m.Switch
    WHITE, MUTED, CYAN, AMBER, GREEN, RED, PANEL_2 = m.WHITE, m.MUTED, m.CYAN, m.AMBER, m.GREEN, m.RED, m.PANEL_2

    def safe_page_live_trades(self):
        # Keep a single vertical ScrollView. The previous implementation put a
        # second vertical ScrollView inside the page ScrollView, which is fragile
        # on older Android/Kivy builds when the page becomes visible.
        root = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(14), size_hint_y=None)
        root.bind(minimum_height=root.setter("height"))

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
        root.add_widget(self.live_positions_box)
        self.live_empty = Label(text="No synchronized real holdings.", color=MUTED,
                                size_hint_y=None, height=dp(40))
        self.live_positions_box.add_widget(self.live_empty)
        return self._scroll_page(root)

    def safe_render_account_cards(self):
        try:
            free = float(self.account_data.get("usdt_free", 0) or 0)
            total = float(self.account_data.get("usdt_total", 0) or 0)
            with self.controller.exchange_lock:
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
        except Exception as exc:
            self._log(f"ACCOUNT VIEW ERROR • {exc}", error=True)

    def safe_render_live_positions(self):
        try:
            self.live_positions_box.clear_widgets()
            with self.controller.exchange_lock:
                engine = self.controller.live_engine
                positions = list(engine.positions.values()) if engine else []
                prices = dict(self.controller.prices)
            if engine is None:
                self.live_positions_box.add_widget(Label(text="Connect the account first.", color=MUTED,
                                                         size_hint_y=None, height=dp(40)))
                return
            positions.sort(key=lambda p: p.symbol)
            if not positions:
                self.live_positions_box.add_widget(Label(text="No synchronized real holdings.", color=MUTED,
                                                         size_hint_y=None, height=dp(40)))
                return
            for pos in positions:
                current = float(prices.get(pos.symbol, pos.entry_price))
                pnl_pct = ((current - pos.entry_price) / pos.entry_price * 100.0) if pos.entry_price else 0.0
                pnl_usdt = (current - pos.entry_price) * pos.quantity if pos.entry_price else 0.0
                synced = pos.entry_order_id == "ACCOUNT_SYNC"
                card = Card(orientation="vertical", padding=dp(12), spacing=dp(6), size_hint_y=None, height=dp(188), color=PANEL_2)
                top = BoxLayout(size_hint_y=None, height=dp(30))
                top.add_widget(Label(text=pos.symbol, color=WHITE, bold=True, font_size="18sp", halign="left"))
                top.add_widget(Label(text="ACCOUNT SYNC" if synced else "LIVE TRADE",
                                    color=AMBER if synced else GREEN, bold=True, font_size="10sp", halign="right"))
                card.add_widget(top)
                card.add_widget(Label(text=f"QTY  {pos.quantity:.10f}    ENTRY  {pos.entry_price:.10f}", color=MUTED,
                                      font_size="10sp", halign="left", size_hint_y=None, height=dp(20)))
                pnl_color = GREEN if pnl_usdt >= 0 else RED
                card.add_widget(Label(text=f"CURRENT  {current:.10f}     P/L  {pnl_usdt:+.6f} USDT  ({pnl_pct:+.3f}%)",
                                      color=pnl_color, font_size="11sp", bold=True, size_hint_y=None, height=dp(24)))
                sltp = "SL / TP  reference unavailable for pre-existing holding" if synced else f"SL  {pos.stop_loss:.10f}    TP  {pos.take_profit:.10f}"
                card.add_widget(Label(text=sltp, color=MUTED, font_size="10sp", size_hint_y=None, height=dp(20)))
                card.add_widget(Label(text=f"ORDER  {pos.entry_order_id}", color=MUTED, font_size="9sp", size_hint_y=None, height=dp(18)))
                sell = PillButton(text=f"SELL {pos.symbol} NOW")
                sell.background_color = RED
                sell.bind(on_release=lambda _b, symbol=pos.symbol: self._confirm_sell(symbol))
                card.add_widget(sell)
                self.live_positions_box.add_widget(card)
        except Exception as exc:
            self._log(f"LIVE POSITIONS VIEW ERROR • {exc}", error=True)
            self.live_positions_box.clear_widgets()
            self.live_positions_box.add_widget(Label(text="Unable to render LIVE positions. Use SYNC MEXC ACCOUNT.",
                                                      color=MUTED, size_hint_y=None, height=dp(40)))

    def safe_collect(self):
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
        for key in numeric:
            raw = str(data.get(key, "")).strip()
            if not raw:
                raise ValueError(f"{key}: value is required")
            value = float(raw)
            if value < 0 and key not in {"live_stop_loss_pct"}:
                raise ValueError(f"{key}: value cannot be negative")
            data[key] = value
        for key in ints:
            raw = str(data.get(key, "")).strip()
            if not raw:
                raise ValueError(f"{key}: value is required")
            value = int(float(raw))
            if value < 1:
                raise ValueError(f"{key}: value must be at least 1")
            data[key] = value
        data["trading_mode"] = "LIVE"
        data["trading_env"] = "live"
        return data

    m.MobileUI._page_live_trades = safe_page_live_trades
    m.MobileUI._render_account_cards = safe_render_account_cards
    m.MobileUI._render_live_positions = safe_render_live_positions
    m.MobileUI.collect = safe_collect

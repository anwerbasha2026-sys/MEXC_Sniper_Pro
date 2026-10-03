from __future__ import annotations

import time
import csv
import json
from pathlib import Path

from app.market.feature_engine import FeatureBook
from app.market.score_engine import ScoreEngine
from app.scanner.signal_state import SignalStateMachine
from app.paper.paper_trader import PaperTrader
from app.paper.risk_manager import PaperRiskManager


class LiveSignalScanner:
    """
    Connects raw MEXC protobuf messages to:
        market features -> score -> state machine

    No order execution is performed here.
    """

    def __init__(
        self,
        *,
        strong_threshold: float = 65.0,
        ready_threshold: float = 55.0,
        reset_threshold: float = 50.0,
        confirmations_required: int = 1,
        cooldown_seconds: float = 20.0,
        stale_after_ms: float = 5000.0,
        paper_starting_balance: float = 1000.0,
        paper_order_usdt: float = 50.0,
        paper_stop_loss_pct: float = 1.5,
        paper_take_profit_pct: float = 3.0,
        paper_max_open_positions: int = 5,
        paper_max_spread_pct: float = 0.20,
        paper_max_entry_drift_pct: float = 0.30,
        paper_min_top_ask_coverage_pct: float = 50.0,
        enabled_strategies: dict[str, bool] | None = None,
    ):
        self.features = FeatureBook()
        self.scorer = ScoreEngine(
            strong_threshold=strong_threshold,
            enabled_strategies=enabled_strategies,
        )
        self.state_machine = SignalStateMachine(
            ready_threshold=ready_threshold,
            trigger_threshold=strong_threshold,
            reset_threshold=reset_threshold,
            confirmations_required=1,
            cooldown_seconds=cooldown_seconds,
            stale_after_ms=stale_after_ms,
        )

        self.last_scores: dict[str, float] = {}
        self.last_snapshots: dict[str, object] = {}
        self.last_decisions: dict[str, object] = {}
        self.last_trade_events: list[dict] = []
        self.signal_history: list[dict] = []
        self.signal_log_path = Path("data/signals.csv")
        self.signal_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.wrappers_processed = 0
        self.snapshots_calculated = 0
        self.ready_snapshots = 0
        self.signal_candidates = 0
        self.signal_alerts = 0
        self.paper_opens = 0
        self.paper_open_rejections = 0
        self.paper_guard_rejections = 0
        self.paper_spread_rejections = 0
        self.paper_drift_rejections = 0
        self.paper_coverage_rejections = 0
        self.paper_risk_rejections = 0
        self.paper_closes = 0
        self.last_rejection_reason = ""
        self.last_entry_diagnostics: dict = {}
        self.paper_max_spread_pct = max(0.0, float(paper_max_spread_pct))
        self.paper_max_entry_drift_pct = max(0.0, float(paper_max_entry_drift_pct))
        self.paper_min_top_ask_coverage_pct = max(0.0, min(100.0, float(paper_min_top_ask_coverage_pct)))
        self.deal_messages_parsed = 0
        self.book_messages_parsed = 0
        self.invalid_deals = 0
        self.invalid_books = 0
        self.symbols_with_market_data: set[str] = set()
        self.last_market_data_at = 0.0
        self.last_body_kind = ""
        self.paper_trader = PaperTrader(
            risk_manager=PaperRiskManager(
                max_risk_per_trade_pct=0.50,
                max_daily_loss_pct=2.0,
                max_open_positions=paper_max_open_positions,
                max_total_exposure_pct=50.0,
                max_position_pct=10.0,
            ),
            starting_balance=paper_starting_balance,
            allocation_usdt=paper_order_usdt,
            stop_loss_pct=paper_stop_loss_pct,
            take_profit_pct=paper_take_profit_pct,
            max_open_positions=paper_max_open_positions,
            fee_rate=0.001,
            slippage_pct=0.05,
            db_path="data/mexc_sniper.db",
        )
        # The PaperTrader owns the SQLite connection; the scanner shares it for
        # the signal journal so both streams are committed to one durable file.
        self.db = self.paper_trader.db
        self._ensure_signal_log()
        self._load_signal_history()

    def close(self):
        """Flush and close the durable Paper/Signal journal."""
        self.paper_trader.shutdown()

    @staticmethod
    def safe_get(
        obj,
        name: str,
        default=None,
    ):
        if obj is None:
            return default

        try:
            return getattr(obj, name)
        except (AttributeError, KeyError, TypeError):
            return default

    @staticmethod
    def safe_float(
        value,
        default=0.0,
    ) -> float:
        try:
            if value is None:
                return default

            if isinstance(value, bytes):
                value = value.decode(
                    "utf-8",
                    errors="ignore",
                )

            if str(value).strip() == "":
                return default

            return float(value)

        except (ValueError, TypeError):
            return default

    @classmethod
    def _body_kind(cls, wrapper) -> str:
        """Return the protobuf oneof body name when available.

        Accessing a protobuf message field with ``getattr`` is not enough for
        oneof messages: protobuf can return an empty sub-message even when
        that body was *not* present on the wire.  Stage 18 used that pattern,
        which made book and deal messages look as if both bodies existed and
        could leave the feature pipeline with zero real snapshots.
        """
        try:
            kind = wrapper.WhichOneof("body")
            if kind:
                return str(kind)
        except (AttributeError, ValueError, KeyError, TypeError):
            pass

        channel = str(cls.safe_get(wrapper, "channel", "") or "")
        if "aggre.deals" in channel:
            return "publicAggreDeals"
        if "aggre.bookTicker" in channel:
            return "publicAggreBookTicker"
        return ""

    def _ensure_signal_log(self):
        if self.signal_log_path.exists():
            return
        fields = ["time", "symbol", "score", "setup", "state", "price", "pressure", "momentum", "volume", "imbalance", "spread", "reasons", "paper_action"]
        with self.signal_log_path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()

    def _load_signal_history(self):
        """Load the durable SQLite journal, falling back to legacy CSV."""
        try:
            rows = self.db.load_signals(limit=200)
            if rows:
                for row in rows:
                    try:
                        reasons = json.loads(row["reasons"] or "[]")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        reasons = []
                    self.signal_history.append({
                        "time": float(row["event_time"]),
                        "symbol": row["symbol"],
                        "score": float(row["score"]),
                        "setup": row["setup"],
                        "state": row["state"],
                        "price": float(row["price"]),
                        "pressure": float(row["pressure"]),
                        "momentum": float(row["momentum"]),
                        "volume": float(row["volume"]),
                        "imbalance": float(row["imbalance"]),
                        "spread": float(row["spread"]),
                        "reasons": reasons,
                        "paper_action": row["paper_action"],
                        "entry_diagnostics": json.loads(row["entry_diagnostics"] or "{}") if "entry_diagnostics" in row.keys() else {},
                    })
                return
        except Exception:
            pass

        # Stage 20/21 compatibility: import old CSV records into SQLite.
        if not self.signal_log_path.exists():
            return
        try:
            with self.signal_log_path.open("r", newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                event = {
                    "time": float(row.get("time") or 0),
                    "symbol": row.get("symbol", ""),
                    "score": float(row.get("score") or 0),
                    "setup": row.get("setup", ""),
                    "state": row.get("state", ""),
                    "price": float(row.get("price") or 0),
                    "pressure": float(row.get("pressure") or 0),
                    "momentum": float(row.get("momentum") or 0),
                    "volume": float(row.get("volume") or 0),
                    "imbalance": float(row.get("imbalance") or 0),
                    "spread": float(row.get("spread") or 0),
                    "reasons": [x for x in row.get("reasons", "").split(" | ") if x],
                    "paper_action": row.get("paper_action", ""),
                }
                self.db.insert_signal(event)
            for row in self.db.load_signals(limit=200):
                self.signal_history.append({
                    "time": float(row["event_time"]), "symbol": row["symbol"],
                    "score": float(row["score"]), "setup": row["setup"], "state": row["state"],
                    "price": float(row["price"]), "pressure": float(row["pressure"]),
                    "momentum": float(row["momentum"]), "volume": float(row["volume"]),
                    "imbalance": float(row["imbalance"]), "spread": float(row["spread"]),
                    "reasons": json.loads(row["reasons"] or "[]"),
                    "paper_action": row["paper_action"],
                })
        except (OSError, ValueError, TypeError):
            self.signal_history = []

    def _record_signal(self, snapshot, result, decision, paper_action: str, entry_diagnostics: dict | None = None):
        event = {
            "time": time.time(),
            "symbol": snapshot.symbol,
            "score": float(result.score),
            "setup": result.setup,
            "state": decision.state.value,
            "price": float(snapshot.price),
            "pressure": float(snapshot.buy_pressure_5s),
            "momentum": float(snapshot.price_change_5s_pct),
            "volume": float(snapshot.volume_acceleration),
            "imbalance": float(snapshot.book_imbalance),
            "spread": float(snapshot.spread_pct),
            "reasons": list(result.reasons),
            "paper_action": paper_action,
            "entry_diagnostics": entry_diagnostics or {},
        }
        self.signal_history.append(event)
        self.signal_history = self.signal_history[-200:]
        self.db.insert_signal(event)
        self.db.insert_entry_check(self.db.signal_key(event), event)
        fields = ["time", "symbol", "score", "setup", "state", "price", "pressure", "momentum", "volume", "imbalance", "spread", "reasons", "paper_action", "entry_diagnostics"]
        csv_row = dict(event)
        csv_row["reasons"] = " | ".join(event["reasons"])
        csv_row["entry_diagnostics"] = json.dumps(event.get("entry_diagnostics", {}), ensure_ascii=False)
        with self.signal_log_path.open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writerow(csv_row)
        return event

    def process_wrapper(
        self,
        wrapper,
    ):
        now = time.monotonic()
        self.wrappers_processed += 1
        self.last_trade_events = []

        body_kind = self._body_kind(wrapper)
        self.last_body_kind = body_kind or "unknown"
        wrapper_symbol = str(
            self.safe_get(wrapper, "symbol", "") or ""
        ).upper()
        channel = str(
            self.safe_get(wrapper, "channel", "") or ""
        )

        symbols_seen: set[str] = set()

        # The symbol lives on the protobuf wrapper.  The aggregated book
        # ticker body itself does not contain a symbol field.
        if body_kind == "publicAggreDeals" or "aggre.deals" in channel:
            deals = self.safe_get(wrapper, "publicAggreDeals")
            deal_items = self.safe_get(deals, "deals", []) or []

            if deal_items and wrapper_symbol:
                symbol = wrapper_symbol
                symbols_seen.add(symbol)
                engine = self.features.for_symbol(symbol)
                valid_in_message = 0

                for deal in deal_items:
                    price = self.safe_float(
                        self.safe_get(deal, "price", 0)
                    )
                    quantity = self.safe_float(
                        self.safe_get(deal, "quantity", 0)
                    )
                    trade_type = int(
                        self.safe_float(
                            self.safe_get(deal, "tradeType", 0)
                        )
                    )

                    if price <= 0 or quantity <= 0:
                        self.invalid_deals += 1
                        continue

                    # MEXC Spot public aggregated deals use:
                    # 1 = buy, 2 = sell.
                    if trade_type not in (1, 2):
                        self.invalid_deals += 1
                        continue

                    engine.add_trade(
                        price=price,
                        qty=quantity,
                        is_buy=trade_type == 1,
                        ts=now,
                    )
                    valid_in_message += 1

                if valid_in_message:
                    self.deal_messages_parsed += 1
                    self.symbols_with_market_data.add(symbol)
                    self.last_market_data_at = now
            else:
                # A deals channel message without a usable wrapper symbol is
                # not safe to attribute to another market.
                self.invalid_deals += 1

        elif body_kind == "publicAggreBookTicker" or "aggre.bookTicker" in channel:
            ticker = self.safe_get(wrapper, "publicAggreBookTicker")
            symbol = wrapper_symbol

            bid = self.safe_float(
                self.safe_get(
                    ticker,
                    "bidPrice",
                    self.safe_get(ticker, "bidprice", 0),
                )
            )
            ask = self.safe_float(
                self.safe_get(
                    ticker,
                    "askPrice",
                    self.safe_get(ticker, "askprice", 0),
                )
            )
            bid_qty = self.safe_float(
                self.safe_get(
                    ticker,
                    "bidQuantity",
                    self.safe_get(ticker, "bidquantity", 0),
                )
            )
            ask_qty = self.safe_float(
                self.safe_get(
                    ticker,
                    "askQuantity",
                    self.safe_get(ticker, "askquantity", 0),
                )
            )

            if symbol and bid > 0 and ask > 0 and ask >= bid:
                symbols_seen.add(symbol)
                engine = self.features.for_symbol(symbol)
                engine.add_book(
                    bid=bid,
                    ask=ask,
                    bid_qty=bid_qty,
                    ask_qty=ask_qty,
                    ts=now,
                )
                self.book_messages_parsed += 1
                self.symbols_with_market_data.add(symbol)
                self.last_market_data_at = now
            else:
                self.invalid_books += 1

        else:
            # Ignore unrelated protobuf bodies without manufacturing an empty
            # market snapshot. This keeps diagnostics honest.
            return []

        decisions = []

        for symbol in symbols_seen:
            snapshot = self.features.snapshot(symbol)
            result = self.scorer.score(snapshot)
            decision = self.state_machine.update(
                snapshot,
                result,
                now=now,
            )

            self.last_scores[symbol] = result.score
            self.last_snapshots[symbol] = snapshot
            self.last_decisions[symbol] = decision
            self.snapshots_calculated += 1
            if snapshot.ready:
                self.ready_snapshots += 1
            if result.score >= self.state_machine.trigger_threshold:
                self.signal_candidates += 1

            # Paper execution only. Every confirmed alert is journaled even if
            # the paper risk layer rejects opening a position.
            if decision.should_alert:
                self.signal_alerts += 1
                reference_price = float(decision.reference_price or snapshot.price or snapshot.ask or 0.0)
                ask_price = float(snapshot.ask or snapshot.price or 0.0)
                spread_pct = float(snapshot.spread_pct or 0.0)
                entry_drift_pct = (abs(ask_price - reference_price) / reference_price * 100.0) if reference_price > 0 and ask_price > 0 else 0.0
                top_ask_coverage_pct = ((ask_price * float(snapshot.ask_qty)) / self.paper_trader.allocation_usdt * 100.0) if ask_price > 0 and snapshot.ask_qty > 0 and self.paper_trader.allocation_usdt > 0 else 0.0
                # Evaluate all three market-entry protections independently.
                # Stage 25 used an ``elif`` chain, so one rejection hid the other
                # failing conditions and made long runs impossible to diagnose.
                guard_failures: list[str] = []
                if spread_pct > self.paper_max_spread_pct:
                    guard_failures.append(f"SPREAD: {spread_pct:.4f}% > {self.paper_max_spread_pct:.4f}%")
                    self.paper_spread_rejections += 1
                if entry_drift_pct > self.paper_max_entry_drift_pct:
                    guard_failures.append(f"DRIFT: {entry_drift_pct:.4f}% > {self.paper_max_entry_drift_pct:.4f}%")
                    self.paper_drift_rejections += 1
                if top_ask_coverage_pct < self.paper_min_top_ask_coverage_pct:
                    guard_failures.append(f"COVERAGE: {top_ask_coverage_pct:.1f}% < {self.paper_min_top_ask_coverage_pct:.1f}%")
                    self.paper_coverage_rejections += 1

                guard_reason = " | ".join(guard_failures)
                entry_diagnostics = {
                    "reference_price": reference_price, "ask_price": ask_price,
                    "spread_pct": spread_pct, "entry_drift_pct": entry_drift_pct,
                    "top_ask_coverage_pct": top_ask_coverage_pct,
                    "estimated_slippage_pct": float(self.paper_trader.slippage_pct),
                    "spread_limit_pct": self.paper_max_spread_pct,
                    "drift_limit_pct": self.paper_max_entry_drift_pct,
                    "coverage_limit_pct": self.paper_min_top_ask_coverage_pct,
                    "failed_checks": guard_failures,
                    "decision": "REJECTED_GUARD" if guard_failures else "PASSED_GUARD",
                    "rejection_reason": guard_reason,
                }
                self.last_entry_diagnostics = {"symbol": symbol, **entry_diagnostics}
                if guard_failures:
                    self.paper_open_rejections += 1
                    self.paper_guard_rejections += 1
                    paper_action = "REJECTED_GUARD"
                    self.last_rejection_reason = guard_reason
                else:
                    opened = self.paper_trader.open_long(
                        symbol=symbol, price=ask_price, score=result.score, setup=result.setup,
                    )
                    if opened is not None:
                        self.paper_opens += 1
                        paper_action = "OPENED"
                        self.last_trade_events.append({
                            "type": "OPEN", "symbol": symbol, "price": opened.entry_price,
                            "score": result.score, "setup": result.setup,
                            "entry_diagnostics": entry_diagnostics,
                        })
                    else:
                        self.paper_open_rejections += 1
                        self.paper_risk_rejections += 1
                        paper_action = "REJECTED_RISK"
                        self.last_rejection_reason = "Paper risk/balance/position limit rejected the alert"
                self._record_signal(snapshot, result, decision, paper_action, entry_diagnostics)

            if snapshot.price > 0:
                closed = self.paper_trader.update_price(
                    symbol=symbol,
                    price=snapshot.price,
                )
                if closed is not None:
                    self.paper_closes += 1
                    self.last_trade_events.append({
                        "type": "CLOSE",
                        "symbol": symbol,
                        "price": closed.exit_price,
                        "pnl": closed.pnl_usdt,
                        "reason": closed.reason,
                    })

            decisions.append((snapshot, result, decision))

        return decisions

    def diagnostics(self) -> dict:
        """Return compact live diagnostics for the GUI without touching the hot path."""
        scores = sorted(
            ((symbol, float(score)) for symbol, score in self.last_scores.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        return {
            "wrappers_processed": self.wrappers_processed,
            "snapshots_calculated": self.snapshots_calculated,
            "ready_snapshots": self.ready_snapshots,
            "score_candidates": self.signal_candidates,
            "signal_alerts": self.signal_alerts,
            "paper_opens": self.paper_opens,
            "paper_open_rejections": self.paper_open_rejections,
            "paper_guard_rejections": self.paper_guard_rejections,
            "paper_spread_rejections": self.paper_spread_rejections,
            "paper_drift_rejections": self.paper_drift_rejections,
            "paper_coverage_rejections": self.paper_coverage_rejections,
            "paper_risk_rejections": self.paper_risk_rejections,
            "paper_closes": self.paper_closes,
            "last_rejection_reason": self.last_rejection_reason,
            "last_entry_diagnostics": dict(self.last_entry_diagnostics),
            "deal_messages_parsed": self.deal_messages_parsed,
            "book_messages_parsed": self.book_messages_parsed,
            "invalid_deals": self.invalid_deals,
            "invalid_books": self.invalid_books,
            "symbols_with_market_data": len(self.symbols_with_market_data),
            "last_body_kind": self.last_body_kind,
            "last_market_data_age_ms": (
                max(0.0, (time.monotonic() - self.last_market_data_at) * 1000.0)
                if self.last_market_data_at else None
            ),
            "top_scores": scores[:10],
            "signal_history_count": self.db.count_signals(),
        }

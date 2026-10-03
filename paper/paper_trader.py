from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import csv
import time

from app.paper.risk_manager import PaperRiskManager
from app.storage.database import Database


class PositionSide(str, Enum):
    LONG = "LONG"


@dataclass
class PaperPosition:
    symbol: str
    side: PositionSide
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    opened_at: float
    entry_score: float
    entry_setup: str
    highest_price: float = 0.0
    lowest_price: float = 0.0

    def __post_init__(self):
        if self.highest_price <= 0:
            self.highest_price = self.entry_price
        if self.lowest_price <= 0:
            self.lowest_price = self.entry_price


@dataclass
class ClosedTrade:
    symbol: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl_usdt: float
    pnl_pct: float
    reason: str
    opened_at: float
    closed_at: float
    entry_score: float
    entry_setup: str


@dataclass
class PaperStats:
    closed_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_equity: float = 0.0

    @property
    def win_rate(self) -> float:
        return (self.wins / self.closed_trades * 100.0) if self.closed_trades else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss <= 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return self.gross_profit / self.gross_loss


class PaperTrader:
    """Spot-only paper simulator with durable state, trades and equity/DD.

    State is restored from SQLite at startup.  Closed trades are immutable
    journal rows.  Open positions and their last prices are persisted so a
    normal restart does not reset the simulated portfolio.
    """

    def __init__(
        self,
        *,
        starting_balance: float = 1000.0,
        allocation_usdt: float = 50.0,
        stop_loss_pct: float = 1.5,
        take_profit_pct: float = 3.0,
        max_open_positions: int = 5,
        fee_rate: float = 0.001,
        slippage_pct: float = 0.05,
        log_path: str = "data/paper_trades.csv",
        db_path: str = "data/mexc_sniper.db",
        risk_manager: PaperRiskManager | None = None,
    ):
        self.starting_balance = float(starting_balance)
        self.balance = float(starting_balance)
        self.allocation_usdt = float(allocation_usdt)
        self.stop_loss_pct = abs(float(stop_loss_pct))
        self.take_profit_pct = abs(float(take_profit_pct))
        self.max_open_positions = max(1, int(max_open_positions))
        self.fee_rate = max(0.0, float(fee_rate))
        self.slippage_pct = max(0.0, float(slippage_pct))

        self.positions: dict[str, PaperPosition] = {}
        self._last_prices: dict[str, float] = {}
        self.risk_manager = risk_manager or PaperRiskManager(
            max_risk_per_trade_pct=0.50,
            max_daily_loss_pct=2.0,
            max_open_positions=max_open_positions,
            max_total_exposure_pct=50.0,
            max_position_pct=10.0,
        )
        self.closed_trades: list[ClosedTrade] = []
        self.stats = PaperStats(peak_equity=self.balance)

        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = Database(db_path)
        self._last_persist = 0.0
        self._load_persistent_state()
        self._ensure_log()
        self._sync_legacy_csv()

    def shutdown(self) -> None:
        self._persist_state(force=True)
        try:
            self.db.export_legacy_csvs(
                self.log_path,
                self.log_path.parent / "signals.csv",
            )
        except Exception:
            pass
        self.db.close()

    def can_open(self, symbol: str) -> bool:
        symbol = symbol.upper()
        return (
            symbol not in self.positions
            and len(self.positions) < self.max_open_positions
            and self.balance >= self.allocation_usdt
        )

    def open_long(self, *, symbol: str, price: float, score: float, setup: str, now: float | None = None) -> PaperPosition | None:
        symbol = symbol.upper()
        if price <= 0 or not self.can_open(symbol):
            return None

        current_time = time.time() if now is None else float(now)
        entry_price = price * (1.0 + self.slippage_pct / 100.0)
        current_exposure = sum(p.entry_price * p.quantity for p in self.positions.values())
        risk = self.risk_manager.evaluate(
            equity=self.equity(),
            open_positions=len(self.positions),
            current_exposure=current_exposure,
            stop_distance_pct=self.stop_loss_pct,
            requested_allocation=self.allocation_usdt,
        )
        if not risk.allowed:
            return None

        allocation = risk.allocation_usdt
        quantity = allocation / entry_price
        entry_fee = allocation * self.fee_rate
        total_cost = allocation + entry_fee
        if total_cost > self.balance:
            return None

        stop_loss = entry_price * (1.0 - self.stop_loss_pct / 100.0)
        take_profit = entry_price * (1.0 + self.take_profit_pct / 100.0)
        self.balance -= total_cost

        position = PaperPosition(
            symbol=symbol,
            side=PositionSide.LONG,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=current_time,
            entry_score=float(score),
            entry_setup=str(setup),
        )
        self.positions[symbol] = position
        self._last_prices[symbol] = float(price)
        self._update_drawdown()
        self._persist_state(force=True)
        return position

    def update_price(self, symbol: str, price: float, now: float | None = None) -> ClosedTrade | None:
        symbol = symbol.upper()
        position = self.positions.get(symbol)
        if position is None or price <= 0:
            return None

        current_time = time.time() if now is None else float(now)
        self._last_prices[symbol] = float(price)
        position.highest_price = max(position.highest_price, price)
        position.lowest_price = min(position.lowest_price, price)
        self._update_drawdown()

        # Conservative rule: if one update crosses both levels, SL wins.
        if price <= position.stop_loss:
            return self.close(symbol=symbol, price=position.stop_loss, reason="STOP_LOSS", now=current_time)
        if price >= position.take_profit:
            return self.close(symbol=symbol, price=position.take_profit, reason="TAKE_PROFIT", now=current_time)

        self._persist_state(force=False)
        return None

    def close(self, *, symbol: str, price: float, reason: str, now: float | None = None) -> ClosedTrade | None:
        symbol = symbol.upper()
        position = self.positions.get(symbol)
        if position is None or price <= 0:
            return None

        current_time = time.time() if now is None else float(now)
        self._last_prices[symbol] = float(price)
        self._update_drawdown()

        self.positions.pop(symbol, None)
        exit_price = price * (1.0 - self.slippage_pct / 100.0)
        gross_value = exit_price * position.quantity
        exit_fee = gross_value * self.fee_rate
        invested = position.entry_price * position.quantity
        entry_fee = invested * self.fee_rate
        pnl = gross_value - exit_fee - invested - entry_fee
        pnl_pct = pnl / invested * 100.0 if invested > 0 else 0.0
        self.balance += gross_value - exit_fee
        self._last_prices.pop(symbol, None)

        trade = ClosedTrade(
            symbol=symbol,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            pnl_usdt=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
            opened_at=position.opened_at,
            closed_at=current_time,
            entry_score=position.entry_score,
            entry_setup=position.entry_setup,
        )
        self.closed_trades.append(trade)
        self.risk_manager.record_closed_pnl(trade.pnl_usdt)
        self._record_stats(trade)
        self._update_drawdown()
        self.db.insert_trade(trade)
        self.db.delete_position(symbol)
        self._append_log(trade)
        self._persist_state(force=True)
        return trade

    def equity(self, prices: dict[str, float] | None = None) -> float:
        total = self.balance
        mark_prices = self._last_prices if prices is None else prices
        for symbol, position in self.positions.items():
            price = mark_prices.get(symbol)
            total += (price * position.quantity) if price is not None and price > 0 else position.entry_price * position.quantity
        return total

    def summary(self, prices: dict[str, float] | None = None) -> dict:
        equity = self.equity(prices)
        dd_pct = (self.stats.max_drawdown / self.stats.peak_equity * 100.0) if self.stats.peak_equity > 0 else 0.0
        return {
            "balance": round(self.balance, 4),
            "equity": round(equity, 4),
            "open_positions": len(self.positions),
            "closed_trades": self.stats.closed_trades,
            "wins": self.stats.wins,
            "losses": self.stats.losses,
            "net_pnl_usdt": round(self.stats.net_pnl, 4),
            "win_rate_pct": round(self.stats.win_rate, 2),
            "profit_factor": round(self.stats.profit_factor, 3) if self.stats.profit_factor != float("inf") else "INF",
            "max_drawdown_usdt": round(self.stats.max_drawdown, 4),
            "max_drawdown_pct": round(dd_pct, 3),
            "peak_equity": round(self.stats.peak_equity, 4),
            "starting_balance": round(self.starting_balance, 4),
            "daily_realized_pnl": round(self.risk_manager.daily_realized_pnl, 4),
            "persistence": "SQLITE",
        }

    def _record_stats(self, trade: ClosedTrade):
        self.stats.closed_trades += 1
        self.stats.net_pnl += trade.pnl_usdt
        if trade.pnl_usdt > 0:
            self.stats.wins += 1
            self.stats.gross_profit += trade.pnl_usdt
        else:
            self.stats.losses += 1
            self.stats.gross_loss += abs(trade.pnl_usdt)

    def _update_drawdown(self):
        equity = self.equity()
        if equity > self.stats.peak_equity:
            self.stats.peak_equity = equity
        drawdown = max(0.0, self.stats.peak_equity - equity)
        if drawdown > self.stats.max_drawdown:
            self.stats.max_drawdown = drawdown

    def _persist_state(self, force: bool = False):
        now = time.monotonic()
        if not force and (now - self._last_persist) < 0.75:
            return
        self._last_persist = now
        self.db.save_paper_state(
            starting_balance=self.starting_balance,
            balance=self.balance,
            peak_equity=self.stats.peak_equity,
            max_drawdown=self.stats.max_drawdown,
            daily_realized_pnl=self.risk_manager.daily_realized_pnl,
            risk_day=self.risk_manager.day.isoformat(),
        )
        for symbol, position in self.positions.items():
            self.db.upsert_position(position, self._last_prices.get(symbol, position.entry_price))

    def _load_persistent_state(self):
        state = self.db.load_paper_state()
        rows = self.db.load_positions()
        trade_rows = self.db.load_trades()

        if state is not None:
            self.starting_balance = float(state["starting_balance"])
            self.balance = float(state["balance"])
            self.stats.peak_equity = float(state["peak_equity"])
            self.stats.max_drawdown = float(state["max_drawdown"])
            self.risk_manager.restore_daily_state(
                float(state["daily_realized_pnl"]),
                str(state["risk_day"]),
            )

        for row in rows:
            position = PaperPosition(
                symbol=str(row["symbol"]),
                side=PositionSide(str(row["side"])),
                entry_price=float(row["entry_price"]),
                quantity=float(row["quantity"]),
                stop_loss=float(row["stop_loss"]),
                take_profit=float(row["take_profit"]),
                opened_at=float(row["opened_at"]),
                entry_score=float(row["entry_score"]),
                entry_setup=str(row["entry_setup"]),
                highest_price=float(row["highest_price"]),
                lowest_price=float(row["lowest_price"]),
            )
            self.positions[position.symbol] = position
            self._last_prices[position.symbol] = float(row["last_price"])

        for row in trade_rows:
            self.closed_trades.append(
                ClosedTrade(
                    symbol=str(row["symbol"]),
                    entry_price=float(row["entry_price"]),
                    exit_price=float(row["exit_price"]),
                    quantity=float(row["quantity"]),
                    pnl_usdt=float(row["pnl_usdt"]),
                    pnl_pct=float(row["pnl_pct"]),
                    reason=str(row["reason"]),
                    opened_at=float(row["opened_at"]),
                    closed_at=float(row["closed_at"]),
                    entry_score=float(row["entry_score"]),
                    entry_setup=str(row["entry_setup"]),
                )
            )

        self._rebuild_stats()
        if self.stats.peak_equity <= 0:
            self.stats.peak_equity = self.equity()

    def _rebuild_stats(self):
        stats = PaperStats(peak_equity=self.stats.peak_equity or self.starting_balance)
        for trade in self.closed_trades:
            stats.closed_trades += 1
            stats.net_pnl += trade.pnl_usdt
            if trade.pnl_usdt > 0:
                stats.wins += 1
                stats.gross_profit += trade.pnl_usdt
            else:
                stats.losses += 1
                stats.gross_loss += abs(trade.pnl_usdt)
        stats.max_drawdown = self.stats.max_drawdown
        stats.peak_equity = self.stats.peak_equity or self.starting_balance
        self.stats = stats

    def _ensure_log(self):
        if self.log_path.exists():
            return
        fields = [
            "symbol", "entry_price", "exit_price", "quantity", "pnl_usdt", "pnl_pct",
            "reason", "opened_at", "closed_at", "entry_score", "entry_setup",
        ]
        with self.log_path.open("w", newline="", encoding="utf-8") as file:
            csv.DictWriter(file, fieldnames=fields).writeheader()

    def _append_log(self, trade: ClosedTrade):
        with self.log_path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=asdict(trade).keys())
            writer.writerow(asdict(trade))

    def _sync_legacy_csv(self):
        # If SQLite already contains the source of truth, refresh the legacy
        # CSV.  This also makes the stage transition backwards compatible.
        try:
            self.db.export_legacy_csvs(
                self.log_path,
                self.log_path.parent / "signals.csv",
            )
        except Exception:
            pass

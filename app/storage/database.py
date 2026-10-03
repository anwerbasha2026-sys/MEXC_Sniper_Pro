from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path


class Database:
    """Small SQLite journal used by Paper Trading and the signal pipeline.

    SQLite is part of Python's standard library, so no extra dependency is
    required.  WAL mode keeps GUI reads responsive while the scanner writes.
    """

    def __init__(self, path: str | Path = "data/mexc_sniper.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = self._open_connection_with_recovery()
        self.conn.row_factory = sqlite3.Row
        self._configure()
        self._schema()

    def _open_connection_with_recovery(self):
        """Open the SQLite journal and recover automatically if it is corrupt.

        A damaged journal must never prevent the trading UI from starting.
        The original database is preserved as a timestamped .corrupt backup,
        then a fresh schema is created by _schema().
        """
        try:
            conn = sqlite3.connect(
                self.path,
                timeout=10.0,
                check_same_thread=False,
            )
            # Opening can succeed even when the file is malformed; verify it.
            conn.execute("PRAGMA quick_check").fetchone()
            return conn
        except sqlite3.DatabaseError:
            try:
                if 'conn' in locals():
                    conn.close()
            except Exception:
                pass

            if self.path.exists():
                stamp = time.strftime("%Y%m%d_%H%M%S")
                backup = self.path.with_name(
                    f"{self.path.stem}.corrupt_{stamp}{self.path.suffix}"
                )
                try:
                    self.path.replace(backup)
                except OSError:
                    # If replacement is unavailable, keep the original and
                    # let SQLite create a fresh file only when possible.
                    pass

            # Stale WAL/SHM files can keep a damaged journal alive.
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(self.path) + suffix)
                try:
                    if sidecar.exists():
                        sidecar.unlink()
                except OSError:
                    pass

            return sqlite3.connect(
                self.path,
                timeout=10.0,
                check_same_thread=False,
            )

    def _configure(self) -> None:
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")

    def _schema(self) -> None:
        with self._lock, self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    starting_balance REAL NOT NULL,
                    balance REAL NOT NULL,
                    peak_equity REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    daily_realized_pnl REAL NOT NULL DEFAULT 0,
                    risk_day TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_positions (
                    symbol TEXT PRIMARY KEY,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    opened_at REAL NOT NULL,
                    entry_score REAL NOT NULL,
                    entry_setup TEXT NOT NULL,
                    highest_price REAL NOT NULL,
                    lowest_price REAL NOT NULL,
                    last_price REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_key TEXT UNIQUE,
                    symbol TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    pnl_usdt REAL NOT NULL,
                    pnl_pct REAL NOT NULL,
                    reason TEXT NOT NULL,
                    opened_at REAL NOT NULL,
                    closed_at REAL NOT NULL,
                    entry_score REAL NOT NULL,
                    entry_setup TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT UNIQUE,
                    event_time REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    score REAL NOT NULL,
                    setup TEXT NOT NULL,
                    state TEXT NOT NULL,
                    price REAL NOT NULL,
                    pressure REAL NOT NULL,
                    momentum REAL NOT NULL,
                    volume REAL NOT NULL,
                    imbalance REAL NOT NULL,
                    spread REAL NOT NULL,
                    reasons TEXT NOT NULL,
                    paper_action TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_signals_time
                    ON signals(event_time DESC);
                CREATE INDEX IF NOT EXISTS idx_trades_closed_at
                    ON paper_trades(closed_at DESC);

                CREATE TABLE IF NOT EXISTS entry_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL,
                    event_time REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    reference_price REAL NOT NULL,
                    ask_price REAL NOT NULL,
                    spread_pct REAL NOT NULL,
                    entry_drift_pct REAL NOT NULL,
                    top_ask_coverage_pct REAL NOT NULL,
                    estimated_slippage_pct REAL,
                    decision TEXT NOT NULL,
                    rejection_reason TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_entry_checks_time
                    ON entry_checks(event_time DESC);
                """
            )
            cols = {row[1] for row in self.conn.execute("PRAGMA table_info(signals)").fetchall()}
            if "entry_diagnostics" not in cols:
                self.conn.execute("ALTER TABLE signals ADD COLUMN entry_diagnostics TEXT NOT NULL DEFAULT '{}'")

    def close(self) -> None:
        with self._lock:
            self.conn.commit()
            self.conn.close()

    # ------------------------------------------------------------------
    # Paper state
    # ------------------------------------------------------------------
    def save_paper_state(
        self,
        *,
        starting_balance: float,
        balance: float,
        peak_equity: float,
        max_drawdown: float,
        daily_realized_pnl: float,
        risk_day: str,
    ) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO paper_state
                    (id, starting_balance, balance, peak_equity, max_drawdown,
                     daily_realized_pnl, risk_day, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    starting_balance=excluded.starting_balance,
                    balance=excluded.balance,
                    peak_equity=excluded.peak_equity,
                    max_drawdown=excluded.max_drawdown,
                    daily_realized_pnl=excluded.daily_realized_pnl,
                    risk_day=excluded.risk_day,
                    updated_at=excluded.updated_at
                """,
                (
                    float(starting_balance),
                    float(balance),
                    float(peak_equity),
                    float(max_drawdown),
                    float(daily_realized_pnl),
                    str(risk_day),
                    time.time(),
                ),
            )

    def load_paper_state(self):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM paper_state WHERE id=1"
            ).fetchone()

    def upsert_position(self, position, last_price: float) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO paper_positions
                    (symbol, side, entry_price, quantity, stop_loss, take_profit,
                     opened_at, entry_score, entry_setup, highest_price,
                     lowest_price, last_price, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    side=excluded.side,
                    entry_price=excluded.entry_price,
                    quantity=excluded.quantity,
                    stop_loss=excluded.stop_loss,
                    take_profit=excluded.take_profit,
                    opened_at=excluded.opened_at,
                    entry_score=excluded.entry_score,
                    entry_setup=excluded.entry_setup,
                    highest_price=excluded.highest_price,
                    lowest_price=excluded.lowest_price,
                    last_price=excluded.last_price,
                    updated_at=excluded.updated_at
                """,
                (
                    position.symbol,
                    str(position.side.value),
                    float(position.entry_price),
                    float(position.quantity),
                    float(position.stop_loss),
                    float(position.take_profit),
                    float(position.opened_at),
                    float(position.entry_score),
                    str(position.entry_setup),
                    float(position.highest_price),
                    float(position.lowest_price),
                    float(last_price),
                    time.time(),
                ),
            )

    def delete_position(self, symbol: str) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "DELETE FROM paper_positions WHERE symbol=?",
                (symbol.upper(),),
            )

    def load_positions(self):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM paper_positions ORDER BY opened_at ASC"
            ).fetchall()

    # ------------------------------------------------------------------
    # Closed trades
    # ------------------------------------------------------------------
    @staticmethod
    def trade_key(trade) -> str:
        return (
            f"{trade.symbol}|{trade.opened_at:.6f}|{trade.closed_at:.6f}|"
            f"{trade.entry_price:.12f}|{trade.exit_price:.12f}|{trade.reason}"
        )

    def insert_trade(self, trade) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO paper_trades
                    (trade_key, symbol, entry_price, exit_price, quantity,
                     pnl_usdt, pnl_pct, reason, opened_at, closed_at,
                     entry_score, entry_setup, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.trade_key(trade),
                    trade.symbol,
                    float(trade.entry_price),
                    float(trade.exit_price),
                    float(trade.quantity),
                    float(trade.pnl_usdt),
                    float(trade.pnl_pct),
                    str(trade.reason),
                    float(trade.opened_at),
                    float(trade.closed_at),
                    float(trade.entry_score),
                    str(trade.entry_setup),
                    time.time(),
                ),
            )

    def load_trades(self, limit: int | None = None):
        sql = "SELECT * FROM paper_trades ORDER BY closed_at ASC"
        params = ()
        if limit is not None:
            sql = "SELECT * FROM paper_trades ORDER BY closed_at DESC LIMIT ?"
            params = (int(limit),)
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        if limit is not None:
            rows = list(reversed(rows))
        return rows

    def count_trades(self) -> int:
        with self._lock:
            return int(self.conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0])

    # ------------------------------------------------------------------
    # Signal journal
    # ------------------------------------------------------------------
    @staticmethod
    def signal_key(event: dict) -> str:
        return (
            f"{event['time']:.6f}|{event['symbol']}|{event['score']:.6f}|"
            f"{event['price']:.12f}|{event['paper_action']}"
        )

    def insert_signal(self, event: dict) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO signals
                    (event_key, event_time, symbol, score, setup, state, price,
                     pressure, momentum, volume, imbalance, spread, reasons,
                     paper_action, entry_diagnostics, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.signal_key(event),
                    float(event["time"]),
                    str(event["symbol"]),
                    float(event["score"]),
                    str(event["setup"]),
                    str(event["state"]),
                    float(event["price"]),
                    float(event["pressure"]),
                    float(event["momentum"]),
                    float(event["volume"]),
                    float(event["imbalance"]),
                    float(event["spread"]),
                    json.dumps(event.get("reasons", []), ensure_ascii=False),
                    str(event.get("paper_action", "")),
                    json.dumps(event.get("entry_diagnostics", {}), ensure_ascii=False),
                    time.time(),
                ),
            )

    def insert_entry_check(self, event_key: str, event: dict) -> None:
        d = event.get("entry_diagnostics", {}) or {}
        with self._lock, self.conn:
            self.conn.execute(
                """INSERT INTO entry_checks
                    (event_key, event_time, symbol, reference_price, ask_price,
                     spread_pct, entry_drift_pct, top_ask_coverage_pct,
                     estimated_slippage_pct, decision, rejection_reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(event_key), float(event.get("time", time.time())), str(event.get("symbol", "")),
                 float(d.get("reference_price", 0.0)), float(d.get("ask_price", 0.0)),
                 float(d.get("spread_pct", 0.0)), float(d.get("entry_drift_pct", 0.0)),
                 float(d.get("top_ask_coverage_pct", 0.0)),
                 None if d.get("estimated_slippage_pct") is None else float(d.get("estimated_slippage_pct")),
                 str(d.get("decision", "")), str(d.get("rejection_reason", "")), time.time()))

    def load_entry_checks(self, limit: int = 200):
        with self._lock:
            return self.conn.execute("SELECT * FROM entry_checks ORDER BY event_time DESC LIMIT ?", (int(limit),)).fetchall()

    def load_signals(self, limit: int = 200):
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM signals ORDER BY event_time DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return rows

    def count_signals(self) -> int:
        with self._lock:
            return int(self.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0])

    def export_legacy_csvs(self, paper_csv: Path, signals_csv: Path) -> None:
        """Keep the existing CSV files usable for users/scripts from earlier stages."""
        import csv

        paper_csv.parent.mkdir(parents=True, exist_ok=True)
        with paper_csv.open("w", newline="", encoding="utf-8") as f:
            fields = [
                "symbol", "entry_price", "exit_price", "quantity", "pnl_usdt", "pnl_pct",
                "reason", "opened_at", "closed_at", "entry_score", "entry_setup",
            ]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in self.load_trades():
                writer.writerow({k: row[k] for k in fields})

        signals_csv.parent.mkdir(parents=True, exist_ok=True)
        with signals_csv.open("w", newline="", encoding="utf-8") as f:
            fields = [
                "time", "symbol", "score", "setup", "state", "price", "pressure",
                "momentum", "volume", "imbalance", "spread", "reasons", "paper_action",
            ]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in reversed(self.load_signals(limit=max(200, self.count_signals()))):
                reasons = json.loads(row["reasons"] or "[]")
                writer.writerow({
                    "time": row["event_time"],
                    "symbol": row["symbol"],
                    "score": row["score"],
                    "setup": row["setup"],
                    "state": row["state"],
                    "price": row["price"],
                    "pressure": row["pressure"],
                    "momentum": row["momentum"],
                    "volume": row["volume"],
                    "imbalance": row["imbalance"],
                    "spread": row["spread"],
                    "reasons": " | ".join(reasons),
                    "paper_action": row["paper_action"],
                })

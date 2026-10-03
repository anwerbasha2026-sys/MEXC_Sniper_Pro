import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import logging
import time

from app.alerts.telegram import TelegramAlerter
from app.config import settings
from app.exchange.spot_client import SpotClient
from app.exchange.symbol_discovery import SymbolDiscovery
from app.exchange.websocket_manager import MEXCSpotWebSocketManager
from app.scanner.live_signal_scanner import LiveSignalScanner
from app.trading.live_engine import LiveSpotEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logging.getLogger("mexc.websocket").setLevel(logging.WARNING)

scanner = LiveSignalScanner(strong_threshold=80.0)
live_engine = LiveSpotEngine()
telegram = TelegramAlerter(
    token=settings.telegram_bot_token,
    chat_id=settings.telegram_chat_id,
)

latest_rows: dict[str, dict] = {}
started_at = time.monotonic()
DASHBOARD_INTERVAL = 5.0
DASHBOARD_ROWS = 12


def format_signal(snapshot, result, decision):
    reasons = ", ".join(result.reasons) or "confirmed setup"
    return (
        "🚨 MEXC SPOT SNIPER\n\n"
        f"Symbol: {snapshot.symbol}\n"
        f"Score: {result.score:.1f}/100\n"
        f"Setup: {result.setup}\n"
        f"State: {decision.state.value}\n\n"
        f"Price: {snapshot.price:.8f}\n"
        f"5s Momentum: {snapshot.price_change_5s_pct:+.3f}%\n"
        f"Buy Pressure: {snapshot.buy_pressure_5s:.1%}\n"
        f"Volume Acceleration: {snapshot.volume_acceleration:.2f}x\n"
        f"Book Imbalance: {snapshot.book_imbalance:+.1%}\n"
        f"Spread: {snapshot.spread_pct:.4f}%\n\n"
        f"Reasons: {reasons}\n\n"
        f"Paper Equity: {scanner.paper_trader.equity():.2f} USDT\n"
        f"Paper Open Positions: {len(scanner.paper_trader.positions)}\n"
        f"Paper Net PnL: {scanner.paper_trader.stats.net_pnl:+.2f} USDT\n\n"
        "Mode: PAPER TRADING\n"
        "No live order was sent."
    )


def _fmt_price(price: float) -> str:
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:.4f}"
    return f"{price:.8f}"


def render_dashboard(manager) -> str:
    rows = sorted(
        latest_rows.values(),
        key=lambda row: row["score"],
        reverse=True,
    )[:DASHBOARD_ROWS]

    connected = sum(1 for c in manager.connections if c.connected)
    uptime = int(time.monotonic() - started_at)
    ready = sum(1 for row in latest_rows.values() if row["ready"])

    lines = [
        "",
        "=" * 112,
        "MEXC SPOT SNIPER | LIVE MARKET DASHBOARD (NO LIVE ORDERS)",
        "=" * 112,
        (
            f"WS {connected}/{len(manager.connections)} connected | "
            f"messages={manager._messages_received:,} | "
            f"symbols_seen={len(latest_rows)} | ready={ready} | "
            f"uptime={uptime}s | paper_positions={len(scanner.paper_trader.positions)} | "
            f"paper_pnl={scanner.paper_trader.stats.net_pnl:+.2f} USDT"
        ),
        "-" * 112,
        f"{'#':<3} {'SYMBOL':<16} {'SCORE':>7} {'PRICE':>14} {'BUY%':>7} {'VOL':>7} {'MOM%':>8} {'BOOK':>8} {'STATE':<14} SETUP",
        "-" * 112,
    ]

    if not rows:
        lines.append("Waiting for enough market data to calculate snapshots...")
    else:
        for idx, row in enumerate(rows, 1):
            lines.append(
                f"{idx:<3} {row['symbol']:<16} {row['score']:>7.2f} "
                f"{_fmt_price(row['price']):>14} {row['pressure']*100:>6.1f}% "
                f"{row['volume']:>6.2f}x {row['momentum']:>+7.3f}% "
                f"{row['imbalance']*100:>+7.1f}% {row['state']:<14} {row['setup']}"
            )

    lines.extend([
        "-" * 112,
        "Trigger: score >= 80 with state-machine confirmation | Display: top 12 scores | Execution: DISABLED",
        "=" * 112,
    ])
    return "\n".join(lines)


async def dashboard_loop(manager, stop_event: asyncio.Event):
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=DASHBOARD_INTERVAL)
        except asyncio.TimeoutError:
            print(render_dashboard(manager), flush=True)


async def on_message(wrapper):
    decisions = scanner.process_wrapper(wrapper)

    for snapshot, result, decision in decisions:
        latest_rows[snapshot.symbol] = {
            "ts": time.monotonic(),
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
        }

        if live_engine.enabled and snapshot.price > 0:
            try:
                closed = await asyncio.to_thread(
                    live_engine.update_price,
                    snapshot.symbol,
                    snapshot.price,
                )
                if closed is not None:
                    print(
                        f"[LIVE SELL] {snapshot.symbol} reason={closed['reason']} "
                        f"order={closed['order'].get('orderId', '')}",
                        flush=True,
                    )
            except Exception:
                logging.exception("LIVE SELL failed.")

        if decision.should_alert:
            # Live execution remains fail-closed and is disabled by default.
            if live_engine.enabled:
                try:
                    live_position = await asyncio.to_thread(
                        live_engine.open_long,
                        snapshot.symbol,
                        snapshot.price,
                        result.score,
                    )
                    if live_position is not None:
                        print(
                            f"[LIVE BUY] {snapshot.symbol} qty={live_position.quantity} "
                            f"entry={live_position.entry_price:.8f} "
                            f"order={live_position.entry_order_id}",
                            flush=True,
                        )
                except Exception:
                    logging.exception("LIVE BUY failed; no retry is automatic.")

            message = format_signal(snapshot, result, decision)
            print("\n" + "=" * 90 + "\n" + message + "\n" + "=" * 90, flush=True)

            if telegram.enabled:
                try:
                    await telegram.send(message)
                    print("[TELEGRAM] Alert sent.", flush=True)
                except Exception:
                    logging.exception("Telegram alert failed.")
            else:
                print("[TELEGRAM] Not configured; console alert only.", flush=True)


async def main():
    print("=" * 100)
    print("MEXC SPOT SNIPER - LIVE SIGNAL ENGINE")
    print("=" * 100)
    print("Market: SPOT ONLY")
    print("Trading: DISABLED")
    print("Execution: NO ORDERS")
    print("Scanner: dynamic Spot/USDT symbols")
    print("Score trigger: 80/100")
    print("Dashboard: every 5 seconds")
    print("=" * 100)

    discovery = SymbolDiscovery(
        client=SpotClient(),
        limit=max(1, int(settings.scanner_symbol_limit)),
        stablecoin_exclusion_enabled=bool(settings.stablecoin_exclusion_enabled),
        stablecoin_base_assets=settings.stablecoin_base_assets,
    )
    print("Discovering Spot/USDT symbols...")
    symbols = await discovery.discover()

    if not symbols:
        raise RuntimeError("No eligible Spot/USDT symbols were found.")

    print(f"Selected symbols: {len(symbols)}")
    print("[ENGINE] Building WebSocket manager...")

    manager = MEXCSpotWebSocketManager(
        symbols=[item.symbol for item in symbols],
        on_message=on_message,
        channels_per_connection=28,
        deal_interval="10ms",
        book_interval="100ms",
        ping_interval=20.0,
    )

    dashboard_stop = asyncio.Event()
    dashboard_task = asyncio.create_task(dashboard_loop(manager, dashboard_stop))

    try:
        print("[ENGINE] Starting WebSocket manager NOW...", flush=True)
        await manager.start()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        dashboard_stop.set()
        dashboard_task.cancel()
        await asyncio.gather(dashboard_task, return_exceptions=True)
        try:
            scanner.close()
        except Exception:
            logging.exception("Failed to close persistent Paper/Signal journal")
        await manager.stop()
        print("[ENGINE] Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")

import sys
from pathlib import Path

# Project root and generated protobuf directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = PROJECT_ROOT / "generated"

for import_path in (PROJECT_ROOT, GENERATED_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from typing import Awaitable, Callable

import websockets

from generated.PushDataV3ApiWrapper_pb2 import PushDataV3ApiWrapper


logger = logging.getLogger("mexc.websocket")


@dataclass
class WebSocketConnection:
    index: int
    channels: list[str]
    websocket: object | None = None
    task: asyncio.Task | None = None
    reconnect_delay: float = 1.0
    connected: bool = False
    stop: bool = False


MessageHandler = Callable[
    [PushDataV3ApiWrapper],
    Awaitable[None] | None,
]


class MEXCSpotWebSocketManager:
    """
    Multi-connection MEXC Spot WebSocket manager.
    """

    URL = "wss://wbs-api.mexc.com/ws"

    def __init__(
        self,
        symbols: list[str],
        on_message: MessageHandler,
        *,
        channels_per_connection: int = 28,
        deal_interval: str = "10ms",
        book_interval: str = "100ms",
        ping_interval: float = 20.0,
        reconnect_max_delay: float = 30.0,
    ):
        self.symbols = sorted(
            {
                str(symbol).upper()
                for symbol in symbols
                if symbol
            }
        )

        self.on_message = on_message

        self.channels_per_connection = max(
            1,
            min(int(channels_per_connection), 30),
        )

        self.deal_interval = deal_interval
        self.book_interval = book_interval
        self.ping_interval = ping_interval
        self.reconnect_max_delay = reconnect_max_delay

        self.connections: list[WebSocketConnection] = []
        self._stop_event = asyncio.Event()

        # Runtime statistics. These are intentionally lightweight so they do
        # not slow down the WebSocket receive path.
        self._messages_received = 0
        self._book_messages = 0
        self._deal_messages = 0
        self._last_symbol = ""
        self._handler_errors = 0
        self._last_handler_error = ""
        self._status_task: asyncio.Task | None = None

    def build_channels(self) -> list[str]:
        channels: list[str] = []

        for symbol in self.symbols:
            channels.append(
                f"spot@public.aggre.deals.v3.api.pb@"
                f"{self.deal_interval}@{symbol}"
            )

            channels.append(
                f"spot@public.aggre.bookTicker.v3.api.pb@"
                f"{self.book_interval}@{symbol}"
            )

        return channels

    def build_connection_plans(
        self,
    ) -> list[WebSocketConnection]:
        channels = self.build_channels()
        plans: list[WebSocketConnection] = []

        for start in range(
            0,
            len(channels),
            self.channels_per_connection,
        ):
            batch = channels[
                start:start + self.channels_per_connection
            ]

            plans.append(
                WebSocketConnection(
                    index=len(plans) + 1,
                    channels=batch,
                )
            )

        return plans

    async def start(self):
        if not self.symbols:
            raise ValueError(
                "No Spot symbols were supplied."
            )

        self.connections = self.build_connection_plans()

        logger.info(
            "Starting MEXC Spot manager: %s symbols, %s connections",
            len(self.symbols),
            len(self.connections),
        )

        tasks: list[asyncio.Task] = []

        self._status_task = asyncio.create_task(
            self._status_loop(),
            name="mexc-ws-status",
        )

        for connection in self.connections:
            task = asyncio.create_task(
                self._connection_loop(connection),
                name=f"mexc-ws-{connection.index}",
            )

            connection.task = task
            tasks.append(task)

        try:
            results = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

            # A normal GUI stop cancels the connection tasks.  Treat those
            # cancellations as an expected shutdown instead of bubbling
            # CancelledError into the Tk worker thread.  Real exceptions
            # from a connection still propagate so genuine failures remain
            # visible to the GUI.
            for result in results:
                if isinstance(result, asyncio.CancelledError):
                    continue
                if isinstance(result, BaseException):
                    raise result

        finally:
            await self.stop()

    async def stop(self):
        self._stop_event.set()

        status_task = self._status_task
        self._status_task = None
        if (
            status_task is not None
            and status_task is not asyncio.current_task()
            and not status_task.done()
        ):
            status_task.cancel()
            await asyncio.gather(
                status_task,
                return_exceptions=True,
            )

        current = asyncio.current_task()

        for connection in self.connections:
            connection.stop = True

            if connection.websocket is not None:
                try:
                    await connection.websocket.close()
                except Exception:
                    pass

        tasks: list[asyncio.Task] = []

        for connection in self.connections:
            task = connection.task

            if (
                task is not None
                and task is not current
                and not task.done()
            ):
                task.cancel()
                tasks.append(task)

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

    async def _status_loop(self):
        """Print a compact health summary every 5 seconds."""
        last_total = 0

        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                raise

            total = self._messages_received
            rate = (total - last_total) / 5.0
            last_total = total

            connected = sum(
                1 for connection in self.connections
                if connection.connected
            )

            logger.info(
                "WS STATUS | connections=%s/%s | symbols=%s | "
                "messages=%s | rate=%.1f/s | book=%s | deals=%s | "
                "handler_errors=%s | last=%s",
                connected,
                len(self.connections),
                len(self.symbols),
                total,
                rate,
                self._book_messages,
                self._deal_messages,
                self._handler_errors,
                self._last_symbol or "-",
            )

    async def _connection_loop(
        self,
        connection: WebSocketConnection,
    ):
        delay = 1.0

        while (
            not self._stop_event.is_set()
            and not connection.stop
        ):
            try:
                await self._run_connection(
                    connection
                )

                delay = 1.0

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                connection.connected = False

                logger.warning(
                    "MEXC WS #%s disconnected: %r",
                    connection.index,
                    exc,
                )

                jitter = random.uniform(
                    0.0,
                    0.5,
                )

                sleep_for = min(
                    delay + jitter,
                    self.reconnect_max_delay,
                )

                logger.info(
                    "MEXC WS #%s reconnecting in %.1fs",
                    connection.index,
                    sleep_for,
                )

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=sleep_for,
                    )

                except asyncio.TimeoutError:
                    pass

                delay = min(
                    delay * 2.0,
                    self.reconnect_max_delay,
                )

    async def _run_connection(
        self,
        connection: WebSocketConnection,
    ):
        logger.info(
            "Connecting MEXC WS #%s (%s channels)",
            connection.index,
            len(connection.channels),
        )

        async with websockets.connect(
            self.URL,
            ping_interval=None,
            max_size=None,
            open_timeout=15,
            close_timeout=5,
        ) as ws:

            connection.websocket = ws
            connection.connected = True

            subscription = {
                "method": "SUBSCRIPTION",
                "params": connection.channels,
            }

            await ws.send(
                json.dumps(subscription)
            )

            logger.info(
                "MEXC WS #%s subscribed to %s channels",
                connection.index,
                len(connection.channels),
            )

            receiver = asyncio.create_task(
                self._receive_loop(
                    connection,
                    ws,
                )
            )

            pinger = asyncio.create_task(
                self._ping_loop(
                    connection,
                    ws,
                )
            )

            try:
                done, pending = await asyncio.wait(
                    {receiver, pinger},
                    return_when=asyncio.FIRST_EXCEPTION,
                )

                for task in done:
                    if task.cancelled():
                        continue

                    exception = task.exception()

                    if exception is not None:
                        raise exception

                for task in pending:
                    task.cancel()

                await asyncio.gather(
                    *pending,
                    return_exceptions=True,
                )

            finally:
                receiver.cancel()
                pinger.cancel()

                await asyncio.gather(
                    receiver,
                    pinger,
                    return_exceptions=True,
                )

                connection.connected = False
                connection.websocket = None

    async def _receive_loop(
        self,
        connection: WebSocketConnection,
        ws,
    ):
        while (
            not self._stop_event.is_set()
            and not connection.stop
        ):
            raw = await ws.recv()

            if isinstance(raw, str):
                await self._handle_text(
                    raw,
                    connection,
                )
                continue

            wrapper = PushDataV3ApiWrapper()

            try:
                wrapper.ParseFromString(raw)

            except Exception:
                logger.exception(
                    "MEXC WS #%s protobuf decode failed",
                    connection.index,
                )
                continue

            # Keep the hot path quiet: count messages instead of printing
            # every WebSocket update to the console.
            symbol = str(getattr(wrapper, "symbol", "") or "").upper()
            channel = str(getattr(wrapper, "channel", "") or "")

            self._messages_received += 1
            if "bookTicker" in channel:
                self._book_messages += 1
            elif "deals" in channel:
                self._deal_messages += 1

            self._last_symbol = symbol

            # A malformed/edge-case market update must not tear down the
            # entire WebSocket connection.  Keep the stream alive, count the
            # callback error, and log the full traceback for diagnosis.
            try:
                result = self.on_message(wrapper)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                self._handler_errors += 1
                self._last_handler_error = repr(exc)
                logger.exception(
                    "MEXC WS #%s message handler failed; stream kept alive "
                    "symbol=%s channel=%s",
                    connection.index,
                    symbol or "-",
                    channel or "-",
                )
                continue

    async def _handle_text(
        self,
        raw: str,
        connection: WebSocketConnection,
    ):
        try:
            data = json.loads(raw)

        except json.JSONDecodeError:
            logger.debug(
                "MEXC WS #%s text: %s",
                connection.index,
                raw,
            )
            return

        logger.debug(
            "MEXC WS #%s control: %s",
            connection.index,
            data,
        )

    async def _ping_loop(
        self,
        connection: WebSocketConnection,
        ws,
    ):
        while (
            not self._stop_event.is_set()
            and not connection.stop
        ):
            await asyncio.sleep(
                self.ping_interval
            )

            await ws.send(
                json.dumps(
                    {"method": "PING"}
                )
            )

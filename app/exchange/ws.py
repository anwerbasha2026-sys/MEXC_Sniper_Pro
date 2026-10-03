import asyncio
import json
import websockets


class MEXCWebSocket:

    URL = "wss://wbs-api.mexc.com/ws"

    def __init__(
        self,
        streams,
        on_message,
    ):
        self.streams = streams
        self.on_message = on_message
        self.running = True

    async def subscribe(self, ws):

        payload = {
            "method": "SUBSCRIPTION",
            "params": self.streams,
        }

        await ws.send(
            json.dumps(payload)
        )

    async def run(self):

        while self.running:

            try:

                print(
                    f"Connecting WebSocket "
                    f"({len(self.streams)} streams)..."
                )

                async with websockets.connect(
                    self.URL,
                    ping_interval=None,
                    max_size=None,
                ) as ws:

                    await self.subscribe(ws)

                    print("WebSocket connected.")

                    ping_task = asyncio.create_task(
                        self._ping(ws)
                    )

                    try:

                        async for message in ws:

                            if isinstance(
                                message,
                                bytes,
                            ):
                                await self.on_message(
                                    message
                                )

                            else:

                                try:

                                    data = json.loads(
                                        message
                                    )

                                    if data.get("msg") == "PONG":
                                        continue

                                    print(
                                        "WS:",
                                        data,
                                    )

                                except Exception:
                                    pass

                    finally:

                        ping_task.cancel()

            except Exception as e:

                print(
                    "WebSocket disconnected:",
                    repr(e),
                )

                if self.running:
                    await asyncio.sleep(5)

    async def _ping(self, ws):

        while True:

            await asyncio.sleep(20)

            try:

                await ws.send(
                    json.dumps(
                        {
                            "method": "PING"
                        }
                    )
                )

            except Exception:
                return

    def stop(self):
        self.running = False
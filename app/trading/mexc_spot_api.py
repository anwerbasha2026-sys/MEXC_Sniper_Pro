from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

import httpx


class MEXCSpotAPIError(RuntimeError):
    pass


class MEXCSpotAPI:
    """Fail-closed MEXC Spot REST client with automatic server-time sync.

    Signed MEXC requests require a timestamp close to the exchange server time.
    This client keeps a small local offset based on /api/v3/time and refreshes it
    periodically. If MEXC returns error 700003, the offset is refreshed and the
    signed request is retried once.

    No withdrawal functionality is implemented.
    """

    BASE_URL = "https://api.mexc.com"
    DEFAULT_RECV_WINDOW = 5000
    MAX_RECV_WINDOW = 60000
    TIME_SYNC_TTL_SECONDS = 30.0

    def __init__(self, api_key: str, api_secret: str, timeout: float = 10.0):
        if not api_key or not api_secret:
            raise ValueError("MEXC API credentials are missing")

        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.timeout = timeout

        self._time_offset_ms = 0
        self._time_synced_at = 0.0

    def _request_server_time(self) -> int:
        url = self.BASE_URL + "/api/v3/time"

        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url)

        try:
            payload = response.json()
        except ValueError:
            raise MEXCSpotAPIError(
                f"Invalid MEXC server-time response: {response.text}"
            )

        if response.status_code >= 400:
            raise MEXCSpotAPIError(
                f"HTTP {response.status_code}: {payload}"
            )

        server_time = int(payload["serverTime"])
        return server_time

    def sync_time(self, force: bool = False) -> int:
        """Synchronize local timestamp generation with MEXC server time.

        Uses midpoint timing to reduce request-latency bias:
            estimated_server_at_midpoint =
                server_time + (local_after - local_before) / 2
        """

        now = time.monotonic()

        if (
            not force
            and self._time_synced_at
            and (now - self._time_synced_at) < self.TIME_SYNC_TTL_SECONDS
        ):
            return self._time_offset_ms

        local_before = int(time.time() * 1000)
        server_time = self._request_server_time()
        local_after = int(time.time() * 1000)

        midpoint_local = (local_before + local_after) // 2
        self._time_offset_ms = server_time - midpoint_local
        self._time_synced_at = time.monotonic()

        return self._time_offset_ms

    def server_timestamp_ms(self) -> int:
        self.sync_time()
        return int(time.time() * 1000) + self._time_offset_ms

    def time_sync_status(self) -> dict:
        offset = self.sync_time(force=True)

        return {
            "localTimeMs": int(time.time() * 1000),
            "offsetMs": offset,
            "estimatedServerTimeMs": self.server_timestamp_ms(),
        }

    def _signed_params(self, params: dict) -> dict:
        data = dict(params)

        recv_window = int(
            data.get("recvWindow", self.DEFAULT_RECV_WINDOW)
        )

        if recv_window <= 0 or recv_window > self.MAX_RECV_WINDOW:
            raise ValueError(
                f"recvWindow must be between 1 and {self.MAX_RECV_WINDOW}"
            )

        data["recvWindow"] = recv_window
        data["timestamp"] = self.server_timestamp_ms()

        query = urlencode(data, doseq=True)

        data["signature"] = hmac.new(
            self.api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()

        return data

    @staticmethod
    def _is_timestamp_error(exc: Exception) -> bool:
        text = str(exc)
        return "700003" in text or "Timestamp for this request is outside" in text

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        signed: bool = False,
        _retry_timestamp: bool = True,
    ):
        params = params or {}

        if signed:
            params = self._signed_params(params)

        headers = {"X-MEXC-APIKEY": self.api_key}
        url = self.BASE_URL + path

        with httpx.Client(timeout=self.timeout) as client:
            response = client.request(
                method,
                url,
                params=params,
                headers=headers,
            )

        try:
            payload = response.json()
        except ValueError:
            payload = response.text

        if response.status_code >= 400:
            exc = MEXCSpotAPIError(
                f"HTTP {response.status_code}: {payload}"
            )

            if signed and _retry_timestamp and self._is_timestamp_error(exc):
                # Re-sync immediately and retry exactly once.
                self.sync_time(force=True)
                return self._request(
                    method,
                    path,
                    params=self._remove_signature(params),
                    signed=True,
                    _retry_timestamp=False,
                )

            raise exc

        if (
            isinstance(payload, dict)
            and payload.get("code") not in (None, 0, 200)
        ):
            exc = MEXCSpotAPIError(
                f"MEXC error {payload.get('code')}: {payload.get('msg')}"
            )

            if signed and _retry_timestamp and self._is_timestamp_error(exc):
                self.sync_time(force=True)
                return self._request(
                    method,
                    path,
                    params=self._remove_signature(params),
                    signed=True,
                    _retry_timestamp=False,
                )

            raise exc

        return payload

    @staticmethod
    def _remove_signature(params: dict) -> dict:
        clean = dict(params)
        clean.pop("signature", None)
        clean.pop("timestamp", None)
        return clean

    def ping(self):
        return self._request("GET", "/api/v3/ping")

    def server_time(self):
        return self._request("GET", "/api/v3/time")

    def account(self):
        return self._request(
            "GET",
            "/api/v3/account",
            signed=True,
        )

    def book_ticker(self, symbol: str):
        return self._request(
            "GET",
            "/api/v3/ticker/bookTicker",
            params={"symbol": symbol.upper()},
        )

    def depth(self, symbol: str, limit: int = 20):
        return self._request(
            "GET",
            "/api/v3/depth",
            params={"symbol": symbol.upper(), "limit": int(limit)},
        )

    def exchange_info(self, symbol: str):
        return self._request(
            "GET",
            "/api/v3/exchangeInfo",
            params={"symbol": symbol.upper()},
        )

    def order_test(self, **params):
        return self._request(
            "POST",
            "/api/v3/order/test",
            params=params,
            signed=True,
        )

    def new_order(self, **params):
        return self._request(
            "POST",
            "/api/v3/order",
            params=params,
            signed=True,
        )

    def get_order(self, symbol: str, order_id: str):
        return self._request(
            "GET",
            "/api/v3/order",
            params={
                "symbol": symbol.upper(),
                "orderId": str(order_id),
            },
            signed=True,
        )

    def market_buy_quote(
        self,
        symbol: str,
        quote_usdt: float,
        client_order_id: str | None = None,
        test: bool = False,
    ):
        params = {
            "symbol": symbol.upper(),
            "side": "BUY",
            "type": "MARKET",
            "quoteOrderQty": self._fmt(quote_usdt),
        }

        if client_order_id:
            params["newClientOrderId"] = client_order_id

        return self.order_test(**params) if test else self.new_order(**params)

    def market_sell_quantity(
        self,
        symbol: str,
        quantity: float,
        client_order_id: str | None = None,
        test: bool = False,
    ):
        params = {
            "symbol": symbol.upper(),
            "side": "SELL",
            "type": "MARKET",
            "quantity": self._fmt(quantity),
        }

        if client_order_id:
            params["newClientOrderId"] = client_order_id

        return self.order_test(**params) if test else self.new_order(**params)

    @staticmethod
    def _fmt(value: float) -> str:
        return format(Decimal(str(value)), "f")

    @staticmethod
    def make_client_order_id(prefix: str = "SNIPER") -> str:
        return f"{prefix}_{uuid.uuid4().hex[:20]}"


def floor_to_step(value: float, step: str) -> float:
    """Round a quantity down to MEXC's baseSizePrecision."""
    step_d = Decimal(str(step))
    value_d = Decimal(str(value))

    if step_d <= 0:
        return value

    return float(
        (value_d / step_d).to_integral_value(rounding=ROUND_DOWN)
        * step_d
    )

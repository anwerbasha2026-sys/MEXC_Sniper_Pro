from __future__ import annotations

import time
from dataclasses import dataclass

from app.config import settings
from app.trading.mexc_spot_api import MEXCSpotAPI, floor_to_step


@dataclass
class LivePosition:
    symbol: str
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_order_id: str
    entry_score: float
    opened_at: float


class LiveSpotEngine:
    """Spot-only live execution with a fail-closed order lifecycle."""

    CONFIRMATION = "I_UNDERSTAND_REAL_MONEY"

    def __init__(self):
        self.api = MEXCSpotAPI(
            settings.mexc_api_key,
            settings.mexc_api_secret,
        )
        self.positions: dict[str, LivePosition] = {}

        self.enabled = (
            settings.trading_mode.value == "LIVE"
            and settings.live_trading_enabled
            and settings.live_runtime_armed
            and settings.live_trading_confirm == self.CONFIRMATION
            and settings.trading_env.lower() == "live"
        )

        self.max_open_positions = max(1, settings.live_max_open_positions)
        self.order_usdt = float(settings.live_order_usdt)
        self.stop_loss_pct = abs(float(settings.live_stop_loss_pct))
        self.take_profit_pct = abs(float(settings.live_take_profit_pct))
        self.max_slippage_pct = max(0.0, float(settings.live_max_slippage_pct))
        self.max_spread_pct = max(0.0, float(settings.live_max_spread_pct))
        self.max_entry_drift_pct = max(0.0, float(settings.live_max_entry_drift_pct))
        self.min_top_ask_coverage_pct = max(0.0, float(settings.live_min_top_ask_coverage_pct))

        # The configured hard ceiling is a real ceiling. Never raise it to match
        # the requested order size, otherwise the safety control becomes useless.
        configured_cap = float(getattr(settings, "live_hard_max_order_usdt", 100.0))
        self.hard_max_order_usdt = configured_cap if configured_cap > 0 else 100.0

    def preflight(self) -> dict:
        if not self.enabled:
            raise RuntimeError("Live trading gate is disabled")

        if self.order_usdt <= 0:
            raise RuntimeError("LIVE_ORDER_USDT must be positive")
        if self.order_usdt > self.hard_max_order_usdt:
            raise RuntimeError(
                f"LIVE_ORDER_USDT exceeds hard safety ceiling: {self.hard_max_order_usdt} USDT"
            )

        account = self.api.account()
        self._assert_spot_account(account)

        return {
            "accountType": account.get("accountType"),
            "canTrade": account.get("canTrade"),
            "permissions": account.get("permissions", []),
            "live_order_usdt": self.order_usdt,
            "max_open_positions": self.max_open_positions,
            "hard_max_order_usdt": self.hard_max_order_usdt,
            "usdt_free": self._free_balance(account, "USDT"),
            "usdt_total": self._total_balance(account, "USDT"),
        }

    @staticmethod
    def _assert_spot_account(account: dict) -> None:
        if account.get("accountType") != "SPOT":
            raise RuntimeError("MEXC account is not reported as SPOT")
        if not account.get("canTrade", False):
            raise RuntimeError("MEXC account cannot trade")
        if "SPOT" not in account.get("permissions", []):
            raise RuntimeError("API key does not report SPOT permission")

    def _symbol_rules(self, symbol: str) -> dict:
        info = self.api.exchange_info(symbol)
        if info.get("isSpotTradingAllowed") is False:
            raise RuntimeError(f"Spot trading disabled for {symbol}")

        symbols = info.get("symbols") or []
        if not symbols:
            return info

        item = next(
            (x for x in symbols if x.get("symbol") == symbol.upper()),
            symbols[0],
        )
        if item.get("isSpotTradingAllowed") is False:
            raise RuntimeError(f"Spot trading disabled for {symbol}")
        return item

    @staticmethod
    def _total_balance(account: dict, asset: str) -> float:
        for item in account.get("balances", []):
            if str(item.get("asset", "")).upper() == asset.upper():
                return float(item.get("total") or item.get("balance") or item.get("free") or 0)
        return 0.0

    @staticmethod
    def _asset_balances(account: dict, asset: str) -> tuple[float, float, float]:
        """Return free, locked and total for an asset from a MEXC account payload."""
        for item in account.get("balances", []) or []:
            if str(item.get("asset", "")).upper() != asset.upper():
                continue
            try:
                free = float(item.get("free") or item.get("available") or item.get("availableAmount") or 0)
                locked = float(item.get("locked") or item.get("frozen") or item.get("freeze") or 0)
                total_field = item.get("balance") or item.get("total")
                total = float(total_field) if total_field is not None else free + locked
                return max(0.0, free), max(0.0, locked), max(0.0, total)
            except (TypeError, ValueError):
                return 0.0, 0.0, 0.0
        return 0.0, 0.0, 0.0

    def sync_account_positions(
        self,
        min_notional_usdt: float = 1.0,
        account: dict | None = None,
    ) -> list[LivePosition]:
        """Make local real positions reflect the current MEXC Spot balances.

        This is deliberately account-driven. It updates quantities for positions
        already known by the app, imports holdings bought outside the app, and
        removes positions that no longer exist on the exchange. It never keeps a
        stale quantity after a partial/external sell.
        """
        account = account if account is not None else self.api.account()
        balances = account.get("balances", []) or []
        imported: list[LivePosition] = []
        observed_symbols: set[str] = set()

        for item in balances:
            asset = str(item.get("asset", "")).upper().strip()
            if not asset or asset == "USDT":
                continue

            free, locked, qty = self._asset_balances(account, asset)
            if qty <= 0:
                continue

            symbol = f"{asset}USDT"
            try:
                ticker = self.api.book_ticker(symbol)
                bid = float(ticker.get("bidPrice") or 0)
                ask = float(ticker.get("askPrice") or 0)
                current = bid if bid > 0 else ask
            except Exception:
                # Do not destroy a known position just because a ticker request
                # temporarily failed. The next account sync will retry it.
                continue

            if current <= 0 or qty * current < float(min_notional_usdt):
                continue

            observed_symbols.add(symbol)
            existing = self.positions.get(symbol)
            if existing is not None:
                # Quantity is always authoritative from the exchange. Preserve
                # the entry metadata for positions opened by this process.
                existing.quantity = qty
                imported.append(existing)
                continue

            position = LivePosition(
                symbol=symbol,
                quantity=qty,
                entry_price=current,
                stop_loss=0.0,
                take_profit=0.0,
                entry_order_id="ACCOUNT_SYNC",
                entry_score=0.0,
                opened_at=time.time(),
            )
            self.positions[symbol] = position
            imported.append(position)

        # A successful account response is the source of truth. Remove stale
        # local positions that have disappeared from the exchange balance set.
        for symbol in list(self.positions):
            if symbol not in observed_symbols:
                asset = symbol[:-4] if symbol.endswith("USDT") else symbol
                _, _, total = self._asset_balances(account, asset)
                if total <= 0:
                    self.positions.pop(symbol, None)

        return imported

    def account_snapshot(self) -> dict:
        account = self.api.account()
        return {
            "accountType": account.get("accountType"),
            "canTrade": account.get("canTrade"),
            "permissions": account.get("permissions", []),
            "usdt_free": self._free_balance(account, "USDT"),
            "usdt_total": self._total_balance(account, "USDT"),
            "balances": account.get("balances", []),
            "_raw_account": account,
        }

    @staticmethod
    def _free_balance(account: dict, asset: str) -> float:
        free, _, _ = LiveSpotEngine._asset_balances(account, asset)
        return free

    def _validate_quote_order(self, rules: dict) -> None:
        min_quote = float(
            rules.get("quoteAmountPrecisionMarket")
            or rules.get("quoteAmountPrecision")
            or 0
        )
        max_quote = float(
            rules.get("maxQuoteAmountMarket")
            or rules.get("maxQuoteAmount")
            or 0
        )

        if min_quote and self.order_usdt < min_quote:
            raise RuntimeError(
                f"Order amount below MEXC minimum for {rules.get('symbol')}: {min_quote}"
            )
        if max_quote and self.order_usdt > max_quote:
            raise RuntimeError(
                f"Order amount above MEXC maximum for {rules.get('symbol')}: {max_quote}"
            )

    def open_long(self, symbol: str, price: float, score: float):
        symbol = symbol.upper()

        if not self.enabled:
            raise RuntimeError("Live trading is disabled")
        if self.order_usdt > self.hard_max_order_usdt:
            raise RuntimeError(
                f"LIVE_ORDER_USDT {self.order_usdt} exceeds hard safety ceiling {self.hard_max_order_usdt}"
            )
        if symbol in self.positions:
            return None
        if len(self.positions) >= self.max_open_positions:
            return None
        if price <= 0:
            return None

        rules = self._symbol_rules(symbol)
        self._validate_quote_order(rules)

        book = self.api.book_ticker(symbol)
        bid = float(book.get("bidPrice") or 0)
        ask = float(book.get("askPrice") or 0)
        ask_qty = float(book.get("askQty") or 0)
        if bid <= 0 or ask <= 0 or ask < bid:
            raise RuntimeError(f"Invalid live book ticker for {symbol}: {book}")

        spread_pct = (ask - bid) / bid * 100.0
        if spread_pct > self.max_spread_pct:
            raise RuntimeError(
                f"LIVE entry rejected: spread {spread_pct:.4f}% > {self.max_spread_pct:.4f}%"
            )

        entry_drift_pct = abs(ask - price) / price * 100.0
        if entry_drift_pct > self.max_entry_drift_pct:
            raise RuntimeError(
                f"LIVE entry rejected: price drift {entry_drift_pct:.4f}% > {self.max_entry_drift_pct:.4f}%"
            )

        depth = self.api.depth(symbol, limit=20)
        asks = depth.get("asks") or []
        if not asks:
            raise RuntimeError(f"LIVE entry rejected: empty ask depth for {symbol}")

        remaining_quote = self.order_usdt
        base_qty = 0.0
        spent_quote = 0.0
        for level in asks:
            level_price = float(level[0])
            level_qty = float(level[1])
            if level_price <= 0 or level_qty <= 0:
                continue
            level_quote = level_price * level_qty
            take_quote = min(remaining_quote, level_quote)
            base_qty += take_quote / level_price
            spent_quote += take_quote
            remaining_quote -= take_quote
            if remaining_quote <= 1e-12:
                break

        if remaining_quote > 1e-9 or base_qty <= 0:
            raise RuntimeError(
                f"LIVE entry rejected: insufficient visible ask liquidity for {self.order_usdt:.2f} USDT"
            )

        estimated_vwap = spent_quote / base_qty
        slippage_pct = (estimated_vwap - ask) / ask * 100.0
        if slippage_pct > self.max_slippage_pct:
            raise RuntimeError(
                f"LIVE entry rejected: estimated slippage {slippage_pct:.4f}% > {self.max_slippage_pct:.4f}%"
            )

        if ask_qty > 0:
            top_quote = ask * ask_qty
            top_coverage_pct = top_quote / self.order_usdt * 100.0
            if top_coverage_pct < self.min_top_ask_coverage_pct:
                raise RuntimeError(
                    f"LIVE entry rejected: top ask covers {top_coverage_pct:.1f}% of order; minimum is {self.min_top_ask_coverage_pct:.1f}%"
                )

        account = self.api.account()
        self._assert_spot_account(account)
        free_usdt = self._free_balance(account, "USDT")
        required = self.order_usdt * 1.002
        if free_usdt < required:
            raise RuntimeError(
                f"Insufficient free USDT: {free_usdt:.8f}; required at least {required:.8f}"
            )

        client_id = self.api.make_client_order_id("SNIPERBUY")
        order = self.api.market_buy_quote(
            symbol,
            self.order_usdt,
            client_order_id=client_id,
        )

        order_id = str(order.get("orderId", ""))
        if not order_id:
            raise RuntimeError(f"BUY response has no orderId: {order}")

        status = self.api.get_order(symbol, order_id)
        executed_qty = float(status.get("executedQty") or order.get("executedQty") or 0)
        executed_quote = float(
            status.get("cummulativeQuoteQty")
            or order.get("cummulativeQuoteQty")
            or 0
        )
        if executed_qty <= 0:
            raise RuntimeError(f"BUY order {order_id} has no executed quantity yet: {status}")

        avg_price = executed_quote / executed_qty if executed_quote > 0 else price

        position = LivePosition(
            symbol=symbol,
            quantity=executed_qty,
            entry_price=avg_price,
            stop_loss=avg_price * (1 - self.stop_loss_pct / 100),
            take_profit=avg_price * (1 + self.take_profit_pct / 100),
            entry_order_id=order_id,
            entry_score=float(score),
            opened_at=time.time(),
        )
        self.positions[symbol] = position
        return position

    def update_price(self, symbol: str, price: float):
        position = self.positions.get(symbol.upper())
        if position is None or price <= 0:
            return None

        if position.stop_loss > 0 and price <= position.stop_loss:
            return self.close(symbol, "STOP_LOSS")
        if position.take_profit > 0 and price >= position.take_profit:
            return self.close(symbol, "TAKE_PROFIT")
        return None

    def close(self, symbol: str, reason: str):
        """Sell only currently free quantity and reconcile the remainder."""
        symbol = symbol.upper()
        position = self.positions.get(symbol)
        if position is None:
            return None

        rules = self._symbol_rules(symbol)
        step = str(rules.get("baseSizePrecision") or "0.00000001")

        # Never submit a sell for locked/unavailable funds. This also handles
        # external/manual partial sells between UI refreshes.
        account_before = self.api.account()
        asset = symbol[:-4] if symbol.endswith("USDT") else symbol
        free_qty, _, total_before = self._asset_balances(account_before, asset)
        sellable = min(position.quantity, free_qty)
        quantity = floor_to_step(sellable, step)
        if quantity <= 0:
            if total_before <= 0:
                self.positions.pop(symbol, None)
            raise RuntimeError(
                f"No free {asset} quantity available to sell; locked balance is not sellable"
            )

        client_id = self.api.make_client_order_id("SNIPERSELL")
        result = self.api.market_sell_quantity(
            symbol,
            quantity,
            client_order_id=client_id,
        )
        order_id = str(result.get("orderId", ""))
        if not order_id:
            raise RuntimeError(f"SELL response has no orderId: {result}")

        status = self.api.get_order(symbol, order_id)
        executed_qty = float(status.get("executedQty") or 0)
        if executed_qty <= 0:
            raise RuntimeError(
                f"SELL order {order_id} has no executed quantity yet: {status}"
            )

        # Re-read the exchange balance after the sell. Do not remove a position
        # merely because a partial fill occurred.
        account_after = self.api.account()
        _, _, remaining_total = self._asset_balances(account_after, asset)
        if remaining_total > 0:
            position.quantity = remaining_total
        else:
            self.positions.pop(symbol, None)

        return {
            "reason": reason,
            "position": position,
            "order": status,
            "remaining_quantity": remaining_total,
        }

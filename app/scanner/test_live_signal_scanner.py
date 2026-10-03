from types import SimpleNamespace

from app.scanner.live_signal_scanner import LiveSignalScanner


class FakeWrapper:
    def __init__(self, kind, symbol, channel, deals=None, ticker=None):
        self._kind = kind
        self.symbol = symbol
        self.channel = channel
        self.publicAggreDeals = deals or SimpleNamespace(deals=[])
        self.publicAggreBookTicker = ticker or SimpleNamespace(
            bidPrice="0",
            askPrice="0",
            bidQuantity="0",
            askQuantity="0",
        )

    def WhichOneof(self, name):
        assert name == "body"
        return self._kind


def deal_wrapper(symbol="TESTUSDT", price="1.0000", qty="100"):
    deals = SimpleNamespace(
        deals=[
            SimpleNamespace(price=price, quantity=qty, tradeType=1),
        ]
    )
    return FakeWrapper(
        "publicAggreDeals",
        symbol,
        f"spot@public.aggre.deals.v3.api.pb@10ms@{symbol}",
        deals=deals,
    )


def book_wrapper(symbol="TESTUSDT"):
    ticker = SimpleNamespace(
        bidPrice="0.9990",
        askPrice="1.0010",
        bidQuantity="1000",
        askQuantity="500",
    )
    return FakeWrapper(
        "publicAggreBookTicker",
        symbol,
        f"spot@public.aggre.bookTicker.v3.api.pb@100ms@{symbol}",
        ticker=ticker,
    )


def test_oneof_body_is_used_and_deals_create_snapshots():
    scanner = LiveSignalScanner(
        strong_threshold=65.0,
        confirmations_required=1
    )

    # Book updates must not be mistaken for empty deal messages.
    decisions = scanner.process_wrapper(book_wrapper())
    assert decisions
    assert scanner.book_messages_parsed == 1
    assert scanner.deal_messages_parsed == 0

    # Several real deal messages build the rolling trade history.
    for _ in range(4):
        decisions = scanner.process_wrapper(deal_wrapper())

    assert scanner.deal_messages_parsed == 4
    assert scanner.snapshots_calculated >= 5
    assert scanner.ready_snapshots >= 1
    assert scanner.last_body_kind == "publicAggreDeals"
    assert scanner.diagnostics()["symbols_with_market_data"] == 1


def test_unrelated_body_does_not_create_fake_snapshots():
    scanner = LiveSignalScanner()
    wrapper = FakeWrapper("publicMiniTicker", "TESTUSDT", "spot@public.miniTicker.v3.api.pb@TESTUSDT")
    assert scanner.process_wrapper(wrapper) == []
    assert scanner.snapshots_calculated == 0

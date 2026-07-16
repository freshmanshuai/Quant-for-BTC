import unittest


class FakeExchange:
    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None, params=None):
        self.calls.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "since": since,
            "limit": limit,
            "params": params or {},
        })
        if not self.batches:
            return []
        return self.batches.pop(0)


class FakeDerivativeExchange(FakeExchange):
    def fetch_funding_rate_history(self, symbol, since=None, limit=None, params=None):
        self.calls.append({"method": "funding", "symbol": symbol, "since": since, "limit": limit, "params": params or {}})
        return [
            {"timestamp": 1700000000000, "fundingRate": "0.0001"},
            {"timestamp": 1700028800000, "fundingRate": "0.0002"},
        ]

    def fetch_open_interest_history(self, symbol, timeframe, since=None, limit=None, params=None):
        self.calls.append({
            "method": "open_interest",
            "symbol": symbol,
            "timeframe": timeframe,
            "since": since,
            "limit": limit,
            "params": params or {},
        })
        return [
            {"timestamp": 1700000000000, "openInterestAmount": "1000"},
            {"timestamp": 1700014400000, "openInterestAmount": "1100"},
        ]


class FakeOrderBookExchange(FakeExchange):
    def __init__(self):
        super().__init__([])
        self.order_book_calls = []

    def fetch_order_book(self, symbol, limit=None):
        self.order_book_calls.append({"symbol": symbol, "limit": limit})
        return {
            "timestamp": 1700000000123,
            "bids": [[100.0, 1.5], [99.5, 2.0]],
            "asks": [[100.5, 1.2], [101.0, 2.4]],
        }


class CcxtConnectorTest(unittest.TestCase):
    def test_binance_swap_uses_usdm_factory_and_returns_normalized_bars(self):
        from quant_platform.connectors_ccxt import CcxtExchangeConnector
        from quant_platform.core import AssetSpec, MarketSpec

        exchange = FakeExchange([
            [
                [1700000000000, 100, 110, 90, 105, 1234],
                [1700003600000, 105, 115, 95, 108, 2345],
            ],
        ])
        factory_calls = []

        def factory(exchange_id, market_type, config):
            factory_calls.append((exchange_id, market_type, config))
            return exchange

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )
        connector = CcxtExchangeConnector(exchange_factory=factory)

        df = connector.fetch_bars(market, "1h", limit=2)

        self.assertEqual(factory_calls[0][0], "binance")
        self.assertEqual(factory_calls[0][1], "swap")
        self.assertEqual(list(df.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(len(df), 2)
        self.assertEqual(float(df.iloc[-1]["Close"]), 108.0)
        self.assertEqual(str(df.index.tz), "UTC")

    def test_fetch_bars_passes_since_and_filters_configured_window(self):
        import pandas as pd

        from quant_platform.connectors_ccxt import CcxtExchangeConnector
        from quant_platform.core import AssetSpec, MarketSpec

        exchange = FakeExchange([
            [
                [1700000000000, 100, 110, 90, 105, 1234],
                [1700003600000, 105, 115, 95, 108, 2345],
                [1700007200000, 108, 118, 98, 111, 3456],
                [1700010800000, 111, 121, 101, 114, 4567],
            ],
        ])
        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )
        connector = CcxtExchangeConnector(exchange_factory=lambda *_: exchange)

        df = connector.fetch_bars(
            market,
            "1h",
            limit=4,
            start=pd.Timestamp("2023-11-14T23:13:20Z"),
            end=pd.Timestamp("2023-11-15T00:13:20Z"),
        )

        self.assertEqual(exchange.calls[0]["since"], 1700003600000)
        self.assertEqual(exchange.calls[0]["params"], {"endTime": 1700007200000})
        self.assertEqual(
            list(df.index),
            [
                pd.Timestamp("2023-11-14T23:13:20Z"),
                pd.Timestamp("2023-11-15T00:13:20Z"),
            ],
        )
        self.assertEqual(float(df.iloc[-1]["Close"]), 111.0)

    def test_binanceus_swap_is_rejected_before_remote_call(self):
        from quant_platform.connectors_ccxt import CcxtExchangeConnector, ConnectorError
        from quant_platform.core import AssetSpec, MarketSpec

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binanceus",
            market_type="swap",
        )
        connector = CcxtExchangeConnector(exchange_factory=lambda *_: FakeExchange([]))

        with self.assertRaisesRegex(ConnectorError, "BinanceUS does not support swap"):
            connector.fetch_bars(market, "4h", limit=10)

    def test_fetch_bars_retries_and_reports_root_cause(self):
        from quant_platform.connectors_ccxt import CcxtExchangeConnector, ConnectorError
        from quant_platform.core import AssetSpec, MarketSpec

        class BrokenExchange:
            def fetch_ohlcv(self, symbol, timeframe, limit, params=None):
                raise RuntimeError("network down")

        market = MarketSpec(
            asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
            exchange="okx",
            market_type="spot",
        )
        connector = CcxtExchangeConnector(
            exchange_factory=lambda *_: BrokenExchange(),
            max_retries=2,
            retry_sleep=lambda _: None,
        )

        with self.assertRaisesRegex(ConnectorError, "network down"):
            connector.fetch_bars(market, "1h", limit=10)

    def test_fetch_derivatives_returns_funding_and_open_interest_frame(self):
        from quant_platform.connectors_ccxt import CcxtExchangeConnector
        from quant_platform.core import AssetSpec, MarketSpec

        exchange = FakeDerivativeExchange([])
        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )
        connector = CcxtExchangeConnector(exchange_factory=lambda *_: exchange)

        df = connector.fetch_derivatives(market, funding_limit=2, open_interest_timeframe="4h", open_interest_limit=2)

        self.assertEqual(list(df.columns), ["funding_rate", "open_interest"])
        self.assertEqual(float(df["funding_rate"].dropna().iloc[0]), 0.0001)
        self.assertEqual(float(df["open_interest"].dropna().iloc[-1]), 1100.0)
        self.assertEqual(str(df.index.tz), "UTC")
        self.assertEqual(exchange.calls[0]["method"], "funding")
        self.assertEqual(exchange.calls[1]["method"], "open_interest")

    def test_fetch_derivatives_passes_since_and_filters_configured_window(self):
        import pandas as pd

        from quant_platform.connectors_ccxt import CcxtExchangeConnector
        from quant_platform.core import AssetSpec, MarketSpec

        exchange = FakeDerivativeExchange([])
        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )
        connector = CcxtExchangeConnector(exchange_factory=lambda *_: exchange)

        df = connector.fetch_derivatives(
            market,
            funding_limit=2,
            open_interest_timeframe="4h",
            open_interest_limit=2,
            start=pd.Timestamp(1700000000000, unit="ms", tz="UTC"),
            end=pd.Timestamp(1700000000000, unit="ms", tz="UTC"),
        )

        self.assertEqual(exchange.calls[0]["since"], 1700000000000)
        self.assertEqual(exchange.calls[1]["since"], 1700000000000)
        self.assertEqual(list(df.index), [pd.Timestamp(1700000000000, unit="ms", tz="UTC")])
        self.assertEqual(float(df.iloc[0]["funding_rate"]), 0.0001)

    def test_fetch_order_book_snapshots_returns_normalized_depth_frame(self):
        from quant_platform.connectors_ccxt import CcxtExchangeConnector
        from quant_platform.core import AssetSpec, MarketSpec

        exchange = FakeOrderBookExchange()
        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )
        connector = CcxtExchangeConnector(exchange_factory=lambda *_: exchange)

        df = connector.fetch_order_book_snapshots(market, depth=2, sample_interval="snapshot")

        self.assertEqual(exchange.order_book_calls, [{"symbol": "BTC/USDT", "limit": 2}])
        self.assertEqual(
            list(df.columns),
            [
                "bid_price_1",
                "bid_size_1",
                "bid_price_2",
                "bid_size_2",
                "ask_price_1",
                "ask_size_1",
                "ask_price_2",
                "ask_size_2",
                "spread",
            ],
        )
        self.assertEqual(str(df.index[0]), "2023-11-14 22:13:20.123000+00:00")
        self.assertEqual(str(df.index.tz), "UTC")
        self.assertEqual(float(df.iloc[0]["bid_price_1"]), 100.0)
        self.assertEqual(float(df.iloc[0]["ask_price_2"]), 101.0)
        self.assertEqual(float(df.iloc[0]["spread"]), 0.5)


if __name__ == "__main__":
    unittest.main()

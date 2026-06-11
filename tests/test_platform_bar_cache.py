import unittest

import pandas as pd


class BarCacheTest(unittest.TestCase):
    def test_fetch_bars_with_cache_reads_store_before_connector(self):
        from quant_platform import fetch_bars_with_cache
        from quant_platform.core import AssetSpec, MarketSpec

        cached = pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [110.0, 111.0],
                "Low": [90.0, 91.0],
                "Close": [105.0, 106.0],
                "Volume": [10.0, 11.0],
            },
            index=pd.to_datetime(["2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"], utc=True),
        )
        calls = {"read": 0, "write": 0, "fetch": 0}

        class FakeStore:
            def read(self, series_id):
                calls["read"] += 1
                calls["series_id"] = series_id
                return cached

            def write(self, series_id, bars):
                calls["write"] += 1

        class FakeConnector:
            def fetch_bars(self, market, timeframe, limit=None, start=None, end=None):
                calls["fetch"] += 1
                raise AssertionError("connector should not be called on cache hit")

        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )

        result = fetch_bars_with_cache(
            connector=FakeConnector(),
            store=FakeStore(),
            source="vendor_yahoo",
            market=market,
            timeframe="1d",
            limit=1,
        )

        self.assertEqual(calls["read"], 1)
        self.assertEqual(calls["write"], 0)
        self.assertEqual(calls["fetch"], 0)
        self.assertEqual(calls["series_id"].cache_key, "vendor_yahoo/nasdaq/equity/AAPL/1d")
        self.assertEqual(len(result), 1)
        self.assertEqual(float(result.iloc[0]["Close"]), 106.0)

    def test_fetch_bars_with_cache_fetches_and_writes_store_on_cache_miss(self):
        from quant_platform import fetch_bars_with_cache
        from quant_platform.core import AssetSpec, MarketSpec

        fetched = pd.DataFrame(
            {"Open": [100.0], "High": [110.0], "Low": [90.0], "Close": [105.0], "Volume": [10.0]},
            index=pd.to_datetime(["2024-01-01T00:00:00Z"], utc=True),
        )
        calls = {"read": 0, "write": 0, "fetch": 0}

        class FakeStore:
            def read(self, series_id):
                calls["read"] += 1
                calls["series_id"] = series_id
                raise FileNotFoundError

            def write(self, series_id, bars):
                calls["write"] += 1
                calls["written_series_id"] = series_id
                calls["written_bars"] = bars

        class FakeConnector:
            def fetch_bars(self, market, timeframe, limit=None, start=None, end=None):
                calls["fetch"] += 1
                calls["fetch_args"] = (market, timeframe, limit, start, end)
                return fetched

        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )

        result = fetch_bars_with_cache(
            connector=FakeConnector(),
            store=FakeStore(),
            source="vendor_polygon",
            market=market,
            timeframe="1d",
            limit=250,
        )

        self.assertIs(result, fetched)
        self.assertEqual(calls["read"], 1)
        self.assertEqual(calls["fetch"], 1)
        self.assertEqual(calls["write"], 1)
        self.assertEqual(calls["written_series_id"].cache_key, "vendor_polygon/nasdaq/equity/AAPL/1d")
        self.assertIs(calls["written_bars"], fetched)
        self.assertEqual(calls["fetch_args"][2], 250)

    def test_fetch_bars_with_cache_refresh_bypasses_store_read(self):
        from quant_platform import fetch_bars_with_cache
        from quant_platform.core import AssetSpec, MarketSpec

        fetched = pd.DataFrame(
            {"Open": [100.0], "High": [110.0], "Low": [90.0], "Close": [105.0], "Volume": [10.0]},
            index=pd.to_datetime(["2024-01-01T00:00:00Z"], utc=True),
        )
        calls = {"read": 0, "write": 0, "fetch": 0}

        class FakeStore:
            def read(self, series_id):
                calls["read"] += 1
                raise AssertionError("read should be bypassed on refresh")

            def write(self, series_id, bars):
                calls["write"] += 1

        class FakeConnector:
            def fetch_bars(self, market, timeframe, limit=None, start=None, end=None):
                calls["fetch"] += 1
                return fetched

        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )

        result = fetch_bars_with_cache(
            connector=FakeConnector(),
            store=FakeStore(),
            source="vendor_alpha_vantage",
            market=market,
            timeframe="1d",
            refresh=True,
        )

        self.assertIs(result, fetched)
        self.assertEqual(calls["read"], 0)
        self.assertEqual(calls["fetch"], 1)
        self.assertEqual(calls["write"], 1)

    def test_fetch_derivatives_with_cache_reads_store_before_connector(self):
        from quant_platform import fetch_derivatives_with_cache
        from quant_platform.core import AssetSpec, MarketSpec

        cached = pd.DataFrame(
            {
                "funding_rate": [0.0001],
                "open_interest": [1250.0],
            },
            index=pd.to_datetime(["2024-01-01T00:00:00Z"], utc=True),
        )
        calls = {"read": 0, "write": 0, "fetch": 0}

        class FakeStore:
            def read(self, series_id):
                calls["read"] += 1
                calls["series_id"] = series_id
                return cached

            def write(self, series_id, derivatives):
                calls["write"] += 1

        class FakeConnector:
            def fetch_derivatives(
                self,
                market,
                funding_limit=1000,
                open_interest_timeframe="4h",
                open_interest_limit=1000,
            ):
                calls["fetch"] += 1
                raise AssertionError("connector should not be called on cache hit")

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )

        result = fetch_derivatives_with_cache(
            connector=FakeConnector(),
            store=FakeStore(),
            source="ccxt",
            market=market,
            open_interest_timeframe="4h",
        )

        self.assertIs(result, cached)
        self.assertEqual(calls["read"], 1)
        self.assertEqual(calls["write"], 0)
        self.assertEqual(calls["fetch"], 0)
        self.assertEqual(calls["series_id"].cache_key, "ccxt/binance/swap/BTC_USDT/4h/derivatives")

    def test_fetch_derivatives_with_cache_fetches_and_writes_store_on_cache_miss(self):
        from quant_platform import fetch_derivatives_with_cache
        from quant_platform.core import AssetSpec, MarketSpec

        fetched = pd.DataFrame(
            {"funding_rate": [0.0002], "open_interest": [1400.0]},
            index=pd.to_datetime(["2024-01-01T00:00:00Z"], utc=True),
        )
        calls = {"read": 0, "write": 0, "fetch": 0}

        class FakeStore:
            def read(self, series_id):
                calls["read"] += 1
                calls["series_id"] = series_id
                raise FileNotFoundError

            def write(self, series_id, derivatives):
                calls["write"] += 1
                calls["written_series_id"] = series_id
                calls["written_derivatives"] = derivatives

        class FakeConnector:
            def fetch_derivatives(
                self,
                market,
                funding_limit=1000,
                open_interest_timeframe="4h",
                open_interest_limit=1000,
            ):
                calls["fetch"] += 1
                calls["fetch_args"] = (market, funding_limit, open_interest_timeframe, open_interest_limit)
                return fetched

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )

        result = fetch_derivatives_with_cache(
            connector=FakeConnector(),
            store=FakeStore(),
            source="ccxt",
            market=market,
            funding_limit=250,
            open_interest_timeframe="1h",
            open_interest_limit=300,
        )

        self.assertIs(result, fetched)
        self.assertEqual(calls["read"], 1)
        self.assertEqual(calls["fetch"], 1)
        self.assertEqual(calls["write"], 1)
        self.assertEqual(calls["written_series_id"].cache_key, "ccxt/binance/swap/BTC_USDT/1h/derivatives")
        self.assertIs(calls["written_derivatives"], fetched)
        self.assertEqual(calls["fetch_args"][1:], (250, "1h", 300))

    def test_fetch_derivatives_with_cache_refresh_bypasses_store_read(self):
        from quant_platform import fetch_derivatives_with_cache
        from quant_platform.core import AssetSpec, MarketSpec

        fetched = pd.DataFrame(
            {"funding_rate": [0.0002], "open_interest": [1400.0]},
            index=pd.to_datetime(["2024-01-01T00:00:00Z"], utc=True),
        )
        calls = {"read": 0, "write": 0, "fetch": 0}

        class FakeStore:
            def read(self, series_id):
                calls["read"] += 1
                raise AssertionError("read should be bypassed on refresh")

            def write(self, series_id, derivatives):
                calls["write"] += 1

        class FakeConnector:
            def fetch_derivatives(
                self,
                market,
                funding_limit=1000,
                open_interest_timeframe="4h",
                open_interest_limit=1000,
            ):
                calls["fetch"] += 1
                return fetched

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )

        result = fetch_derivatives_with_cache(
            connector=FakeConnector(),
            store=FakeStore(),
            source="ccxt",
            market=market,
            refresh=True,
        )

        self.assertIs(result, fetched)
        self.assertEqual(calls["read"], 0)
        self.assertEqual(calls["fetch"], 1)
        self.assertEqual(calls["write"], 1)

    def test_fetch_order_book_snapshots_with_cache_reads_store_before_connector(self):
        from quant_platform import fetch_order_book_snapshots_with_cache
        from quant_platform.core import AssetSpec, MarketSpec

        cached = pd.DataFrame(
            {"bid_price_1": [100.0], "ask_price_1": [100.1]},
            index=pd.to_datetime(["2024-01-01T00:00:00Z"], utc=True),
        )
        calls = {"read": 0, "write": 0, "fetch": 0}

        class FakeStore:
            def read(self, series_id):
                calls["read"] += 1
                calls["series_id"] = series_id
                return cached

            def write(self, series_id, snapshots):
                calls["write"] += 1

        class FakeConnector:
            def fetch_order_book_snapshots(
                self,
                market,
                depth=5,
                sample_interval="1s",
                limit=1000,
                start=None,
                end=None,
            ):
                calls["fetch"] += 1
                raise AssertionError("connector should not be called on cache hit")

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )

        result = fetch_order_book_snapshots_with_cache(
            connector=FakeConnector(),
            store=FakeStore(),
            source="ccxt",
            market=market,
            depth=5,
            sample_interval="1s",
        )

        self.assertIs(result, cached)
        self.assertEqual(calls["read"], 1)
        self.assertEqual(calls["write"], 0)
        self.assertEqual(calls["fetch"], 0)
        self.assertEqual(calls["series_id"].cache_key, "ccxt/binance/swap/BTC_USDT/order_book/depth_5/1s")

    def test_fetch_order_book_snapshots_with_cache_fetches_and_writes_store_on_cache_miss(self):
        from quant_platform import fetch_order_book_snapshots_with_cache
        from quant_platform.core import AssetSpec, MarketSpec

        fetched = pd.DataFrame(
            {"bid_price_1": [100.0], "ask_price_1": [100.1]},
            index=pd.to_datetime(["2024-01-01T00:00:00Z"], utc=True),
        )
        calls = {"read": 0, "write": 0, "fetch": 0}

        class FakeStore:
            def read(self, series_id):
                calls["read"] += 1
                calls["series_id"] = series_id
                raise FileNotFoundError

            def write(self, series_id, snapshots):
                calls["write"] += 1
                calls["written_series_id"] = series_id
                calls["written_snapshots"] = snapshots

        class FakeConnector:
            def fetch_order_book_snapshots(
                self,
                market,
                depth=5,
                sample_interval="1s",
                limit=1000,
                start=None,
                end=None,
            ):
                calls["fetch"] += 1
                calls["fetch_args"] = (market, depth, sample_interval, limit, start, end)
                return fetched

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )

        result = fetch_order_book_snapshots_with_cache(
            connector=FakeConnector(),
            store=FakeStore(),
            source="ccxt",
            market=market,
            depth=10,
            sample_interval="500ms",
            limit=25,
        )

        self.assertIs(result, fetched)
        self.assertEqual(calls["read"], 1)
        self.assertEqual(calls["fetch"], 1)
        self.assertEqual(calls["write"], 1)
        self.assertEqual(calls["written_series_id"].cache_key, "ccxt/binance/swap/BTC_USDT/order_book/depth_10/500ms")
        self.assertIs(calls["written_snapshots"], fetched)
        self.assertEqual(calls["fetch_args"][1:4], (10, "500ms", 25))

    def test_fetch_order_book_snapshots_with_cache_refresh_bypasses_store_read(self):
        from quant_platform import fetch_order_book_snapshots_with_cache
        from quant_platform.core import AssetSpec, MarketSpec

        fetched = pd.DataFrame(
            {"bid_price_1": [100.0], "ask_price_1": [100.1]},
            index=pd.to_datetime(["2024-01-01T00:00:00Z"], utc=True),
        )
        calls = {"read": 0, "write": 0, "fetch": 0}

        class FakeStore:
            def read(self, series_id):
                calls["read"] += 1
                raise AssertionError("read should be bypassed on refresh")

            def write(self, series_id, snapshots):
                calls["write"] += 1

        class FakeConnector:
            def fetch_order_book_snapshots(
                self,
                market,
                depth=5,
                sample_interval="1s",
                limit=1000,
                start=None,
                end=None,
            ):
                calls["fetch"] += 1
                return fetched

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )

        result = fetch_order_book_snapshots_with_cache(
            connector=FakeConnector(),
            store=FakeStore(),
            source="ccxt",
            market=market,
            refresh=True,
        )

        self.assertIs(result, fetched)
        self.assertEqual(calls["read"], 0)
        self.assertEqual(calls["fetch"], 1)
        self.assertEqual(calls["write"], 1)


if __name__ == "__main__":
    unittest.main()

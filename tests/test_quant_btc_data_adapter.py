import unittest
from unittest.mock import patch

import pandas as pd


class QuantBtcDataAdapterTest(unittest.TestCase):
    def test_fetch_from_exchange_delegates_to_platform_ccxt_connector(self):
        from quant_btc import data

        captured = {}
        expected = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [10.0]},
            index=pd.to_datetime([1700000000000], unit="ms", utc=True),
        )

        class FakeConnector:
            def __init__(self, timeout_ms, proxy_url, max_retries):
                captured["init"] = (timeout_ms, proxy_url, max_retries)

            def fetch_bars(self, market, timeframe, limit):
                captured["market"] = market
                captured["timeframe"] = timeframe
                captured["limit"] = limit
                return expected

        with patch("quant_btc.data.CcxtExchangeConnector", FakeConnector):
            result = data._fetch_from_exchange(
                symbol="ETH/USDT",
                timeframe="1h",
                limit=123,
                market_type="spot",
                exchange_id="okx",
                timeout_ms=5000,
                max_retries=2,
                proxy_url="http://proxy",
            )

        self.assertIs(result, expected)
        self.assertEqual(captured["init"], (5000, "http://proxy", 2))
        self.assertEqual(captured["market"].market_key, "okx:spot:ETH/USDT")
        self.assertFalse(captured["market"].supports_short)
        self.assertEqual(captured["timeframe"], "1h")
        self.assertEqual(captured["limit"], 123)

    def test_connector_errors_are_mapped_to_data_fetch_error(self):
        from quant_btc import data
        from quant_platform.connectors_ccxt import ConnectorError

        class BrokenConnector:
            def __init__(self, timeout_ms, proxy_url, max_retries):
                pass

            def fetch_bars(self, market, timeframe, limit):
                raise ConnectorError("remote blocked")

        with patch("quant_btc.data.CcxtExchangeConnector", BrokenConnector):
            with self.assertRaisesRegex(data.DataFetchError, "remote blocked"):
                data._fetch_from_exchange(
                    symbol="BTC/USDT",
                    timeframe="4h",
                    limit=10,
                    market_type="swap",
                    exchange_id="binance",
                    timeout_ms=5000,
                    max_retries=1,
                    proxy_url=None,
                )

    def test_fetch_derivative_data_delegates_to_platform_connector(self):
        from quant_btc import data

        expected = pd.DataFrame(
            {"funding_rate": [0.0001], "open_interest": [1000.0]},
            index=pd.to_datetime([1700000000000], unit="ms", utc=True),
        )
        captured = {}

        class FakeConnector:
            def __init__(self, timeout_ms, proxy_url, max_retries):
                captured["init"] = (timeout_ms, proxy_url, max_retries)

            def fetch_derivatives(self, market, funding_limit=1000, open_interest_timeframe="4h", open_interest_limit=1000):
                captured["market"] = market
                captured["funding_limit"] = funding_limit
                captured["open_interest_timeframe"] = open_interest_timeframe
                captured["open_interest_limit"] = open_interest_limit
                return expected

        with patch("quant_btc.data._load_cache", return_value=None), \
             patch("quant_btc.data._save_cache") as save_cache, \
             patch("quant_btc.data.CcxtExchangeConnector", FakeConnector):
            result = data.fetch_derivative_data("BTC/USDT", exchange_id="binance", proxy_url="http://proxy", refresh=True)

        self.assertIs(result, expected)
        self.assertEqual(captured["init"], (30000, "http://proxy", 5))
        self.assertEqual(captured["market"].market_key, "binance:swap:BTC/USDT")
        save_cache.assert_called_once()

    def test_fetch_derivative_data_remote_path_uses_platform_derivative_cache_boundary(self):
        from quant_btc import data

        expected = pd.DataFrame(
            {"funding_rate": [0.0001], "open_interest": [1000.0]},
            index=pd.to_datetime([1700000000000], unit="ms", utc=True),
        )
        captured = {}

        class FakeConnector:
            def __init__(self, timeout_ms, proxy_url, max_retries):
                captured["init"] = (timeout_ms, proxy_url, max_retries)

        def fake_fetch_with_cache(**kwargs):
            captured.update(kwargs)
            return expected

        with patch("quant_btc.data._load_cache", return_value=None), \
             patch("quant_btc.data._load_derivative_store", return_value=None), \
             patch("quant_btc.data._save_cache") as save_cache, \
             patch("quant_btc.data.CcxtExchangeConnector", FakeConnector), \
             patch("quant_btc.data.fetch_derivatives_with_cache", side_effect=fake_fetch_with_cache):
            result = data.fetch_derivative_data("BTC/USDT", exchange_id="binance", proxy_url="http://proxy")

        self.assertIs(result, expected)
        self.assertIsInstance(captured["connector"], FakeConnector)
        self.assertEqual(captured["source"], "ccxt")
        self.assertEqual(captured["market"].market_key, "binance:swap:BTC/USDT")
        self.assertEqual(captured["open_interest_timeframe"], "4h")
        self.assertTrue(captured["refresh"])
        self.assertEqual(captured["init"], (30000, "http://proxy", 5))
        save_cache.assert_called_once()

    def test_fetch_derivative_data_uses_parquet_store_before_pickle_cache(self):
        from quant_btc import data

        expected = pd.DataFrame(
            {"funding_rate": [0.0001], "open_interest": [1000.0]},
            index=pd.to_datetime([1700000000000], unit="ms", utc=True),
        )
        calls = {"read": 0, "write": 0, "pickle_load": 0}

        class FakeStore:
            def __init__(self, root):
                calls["root"] = root

            def read(self, series_id):
                calls["read"] += 1
                calls["series_id"] = series_id
                return expected

            def write(self, series_id, derivatives):
                calls["write"] += 1

        with patch("quant_btc.data.ParquetDerivativeStore", FakeStore), \
             patch("quant_btc.data._load_cache", side_effect=lambda path: calls.__setitem__("pickle_load", calls["pickle_load"] + 1)), \
             patch("quant_btc.data.CcxtExchangeConnector", side_effect=AssertionError("remote fetch should not run")):
            result = data.fetch_derivative_data("BTC/USDT", exchange_id="binance")

        self.assertIs(result, expected)
        self.assertEqual(calls["read"], 1)
        self.assertEqual(calls["write"], 0)
        self.assertEqual(calls["pickle_load"], 0)
        self.assertEqual(calls["series_id"].cache_key, "ccxt/binance/swap/BTC_USDT/4h/derivatives")

    def test_fetch_ohlcv_uses_parquet_store_before_pickle_cache(self):
        from quant_btc import data

        expected = pd.DataFrame(
            {"Open": [10.0], "High": [11.0], "Low": [9.0], "Close": [10.5], "Volume": [100.0]},
            index=pd.to_datetime([1700000000000], unit="ms", utc=True),
        )
        calls = {"read": 0, "write": 0, "pickle_load": 0}

        class FakeStore:
            def __init__(self, root):
                calls["root"] = root

            def read(self, series_id):
                calls["read"] += 1
                calls["series_id"] = series_id
                return expected

            def write(self, series_id, bars):
                calls["write"] += 1

        with patch("quant_btc.data.ParquetBarStore", FakeStore), \
             patch("quant_btc.data._load_cache", side_effect=lambda path: calls.__setitem__("pickle_load", calls["pickle_load"] + 1)), \
             patch("quant_btc.data._fetch_from_exchange", side_effect=AssertionError("remote fetch should not run")):
            result = data.fetch_ohlcv(symbol="BTC/USDT", timeframe="4h", market_type="swap", exchange_id="binance")

        self.assertIs(result, expected)
        self.assertEqual(calls["read"], 1)
        self.assertEqual(calls["write"], 0)
        self.assertEqual(calls["pickle_load"], 0)
        self.assertEqual(calls["series_id"].cache_key, "ccxt/binance/swap/BTC_USDT/4h")

    def test_fetch_ohlcv_writes_parquet_store_and_pickle_after_remote_fetch(self):
        from quant_btc import data

        fetched = pd.DataFrame(
            {"Open": [10.0], "High": [11.0], "Low": [9.0], "Close": [10.5], "Volume": [100.0]},
            index=pd.to_datetime([1700000000000], unit="ms", utc=True),
        )
        calls = {"read": 0, "write": 0}

        class FakeStore:
            def __init__(self, root):
                calls["root"] = root

            def read(self, series_id):
                calls["read"] += 1
                raise FileNotFoundError

            def write(self, series_id, bars):
                calls["write"] += 1
                calls["series_id"] = series_id
                calls["bars"] = bars

        with patch("quant_btc.data.ParquetBarStore", FakeStore), \
             patch("quant_btc.data._load_cache", return_value=None) as load_cache, \
             patch("quant_btc.data._save_cache") as save_cache, \
             patch("quant_btc.data._fetch_from_exchange", return_value=fetched) as fetch_remote:
            result = data.fetch_ohlcv(symbol="BTC/USDT", timeframe="4h", market_type="swap", exchange_id="binance")

        self.assertIs(result, fetched)
        self.assertEqual(calls["read"], 1)
        self.assertEqual(calls["write"], 1)
        self.assertIs(calls["bars"], fetched)
        self.assertEqual(calls["series_id"].cache_key, "ccxt/binance/swap/BTC_USDT/4h")
        load_cache.assert_called_once()
        save_cache.assert_called_once()
        fetch_remote.assert_called_once()


if __name__ == "__main__":
    unittest.main()

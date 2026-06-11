import unittest
from unittest.mock import patch

import pandas as pd


class ServeDataLoaderTest(unittest.TestCase):
    def setUp(self):
        from serve import data_loader

        data_loader._cache.clear()

    def test_get_ohlcv_reads_parquet_bar_store_before_pickle(self):
        from serve import data_loader

        expected = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "Close": [100.5],
                "Volume": [10.0],
            },
            index=pd.to_datetime(["2026-06-01T00:00:00Z"]),
        )
        calls = {"read": 0, "pickle": 0}

        class FakeStore:
            def __init__(self, root):
                calls["root"] = root

            def read(self, series_id):
                calls["read"] += 1
                calls["series_id"] = series_id
                return expected

        def load_pickle(name):
            calls["pickle"] += 1
            raise AssertionError("pickle fallback should not be read")

        with patch("serve.data_loader.ParquetBarStore", FakeStore), \
             patch("serve.data_loader._load_pickle", load_pickle):
            result = data_loader.get_ohlcv("4h")

        self.assertIs(result, expected)
        self.assertEqual(calls["read"], 1)
        self.assertEqual(calls["pickle"], 0)
        self.assertEqual(calls["series_id"].cache_key, "ccxt/binance/swap/BTC_USDT/4h")

    def test_get_ohlcv_falls_back_to_pickle_when_bar_store_is_missing(self):
        from serve import data_loader

        fallback = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "Close": [100.5],
                "Volume": [10.0],
            },
            index=pd.to_datetime(["2026-06-01T00:00:00Z"]),
        )
        calls = {"read": 0, "pickle": 0}

        class MissingStore:
            def __init__(self, root):
                calls["root"] = root

            def read(self, series_id):
                calls["read"] += 1
                calls["series_id"] = series_id
                raise FileNotFoundError

        def load_pickle(name):
            calls["pickle"] += 1
            calls["pickle_name"] = name
            return fallback

        with patch("serve.data_loader.ParquetBarStore", MissingStore), \
             patch("serve.data_loader._load_pickle", load_pickle):
            result = data_loader.get_ohlcv("15m")

        self.assertIs(result, fallback)
        self.assertEqual(calls["read"], 1)
        self.assertEqual(calls["pickle"], 1)
        self.assertEqual(calls["pickle_name"], "binance_swap_BTC_USDT_15m.pkl")
        self.assertEqual(calls["series_id"].cache_key, "ccxt/binance/swap/BTC_USDT/15m")


if __name__ == "__main__":
    unittest.main()

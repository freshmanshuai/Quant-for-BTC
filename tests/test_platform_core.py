import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class PlatformCoreTest(unittest.TestCase):
    def test_market_spec_describes_tradeable_asset_constraints(self):
        from quant_platform.core import AssetSpec, MarketSpec

        asset = AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT")
        market = MarketSpec(
            asset=asset,
            exchange="binance",
            market_type="swap",
            tick_size=0.01,
            lot_size=0.001,
            fee_rate=0.0004,
            contract_multiplier=1.0,
            supports_short=True,
            supports_leverage=True,
            trading_session="24/7",
        )

        self.assertEqual(market.asset.symbol, "BTC/USDT")
        self.assertTrue(market.supports_short)
        self.assertEqual(market.market_key, "binance:swap:BTC/USDT")

    def test_market_spec_quantizes_price_and_quantity_to_exchange_steps(self):
        from quant_platform.core import AssetSpec, MarketSpec

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
            tick_size=0.01,
            lot_size=0.001,
        )
        unconstrained = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )

        self.assertEqual(market.quantize_price(67234.567), 67234.56)
        self.assertEqual(market.quantize_quantity(0.123456), 0.123)
        self.assertEqual(unconstrained.quantize_price(123.4567), 123.4567)
        self.assertEqual(unconstrained.quantize_quantity(10.25), 10.25)

    def test_market_catalog_registers_and_resolves_market_specs(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.markets import MarketCatalog

        btc_swap = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
            tick_size=0.1,
            lot_size=0.001,
            supports_short=True,
            supports_leverage=True,
        )
        btc_spot = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="spot",
            tick_size=0.01,
            lot_size=0.00001,
        )
        catalog = MarketCatalog().register(btc_swap).register(btc_spot)

        self.assertIs(catalog.resolve("BTC/USDT", exchange="binance", market_type="swap"), btc_swap)
        self.assertIs(catalog.resolve("BTC/USDT", exchange="binance", market_type="spot"), btc_spot)
        self.assertEqual(catalog.by_symbol(), {"BTC/USDT": btc_swap})
        with self.assertRaisesRegex(KeyError, "No market spec registered"):
            catalog.resolve("ETH/USDT", exchange="binance", market_type="swap")

    def test_default_crypto_market_catalog_exposes_btc_swap_spec(self):
        from quant_platform.markets import default_crypto_market_catalog

        catalog = default_crypto_market_catalog()
        market = catalog.resolve("BTC/USDT", exchange="binance", market_type="swap")

        self.assertEqual(market.asset.base, "BTC")
        self.assertEqual(market.asset.quote, "USDT")
        self.assertEqual(market.tick_size, 0.1)
        self.assertEqual(market.lot_size, 0.001)
        self.assertTrue(market.supports_short)
        self.assertTrue(market.supports_leverage)

    def test_market_catalog_builds_from_config_records_and_exports_records(self):
        from quant_platform.markets import MarketCatalog

        records = [
            {
                "symbol": "BTC/USDT",
                "base": "BTC",
                "quote": "USDT",
                "exchange": "binance",
                "market_type": "swap",
                "tick_size": 0.1,
                "lot_size": 0.001,
                "fee_rate": 0.0004,
                "contract_multiplier": 1.0,
                "trading_session": "24/7",
                "supports_short": True,
                "supports_leverage": True,
            },
            {
                "symbol": "AAPL",
                "base": "AAPL",
                "quote": "USD",
                "exchange": "nasdaq",
                "market_type": "equity",
                "tick_size": 0.01,
                "lot_size": 0.001,
                "trading_session": "US_REGULAR",
                "supports_short": False,
                "supports_leverage": False,
            },
        ]

        catalog = MarketCatalog.from_records(records)
        btc = catalog.resolve("BTC/USDT", exchange="binance", market_type="swap")
        aapl = catalog.resolve("AAPL", exchange="nasdaq", market_type="equity")

        self.assertEqual(btc.fee_rate, 0.0004)
        self.assertEqual(aapl.trading_session, "US_REGULAR")
        self.assertFalse(aapl.supports_short)
        self.assertEqual(catalog.to_records(), records)

    def test_market_catalog_loads_and_saves_json_config(self):
        import json

        from quant_platform.markets import load_market_catalog_json, save_market_catalog_json

        records = [
            {
                "symbol": "ETH/USDT",
                "base": "ETH",
                "quote": "USDT",
                "exchange": "okx",
                "market_type": "swap",
                "tick_size": 0.01,
                "lot_size": 0.001,
                "fee_rate": 0.0005,
                "supports_short": True,
                "supports_leverage": True,
            }
        ]
        with TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "markets.json"
            target = Path(tmpdir) / "markets.out.json"
            source.write_text(json.dumps({"markets": records}), encoding="utf-8")

            catalog = load_market_catalog_json(source)
            market = catalog.resolve("ETH/USDT", exchange="okx", market_type="swap")
            saved = save_market_catalog_json(catalog, target)

            self.assertEqual(market.fee_rate, 0.0005)
            self.assertEqual(saved, target)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"markets": catalog.to_records()})

    def test_standard_bar_schema_uses_asset_timeframe_and_source(self):
        from quant_platform.data import BarSeriesId

        series_id = BarSeriesId(
            symbol="BTC/USDT",
            exchange="binance",
            market_type="swap",
            timeframe="4h",
            source="ccxt",
        )

        self.assertEqual(series_id.cache_key, "ccxt/binance/swap/BTC_USDT/4h")

    def test_signal_module_output_is_standardized(self):
        from quant_platform.signals import Direction, Signal

        signal = Signal(
            module="breakout",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=78.5,
            entry_reason="Donchian breakout",
            invalidation="Close back below breakout level",
            preferred_stop=65000,
            preferred_target=72000,
            confidence=0.72,
            required_data=("ohlcv:4h", "features:trend"),
        )

        payload = signal.to_dict()

        self.assertEqual(payload["direction"], "long")
        self.assertEqual(payload["module"], "breakout")
        self.assertEqual(payload["required_data"], ["ohlcv:4h", "features:trend"])

    def test_connector_contract_fetches_bars_by_market_spec(self):
        from quant_platform.connectors import DataConnector
        from quant_platform.core import AssetSpec, MarketSpec

        class MemoryConnector(DataConnector):
            name = "memory"

            def fetch_bars(self, market, timeframe, limit=None, start=None, end=None):
                return {
                    "market": market.market_key,
                    "timeframe": timeframe,
                    "limit": limit,
                    "start": start,
                    "end": end,
                }

        market = MarketSpec(
            asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
            exchange="okx",
            market_type="spot",
        )

        result = MemoryConnector().fetch_bars(market, "1h", limit=100)

        self.assertEqual(result["market"], "okx:spot:ETH/USDT")
        self.assertEqual(result["timeframe"], "1h")
        self.assertEqual(result["limit"], 100)

    def test_connector_registry_routes_bar_fetches_by_source(self):
        from quant_platform.connectors import DataConnector, DataConnectorRegistry
        from quant_platform.core import AssetSpec, MarketSpec

        class MemoryConnector(DataConnector):
            name = "memory"

            def fetch_bars(self, market, timeframe, limit=None, start=None, end=None):
                return {
                    "source": self.name,
                    "market": market.market_key,
                    "timeframe": timeframe,
                    "limit": limit,
                }

        market = MarketSpec(
            asset=AssetSpec(symbol="SOL/USDT", base="SOL", quote="USDT"),
            exchange="local",
            market_type="spot",
        )
        registry = DataConnectorRegistry().register(MemoryConnector())

        result = registry.fetch_bars("memory", market, "1h", limit=25)

        self.assertEqual(result["source"], "memory")
        self.assertEqual(result["market"], "local:spot:SOL/USDT")
        self.assertEqual(result["timeframe"], "1h")
        self.assertEqual(result["limit"], 25)

        with self.assertRaisesRegex(KeyError, "No data connector registered for source 'missing'"):
            registry.fetch_bars("missing", market, "1h")

    def test_connector_registry_routes_derivative_fetches_by_source(self):
        import pandas as pd

        from quant_platform.connectors import DataConnector, DataConnectorRegistry
        from quant_platform.core import AssetSpec, MarketSpec

        class DerivativeConnector(DataConnector):
            name = "derivatives"

            def fetch_bars(self, market, timeframe, limit=None, start=None, end=None):
                return pd.DataFrame()

            def fetch_derivatives(
                self,
                market,
                funding_limit=1000,
                open_interest_timeframe="4h",
                open_interest_limit=1000,
            ):
                return pd.DataFrame(
                    {
                        "market": [market.market_key],
                        "funding_limit": [funding_limit],
                        "open_interest_timeframe": [open_interest_timeframe],
                        "open_interest_limit": [open_interest_limit],
                    }
                )

        class BarsOnlyConnector(DataConnector):
            name = "bars"

            def fetch_bars(self, market, timeframe, limit=None, start=None, end=None):
                return pd.DataFrame()

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )
        registry = DataConnectorRegistry([DerivativeConnector(), BarsOnlyConnector()])

        df = registry.fetch_derivatives(
            "derivatives",
            market,
            funding_limit=12,
            open_interest_timeframe="1h",
            open_interest_limit=34,
        )

        self.assertEqual(df.iloc[0]["market"], "binance:swap:BTC/USDT")
        self.assertEqual(int(df.iloc[0]["funding_limit"]), 12)
        self.assertEqual(df.iloc[0]["open_interest_timeframe"], "1h")
        self.assertEqual(int(df.iloc[0]["open_interest_limit"]), 34)

        with self.assertRaisesRegex(NotImplementedError, "does not support derivative data"):
            registry.fetch_derivatives("bars", market)


if __name__ == "__main__":
    unittest.main()

import unittest

import pandas as pd

from quant_platform.data import DataQualityError, clean_ohlcv_bars
from quant_platform.features import htf_ema
from quant_platform.regimes import step_series_direction
from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
from quant_platform.core import AssetSpec, MarketSpec
from quant_platform.pipeline import SignalPipeline
from quant_platform.portfolio import PortfolioEngine
from quant_platform.risk import AccountState, RiskEngine, RiskLimits
from quant_platform.signal_modules import SignalModuleRunner
from quant_platform.signals import Direction, Signal


class FirstBarLongSignal:
    def generate(self, features, symbol):
        if len(features) != 1:
            return []
        close = float(features["Close"].iloc[-1])
        return [
            Signal(
                module="core_long",
                symbol=symbol,
                direction=Direction.LONG,
                score=80.0,
                entry_reason="test",
                invalidation="stop",
                preferred_stop=close * 0.9,
                preferred_target=None,
                confidence=0.8,
            )
        ]


class CausalGuardTest(unittest.TestCase):
    @staticmethod
    def _backtest(execution):
        symbol = "BTC/USDT"
        market = MarketSpec(
            asset=AssetSpec(symbol=symbol, base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
            fee_rate=0.0005,
            supports_short=True,
            supports_leverage=True,
            maintenance_margin_rate=0.004,
            liquidation_fee_rate=0.0125,
        )
        markets = {symbol: market}
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([FirstBarLongSignal()]),
            risk_engine=RiskEngine(
                RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0, max_leverage=5.0),
                markets_by_symbol=markets,
            ),
            portfolio_engine=PortfolioEngine(
                markets_by_symbol=markets,
                precreate_positions=False,
            ),
            markets_by_symbol=markets,
        )
        return EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=execution,
            markets_by_symbol=markets,
        )

    def test_htf_ema_is_prefix_invariant(self):
        index = pd.date_range("2025-01-01", periods=60, freq="4h", tz="UTC")
        close = pd.Series(range(100, 160), index=index, dtype=float)
        prefix = htf_ema(close.iloc[:42], "1D", 3)

        mutated = close.copy()
        mutated.iloc[42:] = 1_000_000.0
        full = htf_ema(mutated, "1D", 3)

        pd.testing.assert_series_equal(prefix, full.iloc[:42])

    def test_htf_ema_does_not_expose_period_final_close_inside_period(self):
        index = pd.date_range("2025-01-01", periods=12, freq="4h", tz="UTC")
        close = pd.Series([100.0] * 6 + [200.0] * 6, index=index)
        value = htf_ema(close, "1D", 1)

        self.assertTrue(value.iloc[:6].isna().all())
        self.assertTrue((value.iloc[6:] == 100.0).all())

    def test_step_direction_persists_between_htf_updates(self):
        index = pd.date_range("2025-01-01", periods=8, freq="4h", tz="UTC")
        values = pd.Series([100, 100, 100, 102, 102, 102, 101, 101], index=index)

        direction = step_series_direction(values, threshold=0.001)

        self.assertEqual(direction.tolist(), [0, 0, 0, 1, 1, 1, -1, -1])

    def test_ohlcv_guard_deduplicates_and_excludes_forming_bar(self):
        index = pd.DatetimeIndex([
            "2025-01-01 00:00Z",
            "2025-01-01 00:00Z",
            "2025-01-01 04:00Z",
        ])
        bars = pd.DataFrame(
            {
                "Open": [100, 101, 102],
                "High": [105, 106, 107],
                "Low": [95, 96, 97],
                "Close": [102, 103, 104],
                "Volume": [1, 2, 3],
            },
            index=index,
        )

        clean = clean_ohlcv_bars(
            bars,
            "4h",
            as_of=pd.Timestamp("2025-01-01 06:00Z"),
        )

        self.assertEqual(len(clean), 1)
        self.assertEqual(clean.iloc[0]["Open"], 101)

    def test_ohlcv_guard_fails_closed_on_gap_when_requested(self):
        index = pd.DatetimeIndex(["2025-01-01 00:00Z", "2025-01-01 08:00Z"])
        bars = pd.DataFrame(
            {
                "Open": [100, 101],
                "High": [105, 106],
                "Low": [95, 96],
                "Close": [102, 103],
                "Volume": [1, 2],
            },
            index=index,
        )
        with self.assertRaises(DataQualityError):
            clean_ohlcv_bars(
                bars,
                "4h",
                as_of=pd.Timestamp("2025-01-02 00:00Z"),
                require_contiguous=True,
            )

    def test_causal_execution_fills_signal_at_next_bar_open(self):
        index = pd.date_range("2025-01-01", periods=3, freq="4h", tz="UTC")
        bars = pd.DataFrame(
            {
                "Open": [100.0, 110.0, 111.0],
                "High": [101.0, 112.0, 113.0],
                "Low": [99.0, 109.0, 110.0],
                "Close": [100.0, 111.0, 112.0],
                "Volume": [1000.0, 1000.0, 1000.0],
            },
            index=index,
        )
        result = self._backtest(
            BacktestExecutionConfig(fill_price_column="Open", min_order_age_bars=1)
        ).run({"BTC/USDT": bars})

        opens = [order for order in result.filled_orders if order.reason == "opened"]
        self.assertEqual(len(opens), 1)
        self.assertAlmostEqual(opens[0].average_fill_price, 110.0)

    def test_historical_funding_is_directional_and_not_forward_filled(self):
        index = pd.date_range("2025-01-01", periods=3, freq="4h", tz="UTC")
        bars = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 100.0],
                "High": [101.0, 101.0, 101.0],
                "Low": [99.0, 99.0, 99.0],
                "Close": [100.0, 100.0, 100.0],
                "Volume": [1000.0, 1000.0, 1000.0],
                "funding_rate": [float("nan"), 0.001, float("nan")],
            },
            index=index,
        )
        result = self._backtest(
            BacktestExecutionConfig(funding_rate_feature="funding_rate")
        ).run({"BTC/USDT": bars})

        self.assertAlmostEqual(result.funding_paid, 1.0)

    def test_maintenance_margin_breach_records_liquidation_and_clearance_fee(self):
        index = pd.date_range("2025-01-01", periods=2, freq="4h", tz="UTC")
        bars = pd.DataFrame(
            {
                "Open": [100.0, 100.0],
                "High": [101.0, 101.0],
                "Low": [99.0, 70.0],
                "Close": [100.0, 75.0],
                "Volume": [1000.0, 1000.0],
            },
            index=index,
        )
        result = self._backtest(
            BacktestExecutionConfig(
                leverage=5.0,
                intrabar_stop_target=True,
            )
        ).run({"BTC/USDT": bars})

        self.assertEqual(result.liquidation_count, 1)
        self.assertGreater(result.liquidation_fees_paid, 0.0)
        self.assertEqual(result.trades[0].exit_reason, "liquidation")


if __name__ == "__main__":
    unittest.main()

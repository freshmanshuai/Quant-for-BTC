"""End-to-end orchestration from standardized signals to delivery."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from quant_platform.core import MarketSpec
from quant_platform.delivery import DeliveryPayload, DeliveryResult
from quant_platform.portfolio import OrderAction, PortfolioEngine, PortfolioPlan
from quant_platform.risk import AccountState, RiskDecision, RiskEngine
from quant_platform.signal_modules import SignalModuleRunner
from quant_platform.signals import Signal


@dataclass(frozen=True)
class PipelineResult:
    signals: list[Signal]
    risk_decisions: list[RiskDecision]
    portfolio_plan: PortfolioPlan
    delivery_results: list[DeliveryResult]


class SignalPipeline:
    """Wire SignalModule output through risk, portfolio, and delivery layers."""

    def __init__(
        self,
        *,
        signal_runner: SignalModuleRunner,
        risk_engine: RiskEngine,
        portfolio_engine: PortfolioEngine,
        delivery_channels: Sequence[Any] = (),
        markets_by_symbol: dict[str, MarketSpec] | None = None,
    ):
        self.signal_runner = signal_runner
        self.risk_engine = risk_engine
        self.portfolio_engine = portfolio_engine
        self.delivery_channels = list(delivery_channels)
        if markets_by_symbol is not None:
            self.risk_engine.markets_by_symbol = dict(markets_by_symbol)
            self.portfolio_engine.markets_by_symbol = dict(markets_by_symbol)

    def run(
        self,
        features: pd.DataFrame,
        *,
        symbol: str,
        account: AccountState,
        entry_price: float | None = None,
        entry_prices: dict[str, float] | None = None,
        bar_index: int = 0,
    ) -> PipelineResult:
        signals = self.signal_runner.generate(features, symbol=symbol)
        risk_decisions: list[RiskDecision] = []
        open_risk = self.portfolio_engine.state.open_risk()
        open_symbol_risk = self.portfolio_engine.state.open_symbol_risk()
        open_module_risk = self.portfolio_engine.state.open_module_risk()
        open_group_risk = self.portfolio_engine.state.open_group_risk(self.risk_engine.limits.correlation_groups)

        for signal in signals:
            price = self._entry_price(features, signal.symbol, entry_price=entry_price, entry_prices=entry_prices)
            decision = self.risk_engine.evaluate(
                signal,
                account,
                entry_price=price,
                bar_index=bar_index,
                open_risk=open_risk,
                open_symbol_risk=open_symbol_risk,
                open_module_risk=open_module_risk,
                open_group_risk=open_group_risk,
            )
            risk_decisions.append(decision)
            if decision.allowed:
                open_risk += decision.risk_amount
                open_symbol_risk[signal.symbol] = open_symbol_risk.get(signal.symbol, 0.0) + decision.risk_amount
                open_module_risk[signal.module] = open_module_risk.get(signal.module, 0.0) + decision.risk_amount
                group = self.risk_engine.limits.correlation_groups.get(signal.symbol)
                if group:
                    open_group_risk[group] = open_group_risk.get(group, 0.0) + decision.risk_amount

        portfolio_plan = self.portfolio_engine.apply(risk_decisions)
        delivery_results: list[DeliveryResult] = []
        for order in portfolio_plan.orders:
            if order.action == OrderAction.IGNORE:
                continue
            for channel in self.delivery_channels:
                channel_name = getattr(channel, "channel", channel.__class__.__name__)
                payload = DeliveryPayload.from_order(order, channel=channel_name)
                delivery_results.append(channel.publish(payload))

        return PipelineResult(
            signals=signals,
            risk_decisions=risk_decisions,
            portfolio_plan=portfolio_plan,
            delivery_results=delivery_results,
        )

    @staticmethod
    def _entry_price(
        features: pd.DataFrame,
        symbol: str,
        *,
        entry_price: float | None,
        entry_prices: dict[str, float] | None,
    ) -> float:
        if entry_prices and symbol in entry_prices:
            return float(entry_prices[symbol])
        if entry_price is not None:
            return float(entry_price)
        if "Close" not in features.columns or features.empty:
            raise ValueError("entry_price is required when features do not contain Close")
        return float(features["Close"].iloc[-1])

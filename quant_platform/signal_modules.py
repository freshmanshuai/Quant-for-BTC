"""Reusable signal modules that convert features into standard Signal objects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from quant_platform.signals import Direction, Signal


class SignalModule(Protocol):
    """A strategy module that emits standardized signals from feature data."""

    name: str

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        """Return all signals emitted by this module for the supplied features."""


@dataclass(frozen=True)
class ColumnSignalConfig:
    """Map legacy boolean feature columns into standard Signal objects."""

    module: str
    long_column: str | None = None
    short_column: str | None = None
    long_score_column: str | None = None
    short_score_column: str | None = None
    long_stop_column: str | None = None
    short_stop_column: str | None = None
    long_target_column: str | None = None
    short_target_column: str | None = None
    entry_reason: str = ""
    invalidation: str = ""
    required_data: tuple[str, ...] = ()
    confidence_scale: float = 100.0


class ColumnSignalModule:
    """Emit signals from precomputed long/short boolean columns."""

    def __init__(self, config: ColumnSignalConfig):
        self.config = config
        self.name = config.module

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        signals: list[Signal] = []
        for _, row in features.iterrows():
            if self.config.long_column and bool(row.get(self.config.long_column, False)):
                signals.append(self._signal(
                    row,
                    symbol,
                    Direction.LONG,
                    self.config.long_score_column,
                    self.config.long_stop_column,
                    self.config.long_target_column,
                ))
            if self.config.short_column and bool(row.get(self.config.short_column, False)):
                signals.append(self._signal(
                    row,
                    symbol,
                    Direction.SHORT,
                    self.config.short_score_column,
                    self.config.short_stop_column,
                    self.config.short_target_column,
                ))
        return signals

    def _signal(
        self,
        row: pd.Series,
        symbol: str,
        direction: Direction,
        score_column: str | None,
        stop_column: str | None,
        target_column: str | None,
    ) -> Signal:
        score = float(row.get(score_column, 0.0)) if score_column else 0.0
        confidence = max(0.0, min(1.0, score / self.config.confidence_scale))
        return Signal(
            module=self.config.module,
            symbol=symbol,
            direction=direction,
            score=score,
            entry_reason=self.config.entry_reason,
            invalidation=self.config.invalidation,
            preferred_stop=_optional_float(row, stop_column),
            preferred_target=_optional_float(row, target_column),
            confidence=confidence,
            required_data=self.config.required_data,
        )


class SignalModuleRunner:
    """Run signal modules in deterministic priority order."""

    def __init__(self, modules: Sequence[SignalModule]):
        self.modules = list(modules)

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        signals: list[Signal] = []
        for module in self.modules:
            signals.extend(module.generate(features, symbol))
        return signals


def _optional_float(row: pd.Series, column: str | None) -> float | None:
    if not column:
        return None
    value = row.get(column)
    if pd.isna(value):
        return None
    return float(value)

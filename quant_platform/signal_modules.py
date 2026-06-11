"""Reusable signal modules that convert features into standard Signal objects."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from quant_platform.features import ema
from quant_platform.signals import Direction, Signal


class SignalModule(Protocol):
    """A strategy module that emits standardized signals from feature data."""

    name: str

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        """Return all signals emitted by this module for the supplied features."""


class SignalModuleRegistry:
    """Build signal modules from configuration records."""

    def __init__(self):
        self._factories: dict[str, Callable[[dict[str, object]], SignalModule]] = {}

    def register(
        self,
        module_type: str,
        factory: Callable[[dict[str, object]], SignalModule],
    ) -> "SignalModuleRegistry":
        self._factories[module_type] = factory
        return self

    def create(self, record: Mapping[str, object]) -> SignalModule:
        module_type = record.get("type")
        if not isinstance(module_type, str) or not module_type:
            raise ValueError("signal module record requires a non-empty type")
        if module_type not in self._factories:
            raise ValueError(f"unknown signal module type: {module_type}")
        raw_params = record.get("params", {})
        if raw_params is None:
            params: dict[str, object] = {}
        elif isinstance(raw_params, Mapping):
            params = dict(raw_params)
        else:
            raise ValueError("signal module params must be a mapping")
        return self._factories[module_type](params)

    def build_runner(self, records: Sequence[Mapping[str, object]]) -> "SignalModuleRunner":
        return SignalModuleRunner([self.create(record) for record in records])


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


@dataclass(frozen=True)
class BreakoutSignalConfig:
    """Direct-compute Donchian breakout signal settings."""

    module: str = "breakout"
    lookback: int = 20
    timeframe: str = ""
    risk_reward: float = 2.0
    score_floor: float = 70.0
    score_breakout_scale: float = 1000.0
    allow_long: bool = True
    allow_short: bool = True


@dataclass(frozen=True)
class PullbackSignalConfig:
    """Direct-compute EMA pullback continuation signal settings."""

    module: str = "pullback"
    ema_length: int = 20
    timeframe: str = ""
    pullback_tolerance_pct: float = 0.01
    stop_lookback: int = 2
    risk_reward: float = 2.0
    score_floor: float = 68.0
    score_resume_scale: float = 200.0
    allow_long: bool = True
    allow_short: bool = True


@dataclass(frozen=True)
class MeanReversionSignalConfig:
    """Direct-compute rolling-band mean-reversion signal settings."""

    module: str = "meanrev"
    lookback: int = 20
    std_mult: float = 2.0
    timeframe: str = ""
    stop_lookback: int = 2
    score_floor: float = 65.0
    score_deviation_scale: float = 300.0
    allow_long: bool = True
    allow_short: bool = True


@dataclass(frozen=True)
class SweepReversalSignalConfig:
    """Direct-compute liquidity sweep reversal signal settings."""

    module: str = "sweep_reversal"
    lookback: int = 20
    timeframe: str = ""
    score_floor: float = 66.0
    score_sweep_scale: float = 1000.0
    allow_long: bool = True
    allow_short: bool = True


@dataclass(frozen=True)
class CrashShortSignalConfig:
    """Direct-compute crash impulse short signal settings."""

    module: str = "crash_short"
    lookback: int = 20
    timeframe: str = ""
    min_drop_pct: float = 0.05
    volume_multiplier: float = 2.0
    stop_lookback: int = 1
    risk_reward: float = 2.0
    score_floor: float = 72.0
    score_drop_scale: float = 300.0
    score_volume_scale: float = 10.0


@dataclass(frozen=True)
class FailedBounceSignalConfig:
    """Direct-compute failed bounce short signal settings."""

    module: str = "failed_bounce"
    lookback: int = 20
    timeframe: str = ""
    resistance_tolerance_pct: float = 0.01
    min_upper_wick_pct: float = 0.30
    score_floor: float = 69.0
    score_rejection_scale: float = 300.0
    score_wick_scale: float = 10.0


@dataclass(frozen=True)
class BullTrapSignalConfig:
    """Direct-compute bull trap short signal settings."""

    module: str = "bull_trap"
    lookback: int = 20
    timeframe: str = ""
    volume_multiplier: float = 1.5
    weak_close_threshold: float = 0.50
    score_floor: float = 70.0
    score_breakout_scale: float = 300.0
    score_rejection_scale: float = 300.0
    score_volume_scale: float = 10.0


class BreakoutSignalModule:
    """Emit a current-bar breakout signal directly from OHLCV data."""

    def __init__(self, config: BreakoutSignalConfig | None = None):
        self.config = config or BreakoutSignalConfig()
        self.name = self.config.module

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        cfg = self.config
        if features.empty or len(features) <= cfg.lookback:
            return []
        _require_columns(features, ("High", "Low", "Close"), "BreakoutSignalModule")

        previous = features.iloc[:-1].tail(cfg.lookback)
        current = features.iloc[-1]
        close = float(current["Close"])
        channel_high = float(previous["High"].max())
        channel_low = float(previous["Low"].min())
        signals: list[Signal] = []

        if cfg.allow_long and close > channel_high:
            signals.append(self._signal(
                symbol=symbol,
                direction=Direction.LONG,
                close=close,
                boundary=channel_high,
                stop=channel_low,
            ))
        if cfg.allow_short and close < channel_low:
            signals.append(self._signal(
                symbol=symbol,
                direction=Direction.SHORT,
                close=close,
                boundary=channel_low,
                stop=channel_high,
            ))
        return signals

    def _signal(
        self,
        *,
        symbol: str,
        direction: Direction,
        close: float,
        boundary: float,
        stop: float,
    ) -> Signal:
        cfg = self.config
        risk_per_unit = abs(close - stop)
        if risk_per_unit <= 0:
            target = None
        elif direction == Direction.LONG:
            target = close + cfg.risk_reward * risk_per_unit
        else:
            target = close - cfg.risk_reward * risk_per_unit
        score = _breakout_score(close, boundary, cfg)
        return Signal(
            module=cfg.module,
            symbol=symbol,
            direction=direction,
            score=score,
            entry_reason=f"{cfg.lookback}-bar Donchian breakout",
            invalidation=f"Close back inside {cfg.lookback}-bar channel",
            preferred_stop=stop,
            preferred_target=target,
            confidence=max(0.0, min(1.0, score / 100.0)),
            required_data=_required_ohlcv(cfg.timeframe),
        )


class PullbackSignalModule:
    """Emit a current-bar EMA pullback continuation signal from OHLCV data."""

    def __init__(self, config: PullbackSignalConfig | None = None):
        self.config = config or PullbackSignalConfig()
        self.name = self.config.module

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        cfg = self.config
        if features.empty or len(features) < 3:
            return []
        _require_columns(features, ("High", "Low", "Close"), "PullbackSignalModule")

        ema_values = ema(features["Close"].astype(float), cfg.ema_length)
        previous = features.iloc[-2]
        current = features.iloc[-1]
        previous_ema = float(ema_values.iloc[-2])
        current_ema = float(ema_values.iloc[-1])
        previous_close = float(previous["Close"])
        current_close = float(current["Close"])
        signals: list[Signal] = []

        if cfg.allow_long and self._is_long_pullback(previous, current_close, previous_close, previous_ema, current_ema):
            stop = float(features["Low"].tail(cfg.stop_lookback + 1).min())
            signals.append(self._signal(
                symbol=symbol,
                direction=Direction.LONG,
                close=current_close,
                previous_close=previous_close,
                stop=stop,
            ))
        if cfg.allow_short and self._is_short_pullback(previous, current_close, previous_close, previous_ema, current_ema):
            stop = float(features["High"].tail(cfg.stop_lookback + 1).max())
            signals.append(self._signal(
                symbol=symbol,
                direction=Direction.SHORT,
                close=current_close,
                previous_close=previous_close,
                stop=stop,
            ))
        return signals

    def _is_long_pullback(
        self,
        previous: pd.Series,
        current_close: float,
        previous_close: float,
        previous_ema: float,
        current_ema: float,
    ) -> bool:
        tolerance = self.config.pullback_tolerance_pct
        touched_ema = float(previous["Low"]) <= previous_ema * (1.0 + tolerance)
        closed_near_ema = previous_close <= previous_ema * (1.0 + tolerance)
        resumed_up = current_close > max(previous_close, current_ema)
        return touched_ema and closed_near_ema and resumed_up

    def _is_short_pullback(
        self,
        previous: pd.Series,
        current_close: float,
        previous_close: float,
        previous_ema: float,
        current_ema: float,
    ) -> bool:
        tolerance = self.config.pullback_tolerance_pct
        touched_ema = float(previous["High"]) >= previous_ema * (1.0 - tolerance)
        closed_near_ema = previous_close >= previous_ema * (1.0 - tolerance)
        resumed_down = current_close < min(previous_close, current_ema)
        return touched_ema and closed_near_ema and resumed_down

    def _signal(
        self,
        *,
        symbol: str,
        direction: Direction,
        close: float,
        previous_close: float,
        stop: float,
    ) -> Signal:
        cfg = self.config
        risk_per_unit = abs(close - stop)
        if risk_per_unit <= 0:
            target = None
        elif direction == Direction.LONG:
            target = close + cfg.risk_reward * risk_per_unit
        else:
            target = close - cfg.risk_reward * risk_per_unit
        score = _pullback_score(close, previous_close, cfg)
        return Signal(
            module=cfg.module,
            symbol=symbol,
            direction=direction,
            score=score,
            entry_reason=f"EMA{cfg.ema_length} pullback continuation",
            invalidation=f"Close loses EMA{cfg.ema_length} continuation structure",
            preferred_stop=stop,
            preferred_target=target,
            confidence=max(0.0, min(1.0, score / 100.0)),
            required_data=_required_ohlcv(cfg.timeframe),
        )


class MeanReversionSignalModule:
    """Emit a current-bar rolling-band mean-reversion signal from OHLCV data."""

    def __init__(self, config: MeanReversionSignalConfig | None = None):
        self.config = config or MeanReversionSignalConfig()
        self.name = self.config.module

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        cfg = self.config
        if features.empty or len(features) <= cfg.lookback:
            return []
        _require_columns(features, ("High", "Low", "Close"), "MeanReversionSignalModule")

        previous = features.iloc[:-1].tail(cfg.lookback)
        current = features.iloc[-1]
        mid = float(previous["Close"].mean())
        std = float(previous["Close"].std())
        if pd.isna(std) or std <= 0:
            return []

        lower = mid - cfg.std_mult * std
        upper = mid + cfg.std_mult * std
        close = float(current["Close"])
        low = float(current["Low"])
        high = float(current["High"])
        signals: list[Signal] = []

        if cfg.allow_long and low < lower < close < mid:
            stop = float(features["Low"].tail(cfg.stop_lookback + 1).min())
            if stop < close < mid:
                signals.append(self._signal(
                    symbol=symbol,
                    direction=Direction.LONG,
                    band=lower,
                    extreme=low,
                    stop=stop,
                    target=mid,
                ))
        if cfg.allow_short and high > upper > close > mid:
            stop = float(features["High"].tail(cfg.stop_lookback + 1).max())
            if stop > close > mid:
                signals.append(self._signal(
                    symbol=symbol,
                    direction=Direction.SHORT,
                    band=upper,
                    extreme=high,
                    stop=stop,
                    target=mid,
                ))
        return signals

    def _signal(
        self,
        *,
        symbol: str,
        direction: Direction,
        band: float,
        extreme: float,
        stop: float,
        target: float,
    ) -> Signal:
        cfg = self.config
        score = _mean_reversion_score(extreme, band, cfg)
        return Signal(
            module=cfg.module,
            symbol=symbol,
            direction=direction,
            score=score,
            entry_reason=f"{cfg.lookback}-bar rolling-band mean reversion",
            invalidation=f"Close returns outside {cfg.lookback}-bar mean-reversion band",
            preferred_stop=stop,
            preferred_target=target,
            confidence=max(0.0, min(1.0, score / 100.0)),
            required_data=_required_ohlcv(cfg.timeframe),
        )


class SweepReversalSignalModule:
    """Emit a current-bar range sweep and reclaim signal from OHLCV data."""

    def __init__(self, config: SweepReversalSignalConfig | None = None):
        self.config = config or SweepReversalSignalConfig()
        self.name = self.config.module

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        cfg = self.config
        if features.empty or len(features) <= cfg.lookback:
            return []
        _require_columns(features, ("High", "Low", "Close"), "SweepReversalSignalModule")

        previous = features.iloc[:-1].tail(cfg.lookback)
        current = features.iloc[-1]
        support = float(previous["Low"].min())
        resistance = float(previous["High"].max())
        low = float(current["Low"])
        high = float(current["High"])
        close = float(current["Close"])
        signals: list[Signal] = []

        if cfg.allow_long and low < support < close < resistance:
            signals.append(self._signal(
                symbol=symbol,
                direction=Direction.LONG,
                boundary=support,
                extreme=low,
                stop=low,
                target=resistance,
            ))
        if cfg.allow_short and high > resistance > close > support:
            signals.append(self._signal(
                symbol=symbol,
                direction=Direction.SHORT,
                boundary=resistance,
                extreme=high,
                stop=high,
                target=support,
            ))
        return signals

    def _signal(
        self,
        *,
        symbol: str,
        direction: Direction,
        boundary: float,
        extreme: float,
        stop: float,
        target: float,
    ) -> Signal:
        cfg = self.config
        score = _sweep_reversal_score(extreme, boundary, cfg)
        side = "low" if direction == Direction.LONG else "high"
        return Signal(
            module=cfg.module,
            symbol=symbol,
            direction=direction,
            score=score,
            entry_reason=f"{cfg.lookback}-bar {side} sweep reclaim",
            invalidation=f"Close loses reclaimed {cfg.lookback}-bar {side}",
            preferred_stop=stop,
            preferred_target=target,
            confidence=max(0.0, min(1.0, score / 100.0)),
            required_data=_required_ohlcv(cfg.timeframe),
        )


class CrashShortSignalModule:
    """Emit a current-bar crash impulse short signal from OHLCV data."""

    def __init__(self, config: CrashShortSignalConfig | None = None):
        self.config = config or CrashShortSignalConfig()
        self.name = self.config.module

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        cfg = self.config
        if features.empty or len(features) <= cfg.lookback:
            return []
        _require_columns(features, ("Open", "High", "Close", "Volume"), "CrashShortSignalModule")

        previous = features.iloc[:-1].tail(cfg.lookback)
        current = features.iloc[-1]
        previous_close = float(previous["Close"].iloc[-1])
        close = float(current["Close"])
        open_price = float(current["Open"])
        avg_volume = float(previous["Volume"].mean())
        current_volume = float(current["Volume"])
        if previous_close <= 0 or avg_volume <= 0:
            return []

        drop_pct = max(0.0, (previous_close - close) / previous_close)
        volume_ratio = current_volume / avg_volume
        if drop_pct < cfg.min_drop_pct:
            return []
        if volume_ratio < cfg.volume_multiplier:
            return []
        if close >= open_price or close >= previous_close:
            return []

        stop = float(features["High"].tail(cfg.stop_lookback + 1).max())
        risk_per_unit = stop - close
        if risk_per_unit <= 0:
            return []
        target = close - cfg.risk_reward * risk_per_unit
        score = _crash_short_score(drop_pct, volume_ratio, cfg)
        return [
            Signal(
                module=cfg.module,
                symbol=symbol,
                direction=Direction.SHORT,
                score=score,
                entry_reason=f"{drop_pct:.1%} crash impulse with volume expansion",
                invalidation="Crash impulse recovers above recent high",
                preferred_stop=stop,
                preferred_target=target,
                confidence=max(0.0, min(1.0, score / 100.0)),
                required_data=_required_ohlcv(cfg.timeframe),
            )
        ]


class FailedBounceSignalModule:
    """Emit a current-bar failed bounce short signal from OHLCV data."""

    def __init__(self, config: FailedBounceSignalConfig | None = None):
        self.config = config or FailedBounceSignalConfig()
        self.name = self.config.module

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        cfg = self.config
        if features.empty or len(features) < cfg.lookback + 2:
            return []
        _require_columns(features, ("Open", "High", "Low", "Close"), "FailedBounceSignalModule")

        range_bars = features.iloc[:-2].tail(cfg.lookback)
        setup = features.iloc[-2]
        current = features.iloc[-1]
        resistance = float(range_bars["High"].max())
        support = float(range_bars["Low"].min())
        setup_high = float(setup["High"])
        setup_low = float(setup["Low"])
        setup_close = float(setup["Close"])
        current_open = float(current["Open"])
        current_high = float(current["High"])
        current_close = float(current["Close"])
        if resistance <= 0 or support >= current_close:
            return []

        touched_resistance = setup_high >= resistance * (1.0 - cfg.resistance_tolerance_pct)
        rejected_resistance = setup_close < resistance
        breakdown = current_close < setup_low and current_close < current_open
        upper_wick = _upper_wick_fraction(setup)
        if not (touched_resistance and rejected_resistance and breakdown):
            return []
        if upper_wick < cfg.min_upper_wick_pct:
            return []

        stop = max(setup_high, current_high)
        if stop <= current_close:
            return []
        score = _failed_bounce_score(resistance, current_close, upper_wick, cfg)
        return [
            Signal(
                module=cfg.module,
                symbol=symbol,
                direction=Direction.SHORT,
                score=score,
                entry_reason="Failed bounce into resistance",
                invalidation="Price reclaims resistance after the failed bounce",
                preferred_stop=stop,
                preferred_target=support,
                confidence=max(0.0, min(1.0, score / 100.0)),
                required_data=_required_ohlcv(cfg.timeframe),
            )
        ]


class BullTrapSignalModule:
    """Emit a current-bar bull trap short signal from OHLCV data."""

    def __init__(self, config: BullTrapSignalConfig | None = None):
        self.config = config or BullTrapSignalConfig()
        self.name = self.config.module

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        cfg = self.config
        if features.empty or len(features) < cfg.lookback + 2:
            return []
        _require_columns(features, ("Open", "High", "Low", "Close", "Volume"), "BullTrapSignalModule")

        range_bars = features.iloc[:-2].tail(cfg.lookback)
        setup = features.iloc[-2]
        current = features.iloc[-1]
        resistance = float(range_bars["High"].max())
        support = float(range_bars["Low"].min())
        setup_high = float(setup["High"])
        setup_volume = float(setup["Volume"])
        avg_volume = float(range_bars["Volume"].mean())
        current_open = float(current["Open"])
        current_high = float(current["High"])
        current_close = float(current["Close"])
        if resistance <= 0 or avg_volume <= 0 or support >= current_close:
            return []

        breakout_pct = max(0.0, setup_high / resistance - 1.0)
        volume_ratio = setup_volume / avg_volume
        failed_breakout = setup_high > resistance and current_close < resistance and current_close < current_open
        weak_close = _close_position(current) < cfg.weak_close_threshold
        if not (failed_breakout and weak_close):
            return []
        if volume_ratio < cfg.volume_multiplier:
            return []

        stop = max(setup_high, current_high)
        if stop <= current_close:
            return []
        score = _bull_trap_score(breakout_pct, resistance, current_close, volume_ratio, cfg)
        return [
            Signal(
                module=cfg.module,
                symbol=symbol,
                direction=Direction.SHORT,
                score=score,
                entry_reason="Bull trap reversal below resistance",
                invalidation="Price reclaims the trap resistance",
                preferred_stop=stop,
                preferred_target=support,
                confidence=max(0.0, min(1.0, score / 100.0)),
                required_data=_required_ohlcv(cfg.timeframe),
            )
        ]


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


def default_signal_module_registry() -> SignalModuleRegistry:
    """Return registry entries for platform signal modules."""
    registry = SignalModuleRegistry()
    registry.register("column", lambda params: ColumnSignalModule(ColumnSignalConfig(**_column_params(params))))
    registry.register("breakout", lambda params: BreakoutSignalModule(BreakoutSignalConfig(**params)))
    registry.register("pullback", lambda params: PullbackSignalModule(PullbackSignalConfig(**params)))
    registry.register(
        "mean_reversion",
        lambda params: MeanReversionSignalModule(MeanReversionSignalConfig(**params)),
    )
    registry.register("sweep_reversal", lambda params: SweepReversalSignalModule(SweepReversalSignalConfig(**params)))
    registry.register("crash_short", lambda params: CrashShortSignalModule(CrashShortSignalConfig(**params)))
    registry.register(
        "failed_bounce",
        lambda params: FailedBounceSignalModule(FailedBounceSignalConfig(**params)),
    )
    registry.register("bull_trap", lambda params: BullTrapSignalModule(BullTrapSignalConfig(**params)))
    return registry


def _column_params(params: dict[str, object]) -> dict[str, object]:
    converted = dict(params)
    required_data = converted.get("required_data")
    if isinstance(required_data, list):
        converted["required_data"] = tuple(required_data)
    return converted


def _optional_float(row: pd.Series, column: str | None) -> float | None:
    if not column:
        return None
    value = row.get(column)
    if pd.isna(value):
        return None
    return float(value)


def _require_columns(features: pd.DataFrame, columns: tuple[str, ...], module: str) -> None:
    missing = [column for column in columns if column not in features.columns]
    if missing:
        raise ValueError(f"{module} requires columns: {', '.join(missing)}")


def _required_ohlcv(timeframe: str) -> tuple[str, ...]:
    return (f"ohlcv:{timeframe}",) if timeframe else ("ohlcv",)


def _breakout_score(close: float, boundary: float, cfg: BreakoutSignalConfig) -> float:
    if boundary == 0:
        return cfg.score_floor
    breakout_pct = abs(close / boundary - 1.0)
    return max(0.0, min(100.0, cfg.score_floor + breakout_pct * cfg.score_breakout_scale))


def _pullback_score(close: float, previous_close: float, cfg: PullbackSignalConfig) -> float:
    if previous_close == 0:
        return cfg.score_floor
    resume_pct = abs(close / previous_close - 1.0)
    return max(0.0, min(100.0, cfg.score_floor + resume_pct * cfg.score_resume_scale))


def _mean_reversion_score(extreme: float, band: float, cfg: MeanReversionSignalConfig) -> float:
    if band == 0:
        return cfg.score_floor
    deviation_pct = abs(extreme / band - 1.0)
    return max(0.0, min(100.0, cfg.score_floor + deviation_pct * cfg.score_deviation_scale))


def _sweep_reversal_score(extreme: float, boundary: float, cfg: SweepReversalSignalConfig) -> float:
    if boundary == 0:
        return cfg.score_floor
    sweep_pct = abs(extreme / boundary - 1.0)
    return max(0.0, min(100.0, cfg.score_floor + sweep_pct * cfg.score_sweep_scale))


def _crash_short_score(drop_pct: float, volume_ratio: float, cfg: CrashShortSignalConfig) -> float:
    excess_drop = max(0.0, drop_pct - cfg.min_drop_pct)
    excess_volume = max(0.0, volume_ratio - cfg.volume_multiplier)
    score = cfg.score_floor + excess_drop * cfg.score_drop_scale + excess_volume * cfg.score_volume_scale
    return max(0.0, min(100.0, score))


def _failed_bounce_score(
    resistance: float,
    current_close: float,
    upper_wick: float,
    cfg: FailedBounceSignalConfig,
) -> float:
    rejection_pct = max(0.0, resistance / current_close - 1.0) if current_close > 0 else 0.0
    score = cfg.score_floor + rejection_pct * cfg.score_rejection_scale + upper_wick * cfg.score_wick_scale
    return max(0.0, min(100.0, score))


def _bull_trap_score(
    breakout_pct: float,
    resistance: float,
    current_close: float,
    volume_ratio: float,
    cfg: BullTrapSignalConfig,
) -> float:
    rejection_pct = max(0.0, resistance / current_close - 1.0) if current_close > 0 else 0.0
    excess_volume = max(0.0, volume_ratio - cfg.volume_multiplier)
    score = (
        cfg.score_floor
        + breakout_pct * cfg.score_breakout_scale
        + rejection_pct * cfg.score_rejection_scale
        + excess_volume * cfg.score_volume_scale
    )
    return max(0.0, min(100.0, score))


def _upper_wick_fraction(row: pd.Series) -> float:
    high = float(row["High"])
    low = float(row["Low"])
    candle_range = high - low
    if candle_range <= 0:
        return 0.0
    body_top = max(float(row["Open"]), float(row["Close"]))
    return max(0.0, (high - body_top) / candle_range)


def _close_position(row: pd.Series) -> float:
    high = float(row["High"])
    low = float(row["Low"])
    candle_range = high - low
    if candle_range <= 0:
        return 0.5
    return (float(row["Close"]) - low) / candle_range

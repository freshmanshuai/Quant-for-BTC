"""TradingView Pine generation from platform signal-module configs."""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant_platform.delivery import PineGoldenVector, write_pine_golden_vectors_json
from quant_platform.signal_modules import (
    BreakoutSignalConfig,
    BreakoutSignalModule,
    BullTrapSignalConfig,
    BullTrapSignalModule,
    CrashShortSignalConfig,
    CrashShortSignalModule,
    FailedBounceSignalConfig,
    FailedBounceSignalModule,
    MeanReversionSignalConfig,
    MeanReversionSignalModule,
    PullbackSignalConfig,
    PullbackSignalModule,
    SignalModule,
    SignalModuleRunner,
    SweepReversalSignalConfig,
    SweepReversalSignalModule,
)


class PineGenerationError(ValueError):
    """Raised when a signal-module config cannot be rendered to Pine."""


def generate_signal_module_pine(
    configs: Sequence[Any],
    *,
    title: str = "Generated Signal Modules",
    layer: str = "tactical",
) -> str:
    """Generate a Pine v6 indicator from standardized signal-module configs."""
    lines = [
        "//@version=6",
        f'indicator("{_pine_string(title)}", overlay=true)',
        "",
        "// Generated from quant_platform signal-module config. Do not edit signal constants by hand.",
        'pineObservationHeader = "signal_key,bar_time,entry_price,stop_price,target_price,score"',
    ]
    for config in configs:
        if isinstance(config, BreakoutSignalConfig):
            lines.extend(_breakout_lines(config, layer=layer))
        elif isinstance(config, PullbackSignalConfig):
            lines.extend(_pullback_lines(config, layer=layer))
        elif isinstance(config, MeanReversionSignalConfig):
            lines.extend(_mean_reversion_lines(config, layer=layer))
        elif isinstance(config, SweepReversalSignalConfig):
            lines.extend(_sweep_reversal_lines(config, layer=layer))
        elif isinstance(config, CrashShortSignalConfig):
            lines.extend(_crash_short_lines(config, layer=layer))
        elif isinstance(config, FailedBounceSignalConfig):
            lines.extend(_failed_bounce_lines(config, layer=layer))
        elif isinstance(config, BullTrapSignalConfig):
            lines.extend(_bull_trap_lines(config, layer=layer))
        else:
            raise PineGenerationError(f"Unsupported Pine signal module config: {type(config).__name__}")
    return "\n".join(lines) + "\n"


def write_pine_script(path: str | Path, source: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")


def write_signal_module_pine_parity_example(
    output_dir: str | Path,
    *,
    config_path: str | Path | None = None,
    module_set: str | None = None,
    timeframe: str = "",
) -> dict[str, Path]:
    """Write a generated Pine script plus Python/Pine parity example files."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    configs = (
        load_signal_module_pine_configs_json(config_path, module_set=module_set, timeframe=timeframe)
        if config_path is not None
        else _parity_example_configs()
    )
    source = generate_signal_module_pine(
        configs,
        title="Generated Signal Module Parity Example",
        layer="tactical",
    )
    pine_script = target / "signal_module_parity.pine"
    expected_vectors = target / "expected_vectors.json"
    observed_template = target / "observed_template.csv"

    write_pine_script(pine_script, source)
    vectors = _parity_example_vectors(symbol="AAPL", configs=configs)
    write_pine_golden_vectors_json(expected_vectors, vectors)
    observed_template.write_text(_pine_observation_csv(vectors), encoding="utf-8")
    return {
        "pine_script": pine_script,
        "expected_vectors": expected_vectors,
        "observed_template": observed_template,
    }


def load_signal_module_pine_configs_json(
    path: str | Path,
    *,
    module_set: str | None = None,
    timeframe: str = "",
) -> tuple[Any, ...]:
    """Load Pine-supported signal-module configs from a research signal config file."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    selected_name = module_set or payload.get("default_module_set")
    if not selected_name:
        raise PineGenerationError("Pine signal config requires module_set or default_module_set.")
    for record in payload.get("module_sets", []):
        if record.get("name") == selected_name:
            return tuple(_pine_config_from_record(item, timeframe=timeframe) for item in record.get("modules", []))
    raise PineGenerationError(f"Pine signal module set not found: {selected_name}")


def _pine_config_from_record(record: dict[str, Any], *, timeframe: str) -> Any:
    module_type = record.get("type")
    params = dict(record.get("params") or {})
    if module_type != "column" and timeframe and "timeframe" not in params:
        params["timeframe"] = timeframe
    if module_type == "breakout":
        return BreakoutSignalConfig(**params)
    if module_type == "pullback":
        return PullbackSignalConfig(**params)
    if module_type == "mean_reversion":
        return MeanReversionSignalConfig(**params)
    if module_type == "sweep_reversal":
        return SweepReversalSignalConfig(**params)
    if module_type == "crash_short":
        return CrashShortSignalConfig(**params)
    if module_type == "failed_bounce":
        return FailedBounceSignalConfig(**params)
    if module_type == "bull_trap":
        return BullTrapSignalConfig(**params)
    raise PineGenerationError(f"Unsupported Pine signal module type: {module_type}")


def _breakout_lines(config: BreakoutSignalConfig, *, layer: str) -> list[str]:
    prefix = _pine_identifier(config.module)
    close = f"{prefix}_close"
    high = f"{prefix}_high"
    low = f"{prefix}_low"
    long_signal = f"{close} > {prefix}_channelHigh" if config.allow_long else "false"
    short_signal = f"{close} < {prefix}_channelLow" if config.allow_short else "false"
    lines = [
        "",
        f"// {config.module}",
        f'{prefix}_lookback = input.int({config.lookback}, "{_pine_string(config.module)} lookback", minval=1)',
        f'{prefix}_riskReward = input.float({_pine_float(config.risk_reward)}, "{_pine_string(config.module)} risk reward", minval=0.0)',
        f'{prefix}_scoreFloor = input.float({_pine_float(config.score_floor)}, "{_pine_string(config.module)} score floor")',
        f'{prefix}_scoreBreakoutScale = input.float({_pine_float(config.score_breakout_scale)}, "{_pine_string(config.module)} score breakout scale")',
    ]
    lines.extend(_source_lines(prefix, config.timeframe))
    lines.extend([
        f"{prefix}_channelHigh = ta.highest({high}[1], {prefix}_lookback)",
        f"{prefix}_channelLow = ta.lowest({low}[1], {prefix}_lookback)",
        f"{prefix}_longBreakoutPct = math.max(0.0, ({close} - {prefix}_channelHigh) / {prefix}_channelHigh)",
        f"{prefix}_shortBreakoutPct = math.max(0.0, ({prefix}_channelLow - {close}) / {prefix}_channelLow)",
        f"{prefix}_longScore = {prefix}_scoreFloor + {prefix}_longBreakoutPct * {prefix}_scoreBreakoutScale",
        f"{prefix}_shortScore = {prefix}_scoreFloor + {prefix}_shortBreakoutPct * {prefix}_scoreBreakoutScale",
        f"{prefix}_longStop = {prefix}_channelLow",
        f"{prefix}_shortStop = {prefix}_channelHigh",
        f"{prefix}_longTarget = {close} + {prefix}_riskReward * math.abs({close} - {prefix}_longStop)",
        f"{prefix}_shortTarget = {close} - {prefix}_riskReward * math.abs({close} - {prefix}_shortStop)",
        f"{prefix}_longSignal = {long_signal}",
        f"{prefix}_shortSignal = {short_signal}",
        f'{prefix}_longSignalKey = str.format("{{0}}|{_pine_string(layer)}|{_pine_string(config.module)}|long", syminfo.ticker)',
        f'{prefix}_shortSignalKey = str.format("{{0}}|{_pine_string(layer)}|{_pine_string(config.module)}|short", syminfo.ticker)',
        f'plotshape({prefix}_longSignal, title="{_pine_string(config.module)} Long", style=shape.triangleup, location=location.belowbar, color=color.lime, text="L")',
        f'plotshape({prefix}_shortSignal, title="{_pine_string(config.module)} Short", style=shape.triangledown, location=location.abovebar, color=color.red, text="S")',
        f'if {prefix}_longSignal',
        f'    alert(str.format("{{0}},{{1}},{{2}},{{3}},{{4}},{{5}}", {prefix}_longSignalKey, str.tostring(time), str.tostring({close}), str.tostring({prefix}_longStop), str.tostring({prefix}_longTarget), str.tostring({prefix}_longScore)), alert.freq_once_per_bar_close)',
        f'if {prefix}_shortSignal',
        f'    alert(str.format("{{0}},{{1}},{{2}},{{3}},{{4}},{{5}}", {prefix}_shortSignalKey, str.tostring(time), str.tostring({close}), str.tostring({prefix}_shortStop), str.tostring({prefix}_shortTarget), str.tostring({prefix}_shortScore)), alert.freq_once_per_bar_close)',
    ])
    return lines


def _pullback_lines(config: PullbackSignalConfig, *, layer: str) -> list[str]:
    prefix = _pine_identifier(config.module)
    close = f"{prefix}_close"
    high = f"{prefix}_high"
    low = f"{prefix}_low"
    ema_value = f"{prefix}_ema"
    previous_close = f"{prefix}_previousClose"
    previous_high = f"{prefix}_previousHigh"
    previous_low = f"{prefix}_previousLow"
    previous_ema = f"{prefix}_previousEma"
    long_signal = (
        f"{previous_low} <= {previous_ema} * (1.0 + {prefix}_pullbackTolerancePct) "
        f"and {previous_close} <= {previous_ema} * (1.0 + {prefix}_pullbackTolerancePct) "
        f"and {close} > math.max({previous_close}, {ema_value})"
        if config.allow_long else "false"
    )
    short_signal = (
        f"{previous_high} >= {previous_ema} * (1.0 - {prefix}_pullbackTolerancePct) "
        f"and {previous_close} >= {previous_ema} * (1.0 - {prefix}_pullbackTolerancePct) "
        f"and {close} < math.min({previous_close}, {ema_value})"
        if config.allow_short else "false"
    )
    lines = [
        "",
        f"// {config.module}",
        f'{prefix}_emaLength = input.int({config.ema_length}, "{_pine_string(config.module)} EMA length", minval=1)',
        f'{prefix}_pullbackTolerancePct = input.float({_pine_float(config.pullback_tolerance_pct)}, "{_pine_string(config.module)} pullback tolerance pct", minval=0.0)',
        f'{prefix}_stopLookback = input.int({config.stop_lookback}, "{_pine_string(config.module)} stop lookback", minval=1)',
        f'{prefix}_riskReward = input.float({_pine_float(config.risk_reward)}, "{_pine_string(config.module)} risk reward", minval=0.0)',
        f'{prefix}_scoreFloor = input.float({_pine_float(config.score_floor)}, "{_pine_string(config.module)} score floor")',
        f'{prefix}_scoreResumeScale = input.float({_pine_float(config.score_resume_scale)}, "{_pine_string(config.module)} score resume scale")',
    ]
    lines.extend(_source_lines(prefix, config.timeframe))
    lines.extend([
        f"{ema_value} = ta.ema({close}, {prefix}_emaLength)",
        f"{previous_close} = {close}[1]",
        f"{previous_high} = {high}[1]",
        f"{previous_low} = {low}[1]",
        f"{previous_ema} = {ema_value}[1]",
        f"{prefix}_resumePct = {previous_close} == 0.0 ? 0.0 : math.abs({close} / {previous_close} - 1.0)",
        f"{prefix}_score = {prefix}_scoreFloor + {prefix}_resumePct * {prefix}_scoreResumeScale",
        f"{prefix}_longStop = ta.lowest({low}, {prefix}_stopLookback + 1)",
        f"{prefix}_shortStop = ta.highest({high}, {prefix}_stopLookback + 1)",
        f"{prefix}_longTarget = {close} + {prefix}_riskReward * math.abs({close} - {prefix}_longStop)",
        f"{prefix}_shortTarget = {close} - {prefix}_riskReward * math.abs({close} - {prefix}_shortStop)",
        f"{prefix}_longSignal = {long_signal}",
        f"{prefix}_shortSignal = {short_signal}",
        f'{prefix}_longSignalKey = str.format("{{0}}|{_pine_string(layer)}|{_pine_string(config.module)}|long", syminfo.ticker)',
        f'{prefix}_shortSignalKey = str.format("{{0}}|{_pine_string(layer)}|{_pine_string(config.module)}|short", syminfo.ticker)',
        f'plotshape({prefix}_longSignal, title="{_pine_string(config.module)} Long", style=shape.triangleup, location=location.belowbar, color=color.lime, text="L")',
        f'plotshape({prefix}_shortSignal, title="{_pine_string(config.module)} Short", style=shape.triangledown, location=location.abovebar, color=color.red, text="S")',
        f'if {prefix}_longSignal',
        f'    alert(str.format("{{0}},{{1}},{{2}},{{3}},{{4}},{{5}}", {prefix}_longSignalKey, str.tostring(time), str.tostring({close}), str.tostring({prefix}_longStop), str.tostring({prefix}_longTarget), str.tostring({prefix}_score)), alert.freq_once_per_bar_close)',
        f'if {prefix}_shortSignal',
        f'    alert(str.format("{{0}},{{1}},{{2}},{{3}},{{4}},{{5}}", {prefix}_shortSignalKey, str.tostring(time), str.tostring({close}), str.tostring({prefix}_shortStop), str.tostring({prefix}_shortTarget), str.tostring({prefix}_score)), alert.freq_once_per_bar_close)',
    ])
    return lines


def _mean_reversion_lines(config: MeanReversionSignalConfig, *, layer: str) -> list[str]:
    prefix = _pine_identifier(config.module)
    close = f"{prefix}_close"
    high = f"{prefix}_high"
    low = f"{prefix}_low"
    mid = f"{prefix}_mid"
    lower = f"{prefix}_lower"
    upper = f"{prefix}_upper"
    long_stop = f"{prefix}_longStop"
    short_stop = f"{prefix}_shortStop"
    long_signal = (
        f"{low} < {lower} and {lower} < {close} and {close} < {mid} and {long_stop} < {close}"
        if config.allow_long else "false"
    )
    short_signal = (
        f"{high} > {upper} and {upper} > {close} and {close} > {mid} and {short_stop} > {close}"
        if config.allow_short else "false"
    )
    lines = [
        "",
        f"// {config.module}",
        f'{prefix}_lookback = input.int({config.lookback}, "{_pine_string(config.module)} lookback", minval=1)',
        f'{prefix}_stdMult = input.float({_pine_float(config.std_mult)}, "{_pine_string(config.module)} std mult", minval=0.0)',
        f'{prefix}_stopLookback = input.int({config.stop_lookback}, "{_pine_string(config.module)} stop lookback", minval=1)',
        f'{prefix}_scoreFloor = input.float({_pine_float(config.score_floor)}, "{_pine_string(config.module)} score floor")',
        f'{prefix}_scoreDeviationScale = input.float({_pine_float(config.score_deviation_scale)}, "{_pine_string(config.module)} score deviation scale")',
    ]
    lines.extend(_source_lines(prefix, config.timeframe))
    lines.extend([
        f"{mid} = ta.sma({close}[1], {prefix}_lookback)",
        f"{prefix}_std = ta.stdev({close}[1], {prefix}_lookback, false)",
        f"{lower} = {mid} - {prefix}_stdMult * {prefix}_std",
        f"{upper} = {mid} + {prefix}_stdMult * {prefix}_std",
        f"{long_stop} = ta.lowest({low}, {prefix}_stopLookback + 1)",
        f"{short_stop} = ta.highest({high}, {prefix}_stopLookback + 1)",
        f"{prefix}_longDeviationPct = {lower} == 0.0 ? 0.0 : math.abs({low} / {lower} - 1.0)",
        f"{prefix}_shortDeviationPct = {upper} == 0.0 ? 0.0 : math.abs({high} / {upper} - 1.0)",
        f"{prefix}_longScore = math.max(0.0, math.min(100.0, {prefix}_scoreFloor + {prefix}_longDeviationPct * {prefix}_scoreDeviationScale))",
        f"{prefix}_shortScore = math.max(0.0, math.min(100.0, {prefix}_scoreFloor + {prefix}_shortDeviationPct * {prefix}_scoreDeviationScale))",
        f"{prefix}_longTarget = {mid}",
        f"{prefix}_shortTarget = {mid}",
        f"{prefix}_longSignal = {long_signal}",
        f"{prefix}_shortSignal = {short_signal}",
        f'{prefix}_longSignalKey = str.format("{{0}}|{_pine_string(layer)}|{_pine_string(config.module)}|long", syminfo.ticker)',
        f'{prefix}_shortSignalKey = str.format("{{0}}|{_pine_string(layer)}|{_pine_string(config.module)}|short", syminfo.ticker)',
        f'plotshape({prefix}_longSignal, title="{_pine_string(config.module)} Long", style=shape.triangleup, location=location.belowbar, color=color.lime, text="L")',
        f'plotshape({prefix}_shortSignal, title="{_pine_string(config.module)} Short", style=shape.triangledown, location=location.abovebar, color=color.red, text="S")',
        f'if {prefix}_longSignal',
        f'    alert(str.format("{{0}},{{1}},{{2}},{{3}},{{4}},{{5}}", {prefix}_longSignalKey, str.tostring(time), str.tostring({close}), str.tostring({long_stop}), str.tostring({prefix}_longTarget), str.tostring({prefix}_longScore)), alert.freq_once_per_bar_close)',
        f'if {prefix}_shortSignal',
        f'    alert(str.format("{{0}},{{1}},{{2}},{{3}},{{4}},{{5}}", {prefix}_shortSignalKey, str.tostring(time), str.tostring({close}), str.tostring({short_stop}), str.tostring({prefix}_shortTarget), str.tostring({prefix}_shortScore)), alert.freq_once_per_bar_close)',
    ])
    return lines


def _sweep_reversal_lines(config: SweepReversalSignalConfig, *, layer: str) -> list[str]:
    prefix = _pine_identifier(config.module)
    close = f"{prefix}_close"
    high = f"{prefix}_high"
    low = f"{prefix}_low"
    support = f"{prefix}_support"
    resistance = f"{prefix}_resistance"
    long_signal = (
        f"{low} < {support} and {support} < {close} and {close} < {resistance}"
        if config.allow_long else "false"
    )
    short_signal = (
        f"{high} > {resistance} and {resistance} > {close} and {close} > {support}"
        if config.allow_short else "false"
    )
    lines = [
        "",
        f"// {config.module}",
        f'{prefix}_lookback = input.int({config.lookback}, "{_pine_string(config.module)} lookback", minval=1)',
        f'{prefix}_scoreFloor = input.float({_pine_float(config.score_floor)}, "{_pine_string(config.module)} score floor")',
        f'{prefix}_scoreSweepScale = input.float({_pine_float(config.score_sweep_scale)}, "{_pine_string(config.module)} score sweep scale")',
    ]
    lines.extend(_source_lines(prefix, config.timeframe))
    lines.extend([
        f"{support} = ta.lowest({low}[1], {prefix}_lookback)",
        f"{resistance} = ta.highest({high}[1], {prefix}_lookback)",
        f"{prefix}_longSweepPct = {support} == 0.0 ? 0.0 : math.abs({low} / {support} - 1.0)",
        f"{prefix}_shortSweepPct = {resistance} == 0.0 ? 0.0 : math.abs({high} / {resistance} - 1.0)",
        f"{prefix}_longScore = math.max(0.0, math.min(100.0, {prefix}_scoreFloor + {prefix}_longSweepPct * {prefix}_scoreSweepScale))",
        f"{prefix}_shortScore = math.max(0.0, math.min(100.0, {prefix}_scoreFloor + {prefix}_shortSweepPct * {prefix}_scoreSweepScale))",
        f"{prefix}_longStop = {low}",
        f"{prefix}_shortStop = {high}",
        f"{prefix}_longTarget = {resistance}",
        f"{prefix}_shortTarget = {support}",
        f"{prefix}_longSignal = {long_signal}",
        f"{prefix}_shortSignal = {short_signal}",
        f'{prefix}_longSignalKey = str.format("{{0}}|{_pine_string(layer)}|{_pine_string(config.module)}|long", syminfo.ticker)',
        f'{prefix}_shortSignalKey = str.format("{{0}}|{_pine_string(layer)}|{_pine_string(config.module)}|short", syminfo.ticker)',
        f'plotshape({prefix}_longSignal, title="{_pine_string(config.module)} Long", style=shape.triangleup, location=location.belowbar, color=color.lime, text="L")',
        f'plotshape({prefix}_shortSignal, title="{_pine_string(config.module)} Short", style=shape.triangledown, location=location.abovebar, color=color.red, text="S")',
        f'if {prefix}_longSignal',
        f'    alert(str.format("{{0}},{{1}},{{2}},{{3}},{{4}},{{5}}", {prefix}_longSignalKey, str.tostring(time), str.tostring({close}), str.tostring({prefix}_longStop), str.tostring({prefix}_longTarget), str.tostring({prefix}_longScore)), alert.freq_once_per_bar_close)',
        f'if {prefix}_shortSignal',
        f'    alert(str.format("{{0}},{{1}},{{2}},{{3}},{{4}},{{5}}", {prefix}_shortSignalKey, str.tostring(time), str.tostring({close}), str.tostring({prefix}_shortStop), str.tostring({prefix}_shortTarget), str.tostring({prefix}_shortScore)), alert.freq_once_per_bar_close)',
    ])
    return lines


def _crash_short_lines(config: CrashShortSignalConfig, *, layer: str) -> list[str]:
    prefix = _pine_identifier(config.module)
    close = f"{prefix}_close"
    high = f"{prefix}_high"
    open_price = f"{prefix}_open"
    volume = f"{prefix}_volume"
    previous_close = f"{prefix}_previousClose"
    avg_volume = f"{prefix}_avgVolume"
    stop = f"{prefix}_stop"
    target = f"{prefix}_target"
    short_signal = (
        f"{prefix}_dropPct >= {prefix}_minDropPct "
        f"and {prefix}_volumeRatio >= {prefix}_volumeMultiplier "
        f"and {close} < {open_price} "
        f"and {close} < {previous_close} "
        f"and {stop} > {close}"
    )
    lines = [
        "",
        f"// {config.module}",
        f'{prefix}_lookback = input.int({config.lookback}, "{_pine_string(config.module)} lookback", minval=1)',
        f'{prefix}_minDropPct = input.float({_pine_float(config.min_drop_pct)}, "{_pine_string(config.module)} min drop pct", minval=0.0)',
        f'{prefix}_volumeMultiplier = input.float({_pine_float(config.volume_multiplier)}, "{_pine_string(config.module)} volume multiplier", minval=0.0)',
        f'{prefix}_stopLookback = input.int({config.stop_lookback}, "{_pine_string(config.module)} stop lookback", minval=1)',
        f'{prefix}_riskReward = input.float({_pine_float(config.risk_reward)}, "{_pine_string(config.module)} risk reward", minval=0.0)',
        f'{prefix}_scoreFloor = input.float({_pine_float(config.score_floor)}, "{_pine_string(config.module)} score floor")',
        f'{prefix}_scoreDropScale = input.float({_pine_float(config.score_drop_scale)}, "{_pine_string(config.module)} score drop scale")',
        f'{prefix}_scoreVolumeScale = input.float({_pine_float(config.score_volume_scale)}, "{_pine_string(config.module)} score volume scale")',
    ]
    lines.extend(_source_lines(prefix, config.timeframe))
    lines.extend(_source_lines_for_fields(prefix, config.timeframe, ("open", "volume")))
    lines.extend([
        f"{previous_close} = {close}[1]",
        f"{avg_volume} = ta.sma({volume}[1], {prefix}_lookback)",
        f"{prefix}_dropPct = {previous_close} <= 0.0 ? 0.0 : math.max(0.0, ({previous_close} - {close}) / {previous_close})",
        f"{prefix}_volumeRatio = {avg_volume} <= 0.0 ? 0.0 : {volume} / {avg_volume}",
        f"{stop} = ta.highest({high}, {prefix}_stopLookback + 1)",
        f"{target} = {close} - {prefix}_riskReward * math.abs({stop} - {close})",
        f"{prefix}_excessDrop = math.max(0.0, {prefix}_dropPct - {prefix}_minDropPct)",
        f"{prefix}_excessVolume = math.max(0.0, {prefix}_volumeRatio - {prefix}_volumeMultiplier)",
        f"{prefix}_score = math.max(0.0, math.min(100.0, {prefix}_scoreFloor + {prefix}_excessDrop * {prefix}_scoreDropScale + {prefix}_excessVolume * {prefix}_scoreVolumeScale))",
        f"{prefix}_shortSignal = {short_signal}",
        f'{prefix}_shortSignalKey = str.format("{{0}}|{_pine_string(layer)}|{_pine_string(config.module)}|short", syminfo.ticker)',
        f'plotshape({prefix}_shortSignal, title="{_pine_string(config.module)} Short", style=shape.triangledown, location=location.abovebar, color=color.red, text="S")',
        f'if {prefix}_shortSignal',
        f'    alert(str.format("{{0}},{{1}},{{2}},{{3}},{{4}},{{5}}", {prefix}_shortSignalKey, str.tostring(time), str.tostring({close}), str.tostring({stop}), str.tostring({target}), str.tostring({prefix}_score)), alert.freq_once_per_bar_close)',
    ])
    return lines


def _failed_bounce_lines(config: FailedBounceSignalConfig, *, layer: str) -> list[str]:
    prefix = _pine_identifier(config.module)
    close = f"{prefix}_close"
    high = f"{prefix}_high"
    low = f"{prefix}_low"
    open_price = f"{prefix}_open"
    resistance = f"{prefix}_resistance"
    support = f"{prefix}_support"
    setup_high = f"{prefix}_setupHigh"
    setup_low = f"{prefix}_setupLow"
    setup_close = f"{prefix}_setupClose"
    setup_open = f"{prefix}_setupOpen"
    upper_wick = f"{prefix}_upperWick"
    stop = f"{prefix}_stop"
    target = f"{prefix}_target"
    short_signal = (
        f"{resistance} > 0.0 "
        f"and {support} < {close} "
        f"and {setup_high} >= {resistance} * (1.0 - {prefix}_resistanceTolerancePct) "
        f"and {setup_close} < {resistance} "
        f"and {close} < {setup_low} "
        f"and {close} < {open_price} "
        f"and {upper_wick} >= {prefix}_minUpperWickPct "
        f"and {stop} > {close}"
    )
    lines = [
        "",
        f"// {config.module}",
        f'{prefix}_lookback = input.int({config.lookback}, "{_pine_string(config.module)} lookback", minval=1)',
        f'{prefix}_resistanceTolerancePct = input.float({_pine_float(config.resistance_tolerance_pct)}, "{_pine_string(config.module)} resistance tolerance pct", minval=0.0)',
        f'{prefix}_minUpperWickPct = input.float({_pine_float(config.min_upper_wick_pct)}, "{_pine_string(config.module)} min upper wick pct", minval=0.0)',
        f'{prefix}_scoreFloor = input.float({_pine_float(config.score_floor)}, "{_pine_string(config.module)} score floor")',
        f'{prefix}_scoreRejectionScale = input.float({_pine_float(config.score_rejection_scale)}, "{_pine_string(config.module)} score rejection scale")',
        f'{prefix}_scoreWickScale = input.float({_pine_float(config.score_wick_scale)}, "{_pine_string(config.module)} score wick scale")',
    ]
    lines.extend(_source_lines(prefix, config.timeframe))
    lines.extend(_source_lines_for_fields(prefix, config.timeframe, ("open",)))
    lines.extend([
        f"{resistance} = ta.highest({high}[2], {prefix}_lookback)",
        f"{support} = ta.lowest({low}[2], {prefix}_lookback)",
        f"{setup_high} = {high}[1]",
        f"{setup_low} = {low}[1]",
        f"{setup_close} = {close}[1]",
        f"{setup_open} = {open_price}[1]",
        f"{prefix}_setupRange = {setup_high} - {setup_low}",
        f"{prefix}_setupBodyTop = math.max({setup_open}, {setup_close})",
        f"{upper_wick} = {prefix}_setupRange <= 0.0 ? 0.0 : math.max(0.0, ({setup_high} - {prefix}_setupBodyTop) / {prefix}_setupRange)",
        f"{stop} = math.max({setup_high}, {high})",
        f"{target} = {support}",
        f"{prefix}_rejectionPct = {close} <= 0.0 ? 0.0 : math.max(0.0, {resistance} / {close} - 1.0)",
        f"{prefix}_score = math.max(0.0, math.min(100.0, {prefix}_scoreFloor + {prefix}_rejectionPct * {prefix}_scoreRejectionScale + {upper_wick} * {prefix}_scoreWickScale))",
        f"{prefix}_shortSignal = {short_signal}",
        f'{prefix}_shortSignalKey = str.format("{{0}}|{_pine_string(layer)}|{_pine_string(config.module)}|short", syminfo.ticker)',
        f'plotshape({prefix}_shortSignal, title="{_pine_string(config.module)} Short", style=shape.triangledown, location=location.abovebar, color=color.red, text="S")',
        f'if {prefix}_shortSignal',
        f'    alert(str.format("{{0}},{{1}},{{2}},{{3}},{{4}},{{5}}", {prefix}_shortSignalKey, str.tostring(time), str.tostring({close}), str.tostring({stop}), str.tostring({target}), str.tostring({prefix}_score)), alert.freq_once_per_bar_close)',
    ])
    return lines


def _bull_trap_lines(config: BullTrapSignalConfig, *, layer: str) -> list[str]:
    prefix = _pine_identifier(config.module)
    close = f"{prefix}_close"
    high = f"{prefix}_high"
    low = f"{prefix}_low"
    open_price = f"{prefix}_open"
    volume = f"{prefix}_volume"
    resistance = f"{prefix}_resistance"
    support = f"{prefix}_support"
    setup_high = f"{prefix}_setupHigh"
    setup_volume = f"{prefix}_setupVolume"
    avg_volume = f"{prefix}_avgVolume"
    close_position = f"{prefix}_closePosition"
    stop = f"{prefix}_stop"
    target = f"{prefix}_target"
    short_signal = (
        f"{resistance} > 0.0 "
        f"and {avg_volume} > 0.0 "
        f"and {support} < {close} "
        f"and {setup_high} > {resistance} "
        f"and {close} < {resistance} "
        f"and {close} < {open_price} "
        f"and {close_position} < {prefix}_weakCloseThreshold "
        f"and {prefix}_volumeRatio >= {prefix}_volumeMultiplier "
        f"and {stop} > {close}"
    )
    lines = [
        "",
        f"// {config.module}",
        f'{prefix}_lookback = input.int({config.lookback}, "{_pine_string(config.module)} lookback", minval=1)',
        f'{prefix}_volumeMultiplier = input.float({_pine_float(config.volume_multiplier)}, "{_pine_string(config.module)} volume multiplier", minval=0.0)',
        f'{prefix}_weakCloseThreshold = input.float({_pine_float(config.weak_close_threshold)}, "{_pine_string(config.module)} weak close threshold", minval=0.0)',
        f'{prefix}_scoreFloor = input.float({_pine_float(config.score_floor)}, "{_pine_string(config.module)} score floor")',
        f'{prefix}_scoreBreakoutScale = input.float({_pine_float(config.score_breakout_scale)}, "{_pine_string(config.module)} score breakout scale")',
        f'{prefix}_scoreRejectionScale = input.float({_pine_float(config.score_rejection_scale)}, "{_pine_string(config.module)} score rejection scale")',
        f'{prefix}_scoreVolumeScale = input.float({_pine_float(config.score_volume_scale)}, "{_pine_string(config.module)} score volume scale")',
    ]
    lines.extend(_source_lines(prefix, config.timeframe))
    lines.extend(_source_lines_for_fields(prefix, config.timeframe, ("open", "volume")))
    lines.extend([
        f"{resistance} = ta.highest({high}[2], {prefix}_lookback)",
        f"{support} = ta.lowest({low}[2], {prefix}_lookback)",
        f"{setup_high} = {high}[1]",
        f"{setup_volume} = {volume}[1]",
        f"{avg_volume} = ta.sma({volume}[2], {prefix}_lookback)",
        f"{prefix}_currentRange = {high} - {low}",
        f"{close_position} = {prefix}_currentRange <= 0.0 ? 0.5 : ({close} - {low}) / {prefix}_currentRange",
        f"{prefix}_breakoutPct = {resistance} <= 0.0 ? 0.0 : math.max(0.0, {setup_high} / {resistance} - 1.0)",
        f"{prefix}_volumeRatio = {avg_volume} <= 0.0 ? 0.0 : {setup_volume} / {avg_volume}",
        f"{prefix}_rejectionPct = {close} <= 0.0 ? 0.0 : math.max(0.0, {resistance} / {close} - 1.0)",
        f"{prefix}_excessVolume = math.max(0.0, {prefix}_volumeRatio - {prefix}_volumeMultiplier)",
        f"{stop} = math.max({setup_high}, {high})",
        f"{target} = {support}",
        f"{prefix}_score = math.max(0.0, math.min(100.0, {prefix}_scoreFloor + {prefix}_breakoutPct * {prefix}_scoreBreakoutScale + {prefix}_rejectionPct * {prefix}_scoreRejectionScale + {prefix}_excessVolume * {prefix}_scoreVolumeScale))",
        f"{prefix}_shortSignal = {short_signal}",
        f'{prefix}_shortSignalKey = str.format("{{0}}|{_pine_string(layer)}|{_pine_string(config.module)}|short", syminfo.ticker)',
        f'plotshape({prefix}_shortSignal, title="{_pine_string(config.module)} Short", style=shape.triangledown, location=location.abovebar, color=color.red, text="S")',
        f'if {prefix}_shortSignal',
        f'    alert(str.format("{{0}},{{1}},{{2}},{{3}},{{4}},{{5}}", {prefix}_shortSignalKey, str.tostring(time), str.tostring({close}), str.tostring({stop}), str.tostring({target}), str.tostring({prefix}_score)), alert.freq_once_per_bar_close)',
    ])
    return lines


def _source_lines(prefix: str, timeframe: str) -> list[str]:
    if timeframe:
        frame = _pine_string(timeframe)
        return [
            f'{prefix}_high = request.security(syminfo.tickerid, "{frame}", high)',
            f'{prefix}_low = request.security(syminfo.tickerid, "{frame}", low)',
            f'{prefix}_close = request.security(syminfo.tickerid, "{frame}", close)',
        ]
    return [
        f"{prefix}_high = high",
        f"{prefix}_low = low",
        f"{prefix}_close = close",
    ]


def _source_lines_for_fields(prefix: str, timeframe: str, fields: Sequence[str]) -> list[str]:
    lines = []
    for field in fields:
        if timeframe:
            lines.append(f'{prefix}_{field} = request.security(syminfo.tickerid, "{_pine_string(timeframe)}", {field})')
        else:
            lines.append(f"{prefix}_{field} = {field}")
    return lines


def _pine_identifier(value: str) -> str:
    chars = [char if char.isalnum() else "_" for char in value]
    identifier = "".join(chars).strip("_") or "module"
    if identifier[0].isdigit():
        identifier = f"module_{identifier}"
    return identifier


def _pine_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _pine_float(value: float) -> str:
    return repr(float(value))


def _parity_example_configs() -> tuple[
    BreakoutSignalConfig,
    PullbackSignalConfig,
    MeanReversionSignalConfig,
    SweepReversalSignalConfig,
    CrashShortSignalConfig,
    FailedBounceSignalConfig,
    BullTrapSignalConfig,
]:
    return (
        BreakoutSignalConfig(lookback=3, allow_long=True, allow_short=False),
        PullbackSignalConfig(ema_length=3, stop_lookback=2, allow_long=True, allow_short=False),
        MeanReversionSignalConfig(lookback=4, std_mult=1.0, stop_lookback=2, allow_long=True, allow_short=False),
        SweepReversalSignalConfig(lookback=3, allow_long=True, allow_short=False),
        CrashShortSignalConfig(lookback=3, min_drop_pct=0.03, volume_multiplier=1.5, stop_lookback=1),
        FailedBounceSignalConfig(lookback=3, resistance_tolerance_pct=0.01, min_upper_wick_pct=0.3),
        BullTrapSignalConfig(lookback=3, volume_multiplier=1.5, weak_close_threshold=0.5),
    )


def _parity_example_vectors(*, symbol: str, configs: Sequence[Any] | None = None) -> list[PineGoldenVector]:
    vectors: list[PineGoldenVector] = []
    for module, bars in _parity_example_module_fixtures(configs):
        signals = SignalModuleRunner([module]).generate(bars, symbol)
        if len(signals) != 1:
            raise PineGenerationError(f"Parity example expected one signal from {module.name}, got {len(signals)}")
        signal = signals[0]
        entry_price = float(bars.iloc[-1]["Close"])
        vectors.append(PineGoldenVector(
            signal_key=f"{signal.symbol}|tactical|{signal.module}|{signal.direction.value}",
            bar_time=_pine_epoch_millis(bars.index[-1]),
            entry_price=entry_price,
            stop_price=signal.preferred_stop,
            target_price=signal.preferred_target,
            score=signal.score,
        ))
    return vectors


def _parity_example_module_fixtures(configs: Sequence[Any] | None = None) -> tuple[tuple[SignalModule, pd.DataFrame], ...]:
    selected_configs = tuple(configs) if configs is not None else _parity_example_configs()
    fixtures: list[tuple[SignalModule, pd.DataFrame]] = []
    for config in selected_configs:
        fixtures.append((_module_from_config(config), _parity_fixture_bars(config)))
    return tuple(fixtures)


def _module_from_config(config: Any) -> SignalModule:
    if isinstance(config, BreakoutSignalConfig):
        return BreakoutSignalModule(config)
    if isinstance(config, PullbackSignalConfig):
        return PullbackSignalModule(config)
    if isinstance(config, MeanReversionSignalConfig):
        return MeanReversionSignalModule(config)
    if isinstance(config, SweepReversalSignalConfig):
        return SweepReversalSignalModule(config)
    if isinstance(config, CrashShortSignalConfig):
        return CrashShortSignalModule(config)
    if isinstance(config, FailedBounceSignalConfig):
        return FailedBounceSignalModule(config)
    if isinstance(config, BullTrapSignalConfig):
        return BullTrapSignalModule(config)
    raise PineGenerationError(f"Unsupported Pine signal module config: {type(config).__name__}")


def _parity_fixture_bars(config: Any) -> pd.DataFrame:
    if isinstance(config, BreakoutSignalConfig):
        return _bars([
            (99.0, 100.0, 95.0, 98.0, 1000.0),
            (98.0, 101.0, 96.0, 100.0, 1000.0),
            (100.0, 102.0, 97.0, 101.0, 1000.0),
            (102.0, 106.0, 101.0, 105.0, 1300.0),
        ])
    if isinstance(config, PullbackSignalConfig):
        return _bars([
            (100.0, 102.0, 99.0, 101.0, 1000.0),
            (101.0, 104.0, 100.0, 103.0, 1000.0),
            (103.0, 106.0, 102.0, 105.0, 1000.0),
            (105.0, 106.0, 102.0, 103.0, 1000.0),
            (103.0, 108.0, 103.0, 107.0, 1000.0),
        ])
    if isinstance(config, MeanReversionSignalConfig):
        return _bars([
            (100.0, 101.0, 99.0, 100.0, 1000.0),
            (101.0, 102.0, 100.0, 101.0, 1000.0),
            (99.0, 100.0, 98.0, 99.0, 1000.0),
            (100.0, 101.0, 99.0, 100.0, 1000.0),
            (98.0, 100.0, 96.0, 99.5, 1000.0),
        ])
    if isinstance(config, SweepReversalSignalConfig):
        return _bars([
            (100.0, 103.0, 98.0, 101.0, 1000.0),
            (101.0, 104.0, 99.0, 102.0, 1000.0),
            (102.0, 105.0, 100.0, 103.0, 1000.0),
            (99.0, 104.0, 97.0, 100.0, 1000.0),
        ])
    if isinstance(config, CrashShortSignalConfig):
        return _bars([
            (100.0, 102.0, 99.0, 101.0, 1000.0),
            (101.0, 103.0, 100.0, 102.0, 1000.0),
            (102.0, 104.0, 101.0, 103.0, 1000.0),
            (101.0, 102.0, 95.0, 97.0, 2000.0),
        ])
    if isinstance(config, FailedBounceSignalConfig):
        return _bars([
            (100.0, 102.0, 96.0, 99.0, 1000.0),
            (99.0, 103.0, 97.0, 101.0, 1000.0),
            (101.0, 104.0, 98.0, 102.0, 1000.0),
            (102.0, 104.0, 100.0, 101.0, 1000.0),
            (101.0, 102.0, 98.0, 99.0, 1000.0),
        ])
    if isinstance(config, BullTrapSignalConfig):
        return _bars([
            (100.0, 102.0, 96.0, 99.0, 1000.0),
            (99.0, 103.0, 97.0, 101.0, 1000.0),
            (101.0, 104.0, 98.0, 102.0, 1000.0),
            (102.0, 106.0, 101.0, 105.0, 2000.0),
            (104.0, 105.0, 99.0, 101.0, 1300.0),
        ])
    raise PineGenerationError(f"Unsupported Pine signal module config: {type(config).__name__}")


def _bars(rows: Sequence[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    index = pd.date_range("2026-06-01T00:00:00Z", periods=len(rows), freq="4h")
    return pd.DataFrame(rows, columns=("Open", "High", "Low", "Close", "Volume"), index=index)


def _pine_epoch_millis(timestamp: Any) -> str:
    return str(int(pd.Timestamp(timestamp).timestamp() * 1000))


def _pine_observation_csv(vectors: Sequence[PineGoldenVector]) -> str:
    lines = ["signal_key,bar_time,entry_price,stop_price,target_price,score"]
    for vector in vectors:
        lines.append(",".join([
            vector.signal_key,
            vector.bar_time,
            _csv_float(vector.entry_price),
            _csv_optional_float(vector.stop_price),
            _csv_optional_float(vector.target_price),
            _csv_float(vector.score),
        ]))
    return "\n".join(lines) + "\n"


def _csv_optional_float(value: float | None) -> str:
    return "" if value is None else _csv_float(value)


def _csv_float(value: float) -> str:
    return repr(float(value))

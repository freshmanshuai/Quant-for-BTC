# Generic Trading Signal Platform Migration

This project is moving from a BTC-specific strategy collection toward a generic trading signal research and alerting platform.

## Target Architecture

The long-term platform should separate these concerns:

- `AssetSpec` / `MarketSpec`: exchange-aware asset metadata, tradability constraints, fees, contract multiplier, sessions, shorting and leverage support.
- `DataConnector`: vendor and exchange adapters such as Binance, Bybit, OKX, Yahoo Finance, Polygon, Alpha Vantage, local CSV, and databases.
- `BarStore` / `FeatureStore`: normalized storage for OHLCV, funding, open interest, turnover, order book, macro, and on-chain data. Parquet is the first target format; SQLite, DuckDB, or PostgreSQL can follow.
- `FeatureEngine`: registered feature modules for indicators, price action, funding, open interest, and on-chain features.
- `RegimeModel`: asset-specific regime profiles, replacing BTC-only assumptions such as EMA169 and 24/7 trading.
- `SignalModule`: standardized strategy modules that emit `Signal` objects rather than place trades directly.
- `RiskEngine`: position sizing, leverage, correlation exposure, drawdown controls, circuit breakers, and portfolio risk budgets.
- `PortfolioEngine`: multi-symbol, multi-layer, multi-position state management.
- `SignalDelivery`: dashboard, REST API, webhook, Telegram, email, and generated or verified TradingView Pine outputs.

## Current State

- BTC-specific logic still lives mainly in `quant_btc/strategy.py`.
- CCXT data fetching lives in `quant_btc/data.py`.
- Visualization lives under `serve/`.
- Valuescan AI tracking is implemented as a dashboard module and can be normalized into external metric frames for research features, cached through the external metric store, but it still does not feed existing trading signals.
- The new `quant_platform/` package now defines the first generic contracts:
  - `AssetSpec`
  - `MarketSpec`
  - `MarketCatalog`
  - `BarSeriesId`
  - `DerivativeSeriesId`
  - `ExternalMetricSeriesId`
  - `FeatureSeriesId`
  - `DataConnector`
  - `Direction`
  - `FeatureEngine`
  - `RegimeModel`
  - `SignalModule`
  - `Signal`
  - `RiskEngine`
  - `RiskLimits`
  - `RiskState`
  - `RiskDecision`
  - `PortfolioEngine`
  - `PortfolioState`
  - `Position`
  - `PortfolioOrder`
  - `OrderStatus`
  - `DeliveryPayload`
  - `DeliveryResult`
  - `PineGoldenVector`
  - `SignalPipeline`

## Migration Phases

### Phase 1: Generic Contracts

Status: started.

Goals:

- Establish reusable platform schemas without changing existing BTC behavior.
- Keep all BTC backtests and dashboard behavior intact.
- Add tests that define the new contracts.

Implemented:

- `quant_platform/core.py`
- `quant_platform/data.py`
- `quant_platform/connectors.py`
- `quant_platform/signals.py`
- `tests/test_platform_core.py`
- `MarketSpec.quantize_price()` and `MarketSpec.quantize_quantity()` normalize prices and quantities to exchange tick/lot steps before downstream risk or portfolio code builds orders.

### Phase 2: Data Adapter Boundary

Status: started.

Move Binance/BinanceUS fetching into a `DataConnector` implementation while keeping `quant_btc.data.fetch_ohlcv()` as a compatibility wrapper. This creates a clean adapter boundary before replacing pickle cache behavior.

Implemented:

- `quant_platform/connectors_ccxt.py`
- `quant_platform/connectors_csv.py`
- `quant_platform/connectors_sqlite.py`
- `tests/test_platform_ccxt_connector.py`
- `tests/test_platform_csv_connector.py`
- `tests/test_platform_sqlite_connector.py`
- `tests/test_quant_btc_data_adapter.py`
- `DataConnectorRegistry`
- OHLCV fetching now goes through `CcxtExchangeConnector.fetch_bars()`.
- Funding rate and open-interest fetching now goes through `CcxtExchangeConnector.fetch_derivatives()`.
- `CcxtExchangeConnector` can be imported in offline test environments without requiring `ccxt`; the package is required only when the default live exchange factory is used.
- `LocalCsvConnector` can load local OHLCV CSV files into the same normalized `Open`, `High`, `Low`, `Close`, `Volume` schema with UTC timestamps, date filtering, and limit support.
- `SQLiteBarConnector` can load local SQLite OHLCV tables into the same normalized bar schema, including optional timeframe filtering for database-backed research datasets.
- `DataConnectorRegistry` can route bar requests by named source so research scripts and dashboard/API flows do not need to hardcode adapter selection.
- `DataConnectorRegistry` can also route optional derivative data requests for funding and open interest, while bar-only connectors report unsupported derivative data explicitly.
- `quant_btc.data.fetch_ohlcv()` and `quant_btc.data.fetch_derivative_data()` remain as compatibility wrappers.

Remaining:

- Add vendor adapters beyond CCXT and local CSV/SQLite when needed.

### Phase 3: Storage Boundary

Status: started.

Introduce a Parquet-backed `BarStore` with deterministic cache keys from `BarSeriesId`. Existing pickle files can remain for compatibility until backtest flows are migrated.

Implemented:

- `quant_platform/stores.py`
- `tests/test_platform_store.py`
- `tests/test_platform_feature_store.py`
- `FeatureSeriesId`
- `ExternalMetricSeriesId`
- `ParquetFeatureStore`
- `ParquetExternalMetricStore`
- `ParquetDerivativeStore`
- `SQLiteBarStore`
- `SQLiteDerivativeStore`
- `SQLiteExternalMetricStore`
- `SQLiteFeatureStore`
- `pyarrow>=15.0` declared in `requirements.txt`
- `quant_btc.data.fetch_ohlcv()` reads `ParquetBarStore` before the legacy pickle cache.
- Remote OHLCV fetches write to `ParquetBarStore` and still write pickle files as a migration fallback.
- Derivative funding/open-interest fetches read from `ParquetDerivativeStore` before legacy pickle cache, and remote fetches write both the Parquet derivative store and legacy pickle cache as a migration fallback.
- Derived feature sets can now be persisted through `ParquetFeatureStore` using deterministic paths keyed by symbol, exchange, market type, timeframe, source, and feature set.
- `FeatureEngine` runs can now use `run_feature_engine_with_cache()` to persist output through any `FeatureStore` writer while returning the same feature frame for downstream logic.
- External metric frames such as Valuescan AI tracking data can now be persisted through `ParquetExternalMetricStore` using deterministic paths keyed by source, provider, symbol, timeframe, and dataset.
- `SQLiteBarStore` provides a no-extra-dependency OHLCV storage backend keyed by `BarSeriesId`, preserving UTC timestamps and standard `Open`, `High`, `Low`, `Close`, `Volume` columns for research workflows that prefer SQLite over Parquet files.
- `SQLiteDerivativeStore` provides a no-extra-dependency derivatives storage backend keyed by `DerivativeSeriesId`, preserving UTC timestamps and funding/open-interest columns for research workflows that prefer SQLite over Parquet files.
- `SQLiteExternalMetricStore` provides a no-extra-dependency external metric storage backend keyed by `ExternalMetricSeriesId`, preserving UTC timestamps and arbitrary provider metric columns for Valuescan, macro, on-chain, or sentiment research workflows.
- `SQLiteFeatureStore` provides a no-extra-dependency feature storage backend keyed by `FeatureSeriesId`, preserving UTC timestamps and arbitrary feature columns for research workflows that prefer SQLite over Parquet files.

Remaining:

- Decide when to remove legacy pickle cache compatibility after existing workflows have migrated.

### Phase 4: Feature Modules

Status: started.

Split feature calculation out of `quant_btc/strategy.py` into registered modules. Start with indicator-only features, then move regime and module scores.

Implemented:

- `quant_platform/features.py`
- `serve/valuescan_metrics.py`
- `FeatureEngine`
- `TechnicalIndicatorModule`
- `DonchianFeatureModule`
- `VolumeFeatureModule`
- `VolatilityFeatureModule`
- `BollingerFeatureModule`
- `PriceActionFeatureModule`
- `DerivativesFeatureModule`
- `ExternalMetricFeatureModule`
- `tests/test_platform_features.py`
- `quant_btc/feature_engine.py`
- `quant_btc.strategy.prepare_features()` now uses a BTC compatibility feature engine for EMA, MACD, higher-timeframe EMA, RSI, ATR, ADX, Donchian, Bollinger, volume z-score, and candle shadow columns.
- The BTC compatibility feature engine now exposes a deterministic `btc_compat_v1` `FeatureSeriesId` and `build_cached_btc_features()` wrapper for optional `ParquetFeatureStore` persistence.
- The dashboard signal preview default feature builder now attempts to cache BTC compatibility `FeatureEngine` output under `data/features` before continuing through the existing `prepare_features()` path, so cached features do not change trading signal behavior.
- Funding/open-interest data now has a platform feature module that aligns derivative series to bar timestamps and adds funding z-score, open-interest change, and derivative price-change columns without mutating input bars.
- `quant_btc.strategy.compute_derivative_bonus()` now consumes `DerivativesFeatureModule` output for BTC derivative bonus scoring, keeping the legacy crowded-long, deleveraging, crowded-short, and short-cover rules in the BTC compatibility layer.
- External metrics such as Valuescan social sentiment, AI risk scores, on-chain values, macro series, or order-book derived metrics can now be aligned into bars through `ExternalMetricFeatureModule` using stable prefixed feature columns.
- Valuescan overview and AI list payloads can now be converted into timestamp-indexed external metric frames and aligned to OHLCV bars through `serve.valuescan_metrics` without exposing API credentials or changing existing trading signals.
- Valuescan research feature previews are exposed through `/api/valuescan/ai/features` and rendered in the AI Tracking dashboard as read-only `valuescan_*` feature rows.
- `/api/valuescan/ai/features` now attempts to cache normalized Valuescan AI tracking metrics under `data/external_metrics` and returns cache metadata in the preview payload; cache failures are reported as route errors metadata instead of changing or blocking trading signals.

Remaining:

- Move remaining regime helper columns and module-specific execution permissions out of `quant_btc.strategy`.
- Extend `ParquetFeatureStore` reads into research and preview paths once cache invalidation/versioning policy is defined.

### Phase 5: Regime Model

Status: started.

Move market state classification out of strategy classes and into asset-specific regime profiles. BTC keeps its current numeric labels for compatibility: Ranging `0`, Bull `1`, Bear `2`, Compression `3`, HighRisk `4`.

Implemented:

- `quant_platform/regimes.py`
- `RegimeProfile`
- `RegimeProfileRegistry`
- `RegimeModel`
- `RegimeLabel`
- `load_regime_profile_registry_json`
- `tests/test_platform_regimes.py`
- `RegimeProfileRegistry` can select symbol-specific profiles first, then exchange/market-type profiles, then a default profile, so non-BTC assets can use different trend lengths and higher-timeframe rules without changing BTC compatibility behavior.
- `config/regime_profiles.json` defines a project-level default profile plus a NASDAQ equity profile, and `load_regime_profile_registry_json()` loads those settings into `RegimeProfileRegistry` so non-BTC regime assumptions no longer need to be hardcoded.
- The signal preview service now exposes `resolve_regime_profile(market)` backed by `config/regime_profiles.json`, matching the generic market-spec resolver and giving research/preview flows a non-BTC regime profile boundary.
- Generic research previews now pass the resolved non-BTC `RegimeProfile` into injected feature and signal builders before running standardized signals through `SignalPipeline`.
- `quant_btc/regime_model.py`
- `quant_btc.strategy.BaseRiskStrategy.init()` now delegates BTC regime classification to `build_btc_regime_model()`.
- `btc_regime_entry_gate()` owns the BTC compatibility entry-permission rules for default pullback, breakout, and mean-reversion strategy modes, while strategy classes delegate to it for compatibility.

Remaining:

- Move remaining dual-layer execution permissions out of strategy classes.

### Phase 6: Signal Modules

Status: started.

Move Breakout, Pullback, Mean Reversion, Sweep Reversal, Crash Short, Failed Bounce, Bull Trap, and related modules into independent `SignalModule` implementations that produce standardized `Signal` objects.

Implemented:

- `quant_platform/signal_modules.py`
- `SignalModule`
- `ColumnSignalModule`
- `SignalModuleRunner`
- `tests/test_platform_signal_modules.py`
- `quant_btc/signal_modules.py`
- `build_btc_signal_modules()` maps existing Breakout, Pullback, Mean Reversion, Sweep Reversal, Crash Short, Failed Bounce, and Bull Trap feature columns into standardized `Signal` output without changing current backtest behavior.
- `add_btc_signal_predicate_columns()` owns the existing Breakout, Pullback, and Mean Reversion boolean predicate columns previously computed inside `prepare_features()`.
- `add_btc_module_score_columns()` owns the BTC module score columns, price-action bonus helper columns, derivative placeholder columns, and standardized gates previously computed inside `quant_btc.strategy._add_score_columns()`.
- `add_btc_sweep_signal_columns()` owns the Sweep Reversal standardized boolean gates derived from support/resistance reclaim columns.
- `add_btc_sweep_score_columns()` owns the Sweep Reversal score computation and standardized boolean gates while preserving the legacy BTC compatibility columns.
- `add_btc_score_signal_columns()` owns the Crash Short standardized boolean gate derived from score columns.
- `add_btc_crash_score_columns()` owns the Crash Short score computation, DMI helper columns, late-chase gate, and standardized boolean gate while preserving the legacy BTC compatibility columns.
- `add_btc_preferred_exit_columns()` adds preview-only ATR-based preferred stop/target columns so standardized BTC signals can flow through `RiskEngine` without changing legacy trade execution.
- `add_btc_short_extension_signal_columns()` owns the Failed Bounce and Bull Trap standardized boolean gates derived from existing BTC feature columns.
- `add_btc_short_extension_score_columns()` owns the Failed Bounce and Bull Trap score computation and standardized boolean gates while preserving the legacy BTC compatibility columns.
- `generate_btc_standard_signals()` converts prepared BTC compatibility columns into serializable standardized `Signal` objects for preview/API consumers.
- `ColumnSignalModule` can now carry optional `preferred_stop` and `preferred_target` values from feature columns into standardized `Signal` objects.
- BTC 15m MTF confirmation helpers for sweep/reclaim, no-new-extreme, and higher-low checks now live in `quant_btc.signal_modules`, while `DualLayerStrategy` only selects the current 4H window.

Remaining:

- Replace the compatibility column adapter with modules that compute signals directly from required feature columns.
- Feed standardized signals into RiskEngine and PortfolioEngine instead of strategy classes reading boolean columns directly.

### Phase 7: Risk Engine

Status: started.

Move position sizing, circuit breakers, loss-streak controls, and portfolio risk budget gates into a platform layer that consumes standardized `Signal` objects.

Implemented:

- `quant_platform/risk.py`
- `quant_btc/risk_model.py`
- `AccountState`
- `RiskLimits`
- `RiskState`
- `RiskDecision`
- `RiskEngine`
- `tests/test_platform_risk.py`
- `tests/test_btc_risk_model.py`
- Risk decisions now cover stop-distance sizing, max notional caps, daily/weekly drawdown gates, total portfolio risk budget gates, per-symbol risk gates, per-module risk gates, correlation-group risk gates, flat/missing-stop blocking, consecutive-loss size reduction, and pause windows.
- `RiskEngine` can now consume `markets_by_symbol` and apply `MarketSpec.supports_short` / `MarketSpec.supports_leverage` permissions, blocking unsupported short signals and capping non-leveraged markets at unlevered notional exposure.
- `RiskLimits.max_symbol_risk` and `RiskLimits.max_module_risk` let the platform cap concentration in one instrument or one signal family, and `SignalPipeline` passes symbol/module open risk from `PortfolioState`.
- `RiskLimits.correlation_groups` and `RiskLimits.max_correlation_group_risk` let the platform cap related-symbol exposure, and `SignalPipeline` passes group-level open risk from `PortfolioState`.
- BTC single-module stop-distance sizing now lives in `quant_btc.risk_model.calculate_btc_base_position_size()`, preserving max-position caps, consecutive-loss size reduction, HTF conflict half sizing, and bear-short discounts while `BaseRiskStrategy` delegates to it.
- BTC tactical module risk percentages and legacy stop-distance position sizing now live in `quant_btc.risk_model.calculate_btc_tactical_position_size()`, while the dual-layer compatibility strategy delegates to it instead of hardcoding module risk maps in `Strategy.next()`.
- BTC dual-layer regime-dependent size adjustment now lives in `quant_btc.risk_model.btc_dual_layer_regime_size_multiplier()`, preserving the weak-bull/transition half-sizing rule while `DualLayerStrategy` keeps only market state reads.

Remaining:

- Wire BTC strategy compatibility classes to consume `RiskEngine` decisions without changing historical signal behavior.
- Add richer portfolio diagnostics for risk-budget usage by symbol, module, and correlation group.

### Phase 8: Portfolio Engine

Status: started.

Add multi-symbol, multi-layer, multi-position state management after standardized signals and risk decisions are available.

Implemented:

- `quant_platform/portfolio.py`
- `quant_btc/portfolio_model.py`
- `PositionKey`
- `Position`
- `PortfolioState`
- `PortfolioOrder`
- `OrderStatus`
- `PortfolioPlan`
- `PortfolioEngine`
- `quant_platform/backtest.py`
- `BacktestAttribution`
- `BacktestAttributionBucket`
- `BacktestStep`
- `BacktestExecutionConfig`
- `BacktestEquityPoint`
- `BacktestStateSnapshot`
- `EventDrivenBacktest`
- `EventDrivenBacktestResult`
- `BacktestTrade`
- `tests/test_platform_portfolio.py`
- `tests/test_platform_backtest.py`
- `tests/test_btc_portfolio_model.py`
- Portfolio planning now consumes `RiskDecision` objects, opens multiple symbols, tracks open risk, supports module-to-layer mapping, allows core/tactical layers for the same symbol, resolves same-layer conflicts by signal score, ignores risk-blocked decisions, and blocks cross-layer hedging by default.
- `PortfolioEngine` can now consume `markets_by_symbol` and quantize planned order quantities plus entry/stop/target prices through each symbol's `MarketSpec` tick and lot constraints before positions enter `PortfolioState`.
- `PortfolioOrder` now carries planned entry, stop, and target prices so dashboard/API delivery can show the normalized order plan instead of only the quantity and execution state.
- Portfolio orders now track submitted, partially filled, filled, canceled, and rejected lifecycle states.
- Filled open orders now propagate average fill price back into `PortfolioState` positions, so later accounting uses execution prices rather than planned prices.
- `PortfolioEngine.close_position()` supports full closes and partial reduces, emits filled close orders, and updates or removes the corresponding position.
- BTC layer close portion calculation now lives in `quant_btc.portfolio_model`, preserving aggregate-position close fractions for core, bear-core, and tactical layer exits while `DualLayerStrategy` keeps order execution side effects.
- BTC external full-close state cleanup now lives in `quant_btc.portfolio_model`, preserving the legacy core/tactical reset and trade-recording trigger while `DualLayerStrategy` keeps PnL accounting side effects.
- BTC core exit state cleanup now lives in `quant_btc.portfolio_model`, preserving core layer close sizing and core state reset while `DualLayerStrategy` keeps close execution side effects.
- BTC tactical exit close action planning now lives in `quant_btc.portfolio_model`, preserving the partial-vs-full close branch for tactical layer exits while `DualLayerStrategy` keeps order execution side effects.
- BTC tactical exit state cleanup now lives in `quant_btc.portfolio_model`, preserving tactical direction and size reset while `DualLayerStrategy` keeps close execution side effects.
- BTC base partial take-profit and time-stop triggers now live in `quant_btc.portfolio_model`, preserving legacy R-multiple calculations while `BaseRiskStrategy` keeps position state reads and close side effects.
- BTC base entry direction resolution now lives in `quant_btc.portfolio_model`, preserving HighRisk blocking, regime gate permissions, score thresholds, and daily/weekly trend conflict resolution while `BaseRiskStrategy` keeps feature reads and order execution.
- BTC base entry plan validation now lives in `quant_btc.portfolio_model`, preserving stop-distance, fixed-target reward/risk, minimum-size guards, and initial entry state while `BaseRiskStrategy` keeps position sizing and order execution side effects.
- BTC base invalidation exits now live in `quant_btc.portfolio_model`, preserving no-profit timeout, ATR spike, and dual-timeframe reversal rules while `BaseRiskStrategy` keeps market state reads and close side effects.
- BTC base trailing stop updates and hit checks now live in `quant_btc.portfolio_model`, preserving breakeven, activation, breakout-mode multipliers, and one-way stop ratcheting while `BaseRiskStrategy` keeps market state reads and close side effects.
- BTC HTF swing stop/target planning now lives in `quant_btc.portfolio_model`, preserving daily high/low stop caps, fixed 1:2 target projection, and invalid stop rejection while `HTFStopStrategy` keeps market state reads.
- BTC ATR/HTF stop/target planning now lives in `quant_btc.portfolio_model`, preserving regime-specific ATR multipliers, daily high/low stop caps, and invalid stop/target rejection while `ATRHTFStopStrategy` keeps market state reads.
- BTC breakout initial stop planning now lives in `quant_btc.portfolio_model`, preserving long/short ATR stop multipliers, daily high/low stop caps, no-fixed-target semantics, and invalid stop rejection while `BreakoutStrategy` keeps market state reads.
- BTC mean-reversion stop/target planning now lives in `quant_btc.portfolio_model`, preserving ATR stop distance, BB-mid/EMA55 target selection, 2-ATR target cap, and invalid stop/target rejection while `MeanRevStrategy` keeps market state reads.
- BTC tactical stop/target planning now lives in `quant_btc.portfolio_model`, preserving regime-specific ATR multipliers, daily high/low stop caps, and invalid stop/target rejection while `DualLayerStrategy` keeps market data access and order execution side effects.
- BTC short partial take-profit planning now lives in `quant_btc.portfolio_model`, preserving module-specific TP1/TP2 thresholds, close portions, and TP state transitions while `DualLayerStrategy` keeps order execution side effects.
- BTC breakout extra-exit rules now live in `quant_btc.portfolio_model`, preserving Donchian-20 reverse exits and EMA144 two-bar confirmation exits while `BreakoutStrategy` keeps current/previous bar data reads.
- BTC core long compatibility rules for entry, trend-failure exit, ATR trailing stop, pullback add-on signal, and pullback add-on sizing/state planning now live in `quant_btc.portfolio_model`, while `DualLayerStrategy` delegates to those helpers and keeps its historical state variables.
- BTC core long entry state planning now lives in `quant_btc.portfolio_model`, preserving core activation, entry/highest-close snapshots, configured core size, daily trend counter reset, equity snapshot, order tag, and last-trade bar while `DualLayerStrategy` keeps order execution side effects.
- BTC flash-crash dip-buy activation/recovery state now lives in `quant_btc.portfolio_model`, preserving the legacy rapid-drop, ATR-expansion, recovery, and timeout thresholds while `DualLayerStrategy` keeps order execution side effects.
- BTC bear core compatibility rules for stop placement and trend/ATR exits now live in `quant_btc.portfolio_model`, while `DualLayerStrategy` delegates to those helpers and keeps its historical state variables.
- BTC bear-core stage-1 probe and stage-2 confirmation signal permissions now live in `quant_btc.portfolio_model`, preserving the legacy daily/weekly bearish filters while `DualLayerStrategy` keeps market state reads and order execution side effects.
- BTC bear-core V-reversal snapback exit now lives in `quant_btc.portfolio_model`, preserving peak-R, current-R, holding-window, regime, and daily-trend guards while `DualLayerStrategy` keeps layer close and trade-accounting side effects.
- BTC bear-core V-reversal exit state cleanup now lives in `quant_btc.portfolio_model`, preserving layer close sizing, bear-core deactivation, waterfall flag reset, and daily trend counter reset while `DualLayerStrategy` keeps close execution and PnL accounting.
- BTC bear-core giveback exit state cleanup now lives in `quant_btc.portfolio_model`, preserving layer close sizing and bear-core deactivation while `DualLayerStrategy` keeps short giveback guard evaluation, close execution, and PnL accounting.
- BTC bear-core waterfall runner giveback exit now lives in `quant_btc.portfolio_model`, preserving stage-99, stop-distance, lock-R, and current-R rules while `DualLayerStrategy` keeps layer close and waterfall state cleanup side effects.
- BTC bear-core waterfall runner exit state cleanup now lives in `quant_btc.portfolio_model`, preserving layer close sizing, bear-core deactivation, tactical-size reset, waterfall flag reset, and daily trend counter reset while `DualLayerStrategy` keeps close execution and PnL accounting.
- BTC bear-core trend-exit state cleanup now lives in `quant_btc.portfolio_model`, preserving layer close sizing, bear-core deactivation, tactical-size reset, and daily trend counter reset while `DualLayerStrategy` keeps close execution and PnL accounting.
- BTC flash-crash dip-buy tactical entry planning now lives in `quant_btc.portfolio_model`, preserving core-active gating, one-tactical-position gating, 10% add-on size, fixed 8% stop/target, and `dip_buy` module tagging while `DualLayerStrategy` keeps order execution side effects.
- BTC short giveback guard rules now live in `quant_btc.portfolio_model`, preserving the legacy peak-R state update and tiered giveback thresholds for tactical shorts and bear-core exits.
- BTC short extra-exit rules now live in `quant_btc.portfolio_model`, preserving crash DC10-high reversal exits and pullback/failed-bounce/bull-trap DC20-low target exits while `DualLayerStrategy` keeps rolling-window data access.
- BTC short tactical time-stop rules now live in `quant_btc.portfolio_model`, preserving module-specific timeout windows and the reached-1R state transition while `DualLayerStrategy` keeps order execution side effects.
- BTC tactical entry state planning now lives in `quant_btc.portfolio_model`, preserving the reward/risk gate, direction selection, order tag, and legacy state defaults while `DualLayerStrategy` keeps order execution side effects.
- BTC tactical hard stop/target exit checks now live in `quant_btc.portfolio_model`, preserving long/short SL/TP hit semantics while `DualLayerStrategy` keeps order execution side effects.
- BTC tactical ATR trailing-stop state updates now live in `quant_btc.portfolio_model`, preserving long/short extreme tracking and stop ratcheting while `DualLayerStrategy` keeps order execution side effects.
- BTC bear-core waterfall profit guard decisions now live in `quant_btc.portfolio_model`, returning explicit close fraction, lock-R, and next-stage actions while `DualLayerStrategy` keeps order execution side effects.
- BTC bear-core probe peak-R tracking now lives in `quant_btc.portfolio_model`, preserving the max favorable excursion state update while `DualLayerStrategy` keeps order execution side effects.
- BTC bear-core stage-1 probe and group gate planning now lives in `quant_btc.portfolio_model`, returning explicit probe size and group tracking updates while `DualLayerStrategy` keeps order execution side effects.
- BTC bear-core stage-1 probe entry state planning now lives in `quant_btc.portfolio_model`, preserving activation, stage, entry snapshots, probe/giveback peak resets, group tracking, daily trend counter reset, equity snapshot, and last-trade bar while `DualLayerStrategy` keeps short order execution.
- BTC bear-core stage-2 confirm add and stage-3 acceleration add planning now live in `quant_btc.portfolio_model`, returning explicit add sizes, target sizes, group exposure, and next stage while `DualLayerStrategy` keeps order execution side effects.
- BTC bear-core stage-2 confirm add state planning now lives in `quant_btc.portfolio_model`, preserving target size, group exposure, stage, and last-trade-bar updates while `DualLayerStrategy` keeps short add execution.
- BTC bear-core stage-3 acceleration add state planning now lives in `quant_btc.portfolio_model`, preserving target size, group exposure, and stage updates while `DualLayerStrategy` keeps short add execution.
- BTC core pullback add state planning now lives in `quant_btc.portfolio_model`, preserving core size and fully-loaded updates while `DualLayerStrategy` keeps long add execution.
- `SignalPipeline` can route standardized `SignalModule` output through `RiskEngine`, `PortfolioEngine`, and delivery channels.
- `SignalPipeline` can consume one shared `markets_by_symbol` map and propagate the same `MarketSpec` constraints into `RiskEngine` and `PortfolioEngine`, so standard API/backtest paths apply short/leverage gates and tick/lot order normalization without duplicate wiring.
- `MarketCatalog` can register and resolve `MarketSpec` objects by symbol, exchange, and market type, and the platform default crypto catalog now exposes the BTC/USDT Binance swap spec used by compatibility previews.
- `MarketCatalog` can now build from and export plain configuration records, giving future exchange/asset specs a data-driven path before adding JSON, database, or admin UI storage.
- `load_market_catalog_json()` and `save_market_catalog_json()` can round-trip market specs through a `{"markets": [...]}` JSON file, so exchange/asset configuration can move out of Python code incrementally.
- `config/markets.json` now stores the default BTC/USDT Binance swap market spec, and BTC dashboard/API previews load this project config before falling back to the built-in default catalog.
- The signal preview service now has a generic `resolve_market_spec(symbol, exchange, market_type)` helper backed by the project market catalog; the BTC helper delegates to it, and `config/markets.json` includes a non-BTC equity example to keep the path asset-agnostic.
- The BTC dashboard/API `SignalPipeline` and event-driven backtest previews now consume the platform default BTC swap `MarketSpec` and pass it through the standard pipeline/backtest path, keeping legacy signal generation untouched while normalizing preview orders through platform market constraints.
- `EventDrivenBacktest` can run a standardized `SignalPipeline` over multiple symbol feature streams in global timestamp order, collect signals, risk decisions, portfolio orders, delivery results, fill submitted open orders with configurable slippage at the current bar close, close positions on stop/target, record realized trades, record portfolio state history after each event, subtract fees, and produce an equity curve with realized and unrealized PnL.
- `EventDrivenBacktest` can now consume `markets_by_symbol` so per-symbol `MarketSpec.fee_rate`, `MarketSpec.funding_rate`, and `MarketSpec.contract_multiplier` are reflected in fees, funding, realized PnL, and unrealized PnL.
- `EventDrivenBacktestResult.attribution` summarizes realized trade count, gross PnL, net PnL, fees, and win rate by symbol, layer, and signal module.

Remaining:

- Add rebalance actions, more realistic partial fill simulation, and broader portfolio analytics beyond realized trade attribution.
- Migrate BTC historical backtest execution from strategy-class boolean reads to the event-driven `SignalPipeline` harness without changing compatibility results.

### Phase 9: Signal Delivery

Status: started.

Signal delivery can target dashboard, REST, webhook, Telegram, email, and TradingView outputs using one signal source of truth.

Implemented:

- `quant_platform/delivery.py`
- `DeliveryPayload`
- `DeliveryResult`
- `InMemoryDeliveryChannel`
- `WebhookDeliveryChannel`
- `TelegramDeliveryChannel`
- `EmailDeliveryChannel`
- `PineGoldenVector`
- `compare_pine_golden_vectors()`
- `SignalPipeline`
- `tests/test_platform_delivery.py`
- `tests/test_platform_pipeline.py`
- `serve/signal_preview.py`
- `/api/signals/preview`
- `/api/signals/pipeline-preview`
- `tests/test_signal_preview_service.py`
- `tests/test_signal_preview_routes.py`
- `serve/static/js/pipeline.js`
- `tests/test_signal_pipeline_frontend.py`
- Delivery payloads now serialize standardized `Signal`, `RiskDecision`, and `PortfolioOrder` data for dashboard/API use.
- Webhook, Telegram, and email channels use injected transports so delivery is testable without hardcoded network credentials.
- Pine golden vectors can be generated from platform orders to support future Python/Pine signal consistency checks.
- Pine observations exported from TradingView can now be compared against platform `PineGoldenVector` rows with field-level mismatch messages for entry, stop, target, and score.
- Standardized signal output can now be passed through risk, portfolio, and delivery layers in one platform pipeline.
- The visualization server now exposes a read-only BTC standardized signal preview REST endpoint without changing trade execution.
- BTC standardized preview signals now include preferred stop/target values and have focused coverage showing they can pass through `RiskEngine`, `PortfolioEngine`, and in-memory dashboard delivery.
- The visualization server now also exposes a read-only BTC `SignalPipeline` preview REST endpoint with serialized signals, risk decisions, portfolio orders, and dashboard delivery payloads.
- `get_signal_research_preview()` provides a generic read-only preview entry point that resolves configured `MarketSpec` and `RegimeProfile` records, accepts injectable OHLCV/feature/signal builders, and routes resulting standardized signals through `RiskEngine`, `PortfolioEngine`, and dashboard delivery.
- `/api/signals/research-preview` exposes the generic preview boundary with `symbol`, `exchange`, and `market_type` parameters while leaving existing BTC-specific preview routes intact.
- The `SignalPipeline` dashboard now renders normalized portfolio order entry, stop, and target prices from the REST payload, making `MarketSpec` tick/lot effects visible in the frontend.
- The visualization server now exposes a read-only BTC event-driven backtest preview REST endpoint that runs standardized signals through `SignalPipeline` and `EventDrivenBacktest`, returning equity curve, realized trades, summary, and attribution without replacing the legacy historical backtest.
- The visualization server now exposes a read-only BTC migration comparison endpoint that reports legacy cached summary/trade-log metrics beside event-driven preview metrics and deltas.
- The frontend now includes a read-only Signal Pipeline dashboard module that renders the pipeline preview API, event-driven backtest preview, and migration comparison deltas side-by-side without altering trade execution.

Remaining:

- Route live standardized signals and risk decisions into dashboard/API outputs.
- Back the generic research preview with configured non-BTC data connectors and direct-compute signal modules instead of only injected test builders.
- Migrate BTC compatibility flows to use `SignalPipeline` without changing historical signal behavior.
- Add production transport wiring and configuration for webhook, Telegram, and email.
- Generate TradingView Pine from Python configuration and wire exported Pine observations into the golden-vector comparison in CI.

## Invariants During Migration

- Existing BTC strategy behavior must remain runnable while contracts are added.
- New platform code must not import `quant_btc.strategy`.
- Signal modules should not own exchange fetching, storage, portfolio state, or delivery.
- Secrets must stay out of source files.

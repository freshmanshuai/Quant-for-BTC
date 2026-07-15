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
- `SignalDelivery`: generated or verified TradingView Pine outputs that stay consistent with Python signal configuration.

## Current State

- BTC-specific logic still lives mainly in `quant_btc/strategy.py`.
- CCXT data fetching lives in `quant_btc/data.py`.
- Visualization lives under `serve/`.
- Valuescan AI tracking is implemented as a dashboard module and can be normalized into external metric frames for research features, cached through the external metric store, and loaded by configured generic research feature runs; it still does not feed existing BTC trading signals.
- The new `quant_platform/` package now defines the first generic contracts:
  - `AssetSpec`
  - `MarketSpec`
  - `MarketCatalog`
  - `BarSeriesId`
- `DerivativeSeriesId`
- `ExternalMetricSeriesId`
- `OrderBookSeriesId`
- `FeatureSeriesId`
  - `DataConnector`
  - `Direction`
  - `FeatureEngine`
  - `RegimeModel`
  - `SignalModule`
  - `SignalModuleRegistry`
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
- `MarketSpec` now stores structured session metadata alongside the compatibility `trading_session` label: `session_timezone`, `session_open`, `session_close`, and `trading_days`. `MarketCatalog` JSON records round-trip those fields, giving non-24/7 assets an explicit market-hours description without embedding session assumptions in strategies.
- `MarketSpec.is_trading_time()` can now evaluate a UTC timestamp against the configured session timezone, trading days, and open/close hours, while `24/7` markets continue to accept all timestamps.
- `MarketSpec` now stores an optional `correlation_group`, and `MarketCatalog` JSON records round-trip it so multi-asset risk grouping can live with exchange/asset metadata instead of being duplicated at every RiskEngine call site.
- `MarketSpec` now stores optional `max_leverage`, and `MarketCatalog` JSON records round-trip it so leverage capability can live with exchange/asset metadata instead of being hardcoded in risk callers.
- The Signal Pipeline dashboard renders selected configured markets' session metadata and tradability constraints from `/api/signals/markets` in a Market Session feed, making base/quote asset identity, timezone, session hours, trading days, tick size, lot size, fee/funding rates, contract multiplier, short support, leverage support, and max leverage visible outside raw API responses.

### Phase 2: Data Adapter Boundary

Status: started.

Move Binance/BinanceUS fetching into a `DataConnector` implementation while keeping `quant_btc.data.fetch_ohlcv()` as a compatibility wrapper. This creates a clean adapter boundary before replacing pickle cache behavior.

Implemented:

- `quant_platform/connectors_ccxt.py`
- `quant_platform/connectors_csv.py`
- `quant_platform/connectors_sqlite.py`
- `quant_platform/connector_config.py`
- `tests/test_platform_ccxt_connector.py`
- `tests/test_platform_csv_connector.py`
- `tests/test_platform_sqlite_connector.py`
- `tests/test_platform_connector_config.py`
- `tests/test_quant_btc_data_adapter.py`
- `DataConnectorRegistry`
- OHLCV fetching now goes through `CcxtExchangeConnector.fetch_bars()`.
- Funding rate and open-interest fetching now goes through `CcxtExchangeConnector.fetch_derivatives()`.
- Single order-book snapshot fetching now goes through `CcxtExchangeConnector.fetch_order_book_snapshots()`, producing normalized bid/ask depth columns and best-spread values for the platform order-book store/cache boundary.
- `CcxtExchangeConnector` can be imported in offline test environments without requiring `ccxt`; the package is required only when the default live exchange factory is used.
- `LocalCsvConnector` can load local OHLCV CSV files into the same normalized `Open`, `High`, `Low`, `Close`, `Volume` schema with UTC timestamps, date filtering, and limit support.
- `SQLiteBarConnector` can load local SQLite OHLCV tables into the same normalized bar schema, including optional timeframe filtering for database-backed research datasets.
- `LocalCsvConnector` and `SQLiteBarConnector` now preserve optional `turnover` and common quote-volume source columns as standardized `Turnover`, allowing local research datasets to carry traded-value bars into BarStore/FeatureStore flows instead of dropping them at the adapter boundary.
- `LocalCsvConnector` and `SQLiteBarConnector` now accept explicit `column_map` configuration for Open, High, Low, Close, Volume, and Turnover source fields, so local vendor schemas can be normalized without changing connector code.
- `DataConnectorRegistry` can route bar requests by named source so research scripts and dashboard/API flows do not need to hardcode adapter selection.
- `DataConnectorRegistry` can also route optional derivative data requests for funding and open interest, while bar-only connectors report unsupported derivative data explicitly.
- `DataConnectorRegistry` can route optional normalized order-book snapshot requests by source, while connectors without order-book support report unsupported data explicitly.
- `load_data_connector_registry_json()` can register `type: "ccxt"` adapters from JSON config, so exchange-backed research routes can use Binance, Bybit, OKX, or other CCXT exchanges through one adapter selected by `MarketSpec.exchange`.
- `CcxtExchangeConnector.fetch_bars()` now accepts configured `start`/`end` windows, passes `start` to CCXT as `since`, sends `endTime` as a best-effort exchange parameter, and filters the normalized UTC-indexed OHLCV frame locally before it reaches research storage or feature generation.
- `load_data_connector_registry_json()` can build configured CSV and SQLite connector registries from project JSON, resolving relative file and database paths against a caller-provided project root and passing through configured local bar `column_map` records.
- `YahooFinanceConnector` can load Yahoo Finance chart OHLCV responses into the same normalized UTC-indexed bar schema, with injectable HTTP for deterministic tests and explicit symbol mappings for vendor-specific tickers such as `BRK.B` -> `BRK-B`.
- `load_data_connector_registry_json()` can register Yahoo Finance connectors from project JSON via `type: "yahoo"` without adding a BTC strategy dependency.
- `AlphaVantageConnector` can load Alpha Vantage daily and intraday time-series OHLCV responses into the same normalized UTC-indexed bar schema, with injectable HTTP for deterministic tests and API keys resolved from an environment variable at runtime.
- `load_data_connector_registry_json()` can register Alpha Vantage connectors from project JSON via `type: "alpha_vantage"` and rejects inline `api_key` values so credentials stay out of source.
- `PolygonConnector` can load Polygon.io aggregate OHLCV responses into the same normalized UTC-indexed bar schema, with timeframe mapping to Polygon range multipliers/timespans and API keys resolved from an environment variable at runtime.
- `load_data_connector_registry_json()` can register Polygon connectors from project JSON via `type: "polygon"` and rejects inline `api_key` values so credentials stay out of source.
- `config/research_data_sources.json` defines a local CSV research source for the default non-BTC AAPL/NASDAQ equity example and registers optional CCXT exchange, Yahoo Finance, Alpha Vantage, and Polygon vendor connectors without making preview/API flows depend on live network access.
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
- `ParquetOrderBookStore`
- `ParquetDerivativeStore`
- `SQLiteBarStore`
- `SQLiteDerivativeStore`
- `SQLiteExternalMetricStore`
- `SQLiteOrderBookStore`
- `SQLiteFeatureStore`
- `pyarrow>=15.0` declared in `requirements.txt`
- `quant_btc.data.fetch_ohlcv()` reads `ParquetBarStore` before the legacy pickle cache.
- Remote OHLCV fetches write to `ParquetBarStore` and still write pickle files as a migration fallback.
- Derivative funding/open-interest fetches read from `ParquetDerivativeStore` before legacy pickle cache, and remote fetches write both the Parquet derivative store and legacy pickle cache as a migration fallback.
- `serve.data_loader.get_ohlcv()` now reads the platform `ParquetBarStore` before legacy pickle files for BTC dashboard/API data, keeping pickle only as a visualization fallback.
- `fetch_bars_with_cache()` now provides a generic DataConnector-to-BarStore read/write boundary keyed by `BarSeriesId`, so vendor, exchange, CSV, or database adapters can share a BarStore-first cache path instead of each workflow reimplementing BTC-specific pickle compatibility.
- `fetch_derivatives_with_cache()` now provides the matching generic DataConnector-to-DerivativeStore read/write boundary keyed by `DerivativeSeriesId`, including optional `start`/`end` window filtering and connector pass-through for adapters that support ranged derivative fetches; the BTC derivative remote-fetch path uses this platform helper after the existing Parquet and pickle read fallbacks are checked.
- `fetch_order_book_snapshots_with_cache()` now provides the matching generic DataConnector-to-OrderBookStore read/write boundary keyed by `OrderBookSeriesId`.
- Generic research preview bar loading now goes through `fetch_bars_with_cache()` with `ParquetBarStore(data/research_bars)` by default or `SQLiteBarStore(data/research_bars)` when a route sets `store_type: "sqlite"`, so configured non-BTC sources use the same BarStore-first connector cache path before feature, signal, risk, portfolio, and delivery layers run.
- Generic research data routes can now provide `start` and `end` bar windows that are parsed as UTC timestamps and passed into the DataConnector-to-BarStore cache boundary before FeatureEngine execution; CCXT-backed bar routes can now carry those windows into exchange fetches instead of only filtering local cache reads. Derivative routes can provide the same window fields before funding/open-interest data enters the route-selected Parquet or SQLite DerivativeStore-backed feature path.
- Generic intraday research preview/event-backtest bar loading now filters connector/cache output through `MarketSpec.is_trading_time()`, so regular-session assets drop after-hours and non-trading-day bars before FeatureEngine, SignalModule, RiskEngine, PortfolioEngine, and delivery layers consume the data.
- `/api/signals/research-preview` and `/api/signals/research-event-backtest-preview` now accept `refresh_bars=true`, and the service functions accept `refresh_bars=True`, so callers can explicitly bypass BarStore hits when refreshing configured research bars from their DataConnector source.
- Generic research previews now run the default non-BTC feature builder through `run_feature_engine_with_cache()` and `ParquetFeatureStore(data/research_features)` by default or `SQLiteFeatureStore(data/research_features)` when research data config sets `feature_store_type: "sqlite"`, giving configured research markets a FeatureStore boundary before standardized signals are generated.
- Generic swap/futures research feature runs now look for configured `data_type: "derivatives"` routes, load funding/open-interest through `fetch_derivatives_with_cache()` and `ParquetDerivativeStore(data/research_derivatives)` by default or `SQLiteDerivativeStore(data/research_derivatives)` when a route sets `store_type: "sqlite"`, honor route-level `start`/`end` derivative windows, and append `DerivativesFeatureModule` output with derivative-enabled FeatureStore keys kept separate from OHLCV-only cache keys.
- If a configured derivative adapter or derivative store is unavailable at runtime, the default research feature builder falls back to the OHLCV-only feature set instead of failing the preview, keeping derivatives as an optional enrichment layer.
- Derived feature sets can now be persisted through `ParquetFeatureStore` or `SQLiteFeatureStore` using deterministic paths keyed by symbol, exchange, market type, timeframe, source, and feature set.
- `FeatureEngine` runs can now use `run_feature_engine_with_cache()` to read existing cached feature frames from any read-capable `FeatureStore`, fall back to recomputing on cache miss, and persist fresh output through the same boundary for downstream logic.
- Generic research FeatureStore keys now include the default feature builder's resolved `RegimeProfile` trend EMA, ATR, ADX, and Bollinger parameters, preventing different asset/profile feature outputs from sharing one stale `research_default_v1` cache key.
- Generic research FeatureStore keys now also include a `turnover` schema marker when source bars carry standardized `Turnover`, preventing traded-value feature outputs from sharing stale OHLCV-only caches.
- `/api/signals/research-preview` now accepts `refresh_features=true`, and the service accepts `refresh_features=True`, so generic non-BTC research previews can explicitly bypass FeatureStore hits when a caller needs freshly recomputed feature output.
- Generic research preview responses now include `featureCache` metadata for the default FeatureStore-backed feature run; injected feature builders and empty bar responses return `null` for that field.
- The Signal Pipeline dashboard now renders that `featureCache` metadata in a Feature Cache feed, so users can see whether the generic research preview used a FeatureStore hit or wrote refreshed features.
- `/api/signals/research-event-backtest-preview` now uses the same default cached non-BTC `FeatureEngine` path and accepts `refresh_features=true`, so event-driven research simulations no longer bypass the FeatureStore boundary.
- Generic research event-backtest responses now include per-symbol `featureCaches` metadata for the default FeatureStore-backed feature runs; injected feature builders and empty bar streams return `null` for the relevant symbol.
- The Signal Pipeline dashboard now renders event-backtest `featureCaches` in an Event Feature Cache feed, so multi-symbol research runs expose per-symbol FeatureStore hit/write state without inspecting raw JSON.
- BTC and generic research event-backtest responses now include a `finalPortfolio` snapshot serialized from the event-driven `PortfolioEngine` state, exposing final open positions and open risk through the same API surface as orders, fills, trades, equity, and exposure.
- `/api/signals/research-event-backtest-preview` can now accept multiple configured markets in one request, using each symbol's BarStore/FeatureStore-backed stream before handing all feature frames to one portfolio-level event-driven run.
- External metric frames such as Valuescan AI tracking data can now be persisted through `ParquetExternalMetricStore` using deterministic paths keyed by source, provider, symbol, timeframe, and dataset.
- Configured generic research routes with `data_type: "external_metrics"` can now read one or more persisted external metric frames from `ParquetExternalMetricStore(data/research_external_metrics)` by default or `SQLiteExternalMetricStore(data/research_external_metrics)` when a route sets `store_type: "sqlite"`, and apply route-level `start`/`end` windows before FeatureEngine execution, giving macro, on-chain, sentiment, or Valuescan-style datasets a storage-backed path into non-BTC research previews.
- `SQLiteBarStore` provides a no-extra-dependency OHLCV storage backend keyed by `BarSeriesId`, preserving UTC timestamps and standard `Open`, `High`, `Low`, `Close`, `Volume` columns for research workflows that prefer SQLite over Parquet files.
- `SQLiteBarStore` also preserves optional `Turnover` columns for normalized bar series and upgrades existing OHLCV-only SQLite bar tables in place when turnover-backed bars are written.
- `OrderBookSeriesId`, `ParquetOrderBookStore`, and `SQLiteOrderBookStore` provide deterministic storage keys and Parquet/SQLite persistence for normalized order-book snapshots keyed by symbol, exchange, market type, depth, sample interval, and source.
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
- `config/research_feature_modules.json`
- `FeatureEngine`
- `FeatureModuleRegistry`
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
- Generic research previews now default to a cached `FeatureEngine` composed from the configured module set in `config/research_feature_modules.json`; the default set covers technical indicators, Donchian channels, volume z-score, ATR/ADX, Bollinger bands, and price-action features, with `$regime.*` placeholders resolving trend EMA, ATR, ADX, Bollinger period, and Bollinger standard-deviation multiplier from the current market's `RegimeProfile`.
- Those resolved regime feature parameters are included in the persisted feature set name, so non-BTC markets do not inherit BTC-only regime-feature assumptions or collide with stale caches from other profiles.
- When a configured swap/futures derivative route exists, the default generic research `FeatureEngine` also includes `DerivativesFeatureModule`, giving non-BTC research flows funding rate, open interest, funding z-score, open-interest change, and derivative price-change columns without putting derivative fetching into signal modules.
- Missing or unsupported derivative data remains non-fatal for generic research feature generation, so the same configured market can still flow through signal, risk, portfolio, and delivery layers with OHLCV-only features.
- `quant_btc.strategy.prepare_features()` now uses a BTC compatibility feature engine for EMA, MACD, higher-timeframe EMA, RSI, ATR, ADX, Donchian, Bollinger, volume z-score, and candle shadow columns.
- The BTC compatibility feature engine now exposes a deterministic `btc_compat_v1` `FeatureSeriesId` and `build_cached_btc_features()` wrapper for optional `ParquetFeatureStore` persistence.
- The dashboard signal preview default feature builder now attempts to cache BTC compatibility `FeatureEngine` output under `data/features` before continuing through the existing `prepare_features()` path, so cached features do not change trading signal behavior.
- Funding/open-interest data now has a platform feature module that aligns derivative series to bar timestamps and adds funding z-score, open-interest change, and derivative price-change columns without mutating input bars.
- `quant_btc.strategy.compute_derivative_bonus()` now consumes `DerivativesFeatureModule` output for BTC derivative bonus scoring, keeping the legacy crowded-long, deleveraging, crowded-short, and short-cover rules in the BTC compatibility layer.
- Order-book snapshots now have a platform feature module that aligns normalized depth snapshots to OHLCV bars and derives best bid/ask, spread, mid, relative spread, depth-size sums, and imbalance columns without putting market-data fetching or storage into signal modules.
- `VolumeFeatureModule` now derives rolling traded-value mean, standard deviation, and z-score columns from standardized `Turnover` when bar sources provide traded-value data, extending volume normalization beyond raw share/contract volume.
- Default generic research feature runs include `Turnover` availability in the persisted feature-set name, so the traded-value columns generated by `VolumeFeatureModule` are isolated from OHLCV-only FeatureStore entries.
- `FeatureModuleRegistry` and `default_feature_module_registry()` can build a `FeatureEngine` from JSON-like module records for config-only feature modules, so research workflows can register and select technical, Donchian, volume, volatility, Bollinger, and price-action features without hardcoding every module list at each call site.
- Generic research preview and event-backtest feature generation now load matching module sets from `config/research_feature_modules.json` through `FeatureModuleRegistry`, with optional per-market/per-timeframe routes and `$regime.*` parameter substitution, while retaining the previous default module chain as a fallback when no config file is present.
- Generic research feature runs can now load configured order-book snapshot routes through `fetch_order_book_snapshots_with_cache()` and `ParquetOrderBookStore(data/research_order_books)` by default or `SQLiteOrderBookStore(data/research_order_books)` when a route sets `store_type: "sqlite"`, append `OrderBookFeatureModule`, and include the configured depth in the FeatureStore key.
- External metrics such as Valuescan social sentiment, AI risk scores, on-chain values, macro series, or order-book derived metrics can now be aligned into bars through `ExternalMetricFeatureModule` using stable prefixed feature columns.
- Generic research feature runs can now append multiple configured `ExternalMetricFeatureModule` instances from `data_type: "external_metrics"` routes, preserving route-selected metric columns, honoring route-level metric windows, supporting route-selected Parquet or SQLite metric stores, and including all provider/dataset identities in the FeatureStore key so external-metric feature frames cannot reuse stale OHLCV-only caches.
- Valuescan overview and AI list payloads can now be converted into timestamp-indexed external metric frames and aligned to OHLCV bars through `serve.valuescan_metrics` without exposing API credentials or changing existing trading signals.
- Valuescan research feature previews are exposed through `/api/valuescan/ai/features` and rendered in the AI Tracking dashboard as read-only `valuescan_*` feature rows.
- `/api/valuescan/ai/features` now attempts to cache normalized Valuescan AI tracking metrics under `data/external_metrics` and returns cache metadata in the preview payload; cache failures are reported as route errors metadata instead of changing or blocking trading signals.

Remaining:

- Move remaining regime helper columns and module-specific execution permissions out of `quant_btc.strategy`.
- Broaden feature cache invalidation/versioning beyond deterministic feature-set names if research workflows need content hashes, TTLs, or profile parameters beyond the current default trend EMA, ATR, ADX, and Bollinger feature parameters.

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
- Generic research event previews now pass the same resolved non-BTC `RegimeProfile` and configured `MarketSpec` into injected feature and signal builders before running standardized signals through `EventDrivenBacktest`.
- Generic research event previews can now resolve a market-specific `RegimeProfile` per symbol when a request contains multiple configured symbols, so one multi-asset research run no longer forces all assets through a single regime assumption.
- Generic research preview and event-backtest payloads now serialize the latest `RegimeModel` output as `latestRegime` for single-market runs and `latestRegimes` for multi-market event runs, giving API consumers the classified market state from each asset's resolved profile.
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
- `SignalModuleRegistry`
- `ColumnSignalModule`
- `BreakoutSignalModule`
- `SignalModuleRunner`
- `config/research_signal_modules.json`
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
- `select_btc_base_entry_signal()` wraps BTC base strategy entry selection in a standardized compatibility `Signal`, and `BaseRiskStrategy` now consumes that signal direction before applying its existing stop, sizing, and order logic.
- `select_btc_weighted_legacy_signal()` wraps the simple weighted legacy strategy entry in a standardized compatibility `Signal`, while `WeightedSignalStrategy` preserves the legacy 95% fractional size and opposite-signal close behavior.
- `select_btc_tactical_signal()` wraps BTC dual-layer tactical entry priority selection in a standardized compatibility `Signal`, and `DualLayerStrategy` now consumes that signal before applying its existing tactical stop, sizing, state, and order logic.
- `select_btc_core_entry_signal()`, `select_btc_core_add_signal()`, and `select_btc_bear_core_probe_signal()` wrap BTC core-long entry, core pullback add, and bear-core stage-1 probe selection in standardized compatibility `Signal` objects while `DualLayerStrategy` keeps its existing layer state and order side effects.
- `select_btc_bear_core_confirm_add_signal()` and `select_btc_bear_core_acceleration_add_signal()` wrap BTC bear-core stage-2 confirmation add and stage-3 acceleration add selection in standardized compatibility `Signal` objects while `DualLayerStrategy` keeps its existing add-size, group-exposure, layer state, and order side effects.
- `select_btc_flash_crash_dip_buy_signal()` wraps the BTC flash-crash dip-buy tactical add-on in a standardized compatibility `Signal` while `DualLayerStrategy` keeps the legacy flash-crash activation state and 10% tactical size semantics.
- `BreakoutSignalModule` can compute current-bar Donchian breakout signals directly from OHLCV, with preferred stop/target, score, confidence, and `required_data`, without precomputed legacy boolean signal columns.
- `PullbackSignalModule` can compute current-bar EMA pullback continuation signals directly from OHLCV, with preferred stop/target, score, confidence, and `required_data`, without mutating the source bars.
- `MeanReversionSignalModule` can compute current-bar rolling-band reclaim signals directly from OHLCV, with preferred stop/target, score, confidence, and `required_data`, without mutating the source bars.
- `SweepReversalSignalModule` can compute current-bar range sweep-and-reclaim signals directly from OHLCV, with preferred stop/target, score, confidence, and `required_data`, without mutating the source bars.
- `CrashShortSignalModule` can compute current-bar crash impulse short signals directly from OHLCV, with volume confirmation, preferred stop/target, score, confidence, and `required_data`, without mutating the source bars.
- `FailedBounceSignalModule` can compute current-bar failed bounce short signals directly from OHLCV, with resistance rejection, preferred stop/target, score, confidence, and `required_data`, without mutating the source bars.
- `BullTrapSignalModule` can compute current-bar bull trap short signals directly from OHLCV, with breakout-volume confirmation, weak-close confirmation, preferred stop/target, score, confidence, and `required_data`, without mutating the source bars.
- `SignalModuleRegistry` and `default_signal_module_registry()` can build `SignalModuleRunner` instances from JSON-like module records for the column adapter and all current direct-compute signal modules, giving research workflows a config-driven signal-module selection boundary before service-level defaults are fully externalized.
- Generic research preview and event-backtest signal generation now load matching module sets from `config/research_signal_modules.json` through `SignalModuleRegistry`, with request timeframe injected when module records omit it, while retaining the previous seven-module default as a fallback.
- BTC 15m MTF confirmation helpers for sweep/reclaim, no-new-extreme, and higher-low checks now live in `quant_btc.signal_modules`, while `DualLayerStrategy` only selects the current 4H window.

Remaining:

- Continue feeding standardized signals into RiskEngine and PortfolioEngine instead of strategy classes reading remaining boolean columns directly.

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
- `RiskBudgetUsage`
- `RiskBudgetDiagnostics`
- `RiskEngine`
- `tests/test_platform_risk.py`
- `tests/test_btc_risk_model.py`
- Risk decisions now cover stop-distance sizing, max notional caps, daily/weekly drawdown gates, total portfolio risk budget gates, per-symbol risk gates, per-module risk gates, correlation-group risk gates, exchange risk gates, market-type risk gates, flat/missing-stop blocking, consecutive-loss size reduction, and pause windows.
- `RiskEngine` can now consume `markets_by_symbol` and apply `MarketSpec.supports_short` / `MarketSpec.supports_leverage` permissions, blocking unsupported short signals and capping non-leveraged markets at unlevered notional exposure.
- `RiskEngine` now also applies `MarketSpec.max_leverage` for leveraged markets, capping notional exposure at `RiskLimits.max_position_fraction * min(RiskLimits.max_leverage, MarketSpec.max_leverage)` when a market-level maximum is configured.
- `RiskEngine` now applies `MarketSpec.contract_multiplier` when converting stop distance into per-contract risk, contract quantity, and notional exposure, while `PortfolioEngine` uses the same multiplier for planned and filled position notional.
- `RiskEngine` now evaluates portfolio, symbol, module, correlation-group, exchange, and market-type budget gates with the candidate's actual capped `risk_amount` after notional, leverage, and contract-multiplier sizing, rather than the larger pre-cap target risk.
- `RiskLimits.max_symbol_risk` and `RiskLimits.max_module_risk` let the platform cap concentration in one instrument or one signal family, and `SignalPipeline` passes symbol/module open risk from `PortfolioState`.
- `RiskLimits.correlation_groups` and `RiskLimits.max_correlation_group_risk` let the platform cap related-symbol exposure, and `SignalPipeline` passes group-level open risk from `PortfolioState`.
- `RiskLimits.max_exchange_risk` and `RiskLimits.max_market_type_risk` let the platform cap exchange and market-type concentration, and `SignalPipeline` passes existing-position plus same-batch open risk resolved from `MarketSpec.exchange` and `MarketSpec.market_type`.
- Generic research preview and research event-backtest service/API callers can pass `RiskLimits` overrides or query parameters such as `risk_per_trade`, `portfolio_risk_budget`, `max_symbol_risk`, `max_module_risk`, `max_correlation_group_risk`, `max_exchange_risk`, `max_market_type_risk`, and `max_drawdown_pct`, so API-driven research can enforce the same platform risk budgets as direct Python callers.
- The Signal Pipeline dashboard now exposes those generic research risk-limit parameters as optional controls and appends non-empty values to generic preview/event-backtest requests, so UI-driven multi-asset research can exercise the same portfolio, symbol, module, correlation, exchange, market-type, and drawdown budgets.
- `RiskEngine` now falls back to `MarketSpec.correlation_group` when `RiskLimits.correlation_groups` has no explicit symbol mapping, so configured markets can carry their default correlation exposure group through generic research and event-backtest paths.
- `SignalPipeline` now resolves correlation groups through `RiskEngine.correlation_group_for_symbol()` when reading existing positions, accumulating newly allowed decisions in the same signal batch, and building risk diagnostics, so `MarketSpec.correlation_group` affects portfolio-level correlation budgets even without duplicate `RiskLimits.correlation_groups` entries.
- `RiskEngine.budget_diagnostics()` now returns portfolio, symbol, module, correlation-group, exchange, and market-type risk usage, remaining budget where configured, utilization, target next-trade risk, and current loss-streak pause state without changing risk gate behavior.
- `RiskLimits.max_drawdown_pct` and `RiskState.equity_peak` add a default-off portfolio maximum drawdown gate; `RiskEngine.evaluate()` observes account equity to maintain the peak, blocks new risk with `max_drawdown_limit` when the threshold is breached, and `riskDiagnostics.drawdown` reports current drawdown, threshold, and breach state for API/dashboard consumers.
- `EventDrivenBacktest` now feeds mark-to-market account equity into `SignalPipeline` before each event evaluation, allowing the `RiskEngine` maximum drawdown gate to react to realized and unrealized portfolio losses during multi-symbol simulations.
- `EventDrivenBacktest` now records each realized `BacktestTrade.net_pnl` into `RiskState`, allowing consecutive-loss size reductions and pause windows to affect later signals in event-driven research runs.
- `SignalPipeline.run_decisions()` can apply precomputed `RiskDecision` objects through portfolio planning, delivery, and risk diagnostics, giving legacy or external risk engines a bridge into the standard platform result shape without forcing a second `RiskEngine.evaluate()` pass.
- BTC single-module stop-distance sizing now lives in `quant_btc.risk_model.calculate_btc_base_position_size()`, preserving max-position caps, consecutive-loss size reduction, HTF conflict half sizing, and bear-short discounts while `BaseRiskStrategy` delegates to it.
- BTC tactical module risk percentages and legacy stop-distance position sizing now live in `quant_btc.risk_model.calculate_btc_tactical_position_size()`, while the dual-layer compatibility strategy delegates to it instead of hardcoding module risk maps in `Strategy.next()`.
- BTC dual-layer regime-dependent size adjustment now lives in `quant_btc.risk_model.btc_dual_layer_regime_size_multiplier()`, preserving the weak-bull/transition half-sizing rule while `DualLayerStrategy` keeps only market state reads.
- `build_btc_legacy_entry_risk_decision()` can convert a legacy BTC fractional entry, including entry, stop, target, equity, and size fraction, into a read-only platform `RiskDecision` audit object without replacing legacy sizing or execution.
- `BaseRiskStrategy` now records confirmed legacy base entries as `_last_platform_risk_decision`, and `DualLayerStrategy` does the same for confirmed tactical, core-long, core pullback-add, and bear-core probe/confirm/acceleration entries, giving strategy-class entry paths a platform `RiskDecision` audit object while leaving order execution unchanged.
- `BaseRiskStrategy._record_legacy_entry_risk_decision()` now also records `_last_platform_pipeline_result` and appends to `_platform_pipeline_results` by passing each confirmed legacy `RiskDecision` through `SignalPipeline.run_decisions()`, so base and dual-layer entry paths share read-only signals/risk-decisions/portfolio-plan/risk-diagnostics audit snapshots before legacy execution is replaced.
- `WeightedSignalStrategy` now records opposite-signal legacy closes as read-only `SignalPipeline` snapshots too, using `PortfolioEngine(close_on_opposite_signal=True)` to produce a platform `CLOSE` order audit while preserving the existing `position.close()` execution side effect.
- `BaseRiskStrategy` partial take-profit and full-position exits now record read-only platform `CLOSE` order audits before legacy `position.close()` side effects for partial take-profit, time-stop, invalidation, trailing-stop, and extra-exit paths.
- `DualLayerStrategy` core, tactical, and bear-core exits now record read-only platform `CLOSE` order audits before calling the existing legacy close side effects, including bear-core V-reversal, giveback, waterfall guard, waterfall runner, and trend exits, keeping legacy close sizing intact while adding those exit paths to `_platform_pipeline_results`.
- `build_btc_legacy_entry_risk_engine_decision()` now runs the same confirmed legacy fractional entry through the generic `RiskEngine.evaluate()` using the legacy risk amount as an audit target, and strategy classes store it as `_last_platform_risk_engine_decision` before enforcement is enabled.
- `BaseRiskStrategy`, `WeightedSignalStrategy`, and `DualLayerStrategy` now expose a default-off `_ENFORCE_PLATFORM_RISK_ENGINE` path; tests can inject a strict platform `RiskEngine` and verify blocked decisions prevent legacy base, weighted, tactical, flash-crash dip-buy, core-long, core pullback-add, and bear-core probe/confirm/acceleration entries before order/state mutation, while default backtest behavior remains unchanged.
- `BtcLegacyRiskAudit` serializes each legacy/platform risk pair with parity status, allowed/sizing matches, numeric deltas, engine reason, and would-block flags; strategy classes append those audit snapshots to `_platform_risk_audits` for pre-enforcement review.
- The read-only migration comparison service/API now exposes `riskAudit` with raw audit rows, parity-status counts, mismatch count, and would-block-if-enforced count, making RiskEngine parity review part of the legacy-vs-event migration surface.
- `load_btc_legacy_risk_audits()` now runs the legacy dual-layer backtest path and extracts `_platform_risk_audits` from the returned strategy instance when `FractionalBacktest` is available; migration comparison uses that loader by default and keeps returning an empty audit payload in lightweight runtimes where legacy backtesting is unavailable.
- `load_btc_legacy_pipeline_audits()` now extracts `_platform_pipeline_results` from the same legacy strategy runtime, and migration comparison exposes a `pipelineAudit` payload with serialized signals, risk decisions, portfolio orders, delivery results, and risk diagnostics for platform pipeline parity review.
- Migration comparison now exposes `orderParity`, comparing legacy strategy-class pipeline orders against event-driven platform orders by action, symbol, layer, direction, module, quantity, entry, stop, and target, with module-level `byModule` counts so order-plan mismatches can be reviewed before execution migration.
- Migration comparison now derives `migrationReadiness` from `riskAudit`, `pipelineAudit`, and `orderParity`, marking a module ready only when it has risk audit evidence, pipeline order evidence, no risk parity mismatch, no platform would-block result, and no order parity mismatch.

Remaining:

- Decide when platform RiskEngine enforcement can graduate from default-off audit mode after migration parity review.

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
- `SignalPipeline` now prioritizes standardized signals by score before applying risk budgets, matching `PortfolioEngine` conflict priority so a lower-score same-batch same-layer signal cannot consume scarce portfolio budget ahead of a stronger candidate.
- BTC legacy-entry audit `RiskDecision` objects can be passed through `SignalPipeline.run_decisions()` to produce standard open-order plans, delivery payloads, and risk diagnostics, giving compatibility flows a non-mutating bridge into platform planning before historical execution is replaced.
- BTC strategy-class entries now persist that `SignalPipeline.run_decisions()` result as `_last_platform_pipeline_result` and `_platform_pipeline_results` during audit mode, using a fresh portfolio engine and BTC module-to-layer mapping so the standard plan is observable without mutating legacy trade state.
- BTC event-driven preview payloads now include serialized platform `orders`, not only aggregate order counts, giving migration comparison a concrete event-side order surface for parity checks.
- BTC base strategy entries and dual-layer tactical entries now save the first platform open order from `SignalPipeline.run_decisions()` as `_last_platform_entry_order` and use that platform order's direction, stop, and target when calling the legacy buy/sell side effects, while preserving the legacy fractional `size` parameter required by the historical backtesting runtime.
- BTC weighted legacy entries now save the first platform open order from `SignalPipeline.run_decisions()` and use that platform order's direction, stop, and target when calling the legacy buy/sell side effects, while preserving the legacy 95% fractional `size` parameter.
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
- BTC flash-crash dip-buy execution now records the legacy fractional add-on as a platform `RiskDecision` audit, runs it through `SignalPipeline.run_decisions()`, and consumes the recorded platform open-order direction, stop, and target while preserving the legacy 10% tactical size.
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
- Generic research event backtest previews can now consume any configured `MarketSpec` through the same standard pipeline/backtest path, so non-BTC markets are no longer limited to single-bar signal preview payloads.
- Generic research event backtest previews now expose the existing multi-symbol `EventDrivenBacktest` capability through the service layer, allowing configured markets to run in one timestamp-ordered portfolio simulation with shared risk and portfolio state.
- `EventDrivenBacktest` can run a standardized `SignalPipeline` over multiple symbol feature streams in global timestamp order, collect signals, risk decisions, portfolio orders, delivery results, fill submitted open orders with configurable slippage at the current bar close, close positions on stop/target, record realized trades, record portfolio state history after each event, subtract fees, and produce an equity curve with realized PnL, unrealized PnL, per-event return, current equity peak, and per-event drawdown amount, percent, and duration.
- `EventDrivenBacktest` now constructs each event's `AccountState` from current cash plus latest marked open-position PnL before running the pipeline, so downstream sizing, budgets, and drawdown gates use current portfolio equity rather than the initial equity snapshot.
- Realized event trades now feed the shared `RiskEngine` state before subsequent timestamp-ordered events run, so multi-symbol simulations can model loss-streak risk controls across symbols and layers.
- `EventDrivenBacktest` can now consume `markets_by_symbol` so per-symbol `MarketSpec.fee_rate`, `MarketSpec.funding_rate`, and `MarketSpec.contract_multiplier` are reflected in fees, funding, realized PnL, and unrealized PnL.
- `EventDrivenBacktestResult.attribution` summarizes realized trade count, gross PnL, net PnL, fees, and win rate by symbol, layer, signal module, direction, exit reason, exchange, market type, and correlation group.
- `PortfolioEngine` now supports an explicit `rebalance_existing` mode for same-symbol, same-layer, same-direction positions: a higher approved target quantity produces a submitted `REBALANCE` order for the quantity delta while default existing-position behavior remains unchanged.
- Filled same-direction `REBALANCE` orders now update the existing position with the increased quantity, combined notional, weighted entry price, target risk amount, and refreshed stop/target levels.
- Same-direction `REBALANCE` also supports lower approved target quantities: the engine submits a `decrease_position` order for the reduction delta and filled reductions shrink position quantity, notional, and risk amount while preserving the existing entry basis.
- `PortfolioEngine` now supports a default-off `close_on_opposite_signal` mode for explicit direction changes: an opposite same-symbol/same-layer signal submits a `CLOSE` order for the current position, and submitted close fills shrink or remove that position through `record_fill()`.
- `EventDrivenBacktest` now fills pipeline-submitted `CLOSE` orders, converts them into realized `BacktestTrade` rows, and accounts realized PnL plus exit fees without double-counting entry/open-order fees, so explicit opposite-signal closes flow through the event-driven execution path.
- `EventDrivenBacktest` now fills submitted `REBALANCE` orders, so same-direction scale-in orders update position quantity, weighted entry price, fees, unrealized PnL, and equity during event-driven runs instead of remaining submitted in portfolio state.
- Partial-reduce `REBALANCE` fills now produce realized `BacktestTrade` rows and realized PnL, while decrease-position rebalance fills are treated as exits rather than entry-like fills for fee and attribution accounting.
- `PortfolioEngine` now supports a default-off `reverse_on_opposite_signal` mode for one-step same-symbol, same-layer reversals: an opposite signal can plan an ordered `CLOSE` for the existing position followed by an `OPEN` for the new direction, and deferred open fills create the replacement position after the close fill removes the old one.
- `EventDrivenBacktest` can now fill one-step reversal order sequences on the same event, recording the closed leg as a realized trade while accounting the replacement open fee and leaving the new direction open for later bars.
- `PortfolioEngine` now supports a default-off `transfer_existing_layer` mode for layer management: when a target layer is empty and exactly one same-symbol, same-direction position exists in another layer, the engine moves that position into the incoming signal's layer through a filled internal `TRANSFER` order instead of opening a duplicate position.
- `EventDrivenBacktest` now records filled internal `TRANSFER` orders in `EventDrivenBacktestResult.filled_orders`, making core/tactical layer transfers auditable in the same result surface as submitted open, close, and rebalance fills.
- BTC and generic event-preview payloads now serialize `filledOrderCount` and `filledOrders` beside planned `orders`, so API consumers can distinguish intended order plans from actual event-engine fills including internal layer transfers.
- `EventDrivenBacktestResult.order_status_counts` now provides an effective order-state summary where filled executions replace their submitted plan rows, and BTC/generic event-preview payloads serialize `orderStatusCounts` for planned, submitted, partially filled, filled, canceled, and rejected orders.
- `EventDrivenBacktestResult.order_action_counts` now provides an effective order-action summary where filled and terminal executions replace their submitted plan rows, and BTC/generic event-preview payloads serialize `orderActionCounts` for open, close, rebalance, transfer, and ignore orders.
- `EventDrivenBacktestResult.order_module_counts` now provides an effective order-origin summary keyed by `SignalModule`, and BTC/generic event-preview payloads serialize `orderModuleCounts` so module-level order churn can be audited before a module realizes trades.
- `EventDrivenBacktestResult.order_symbol_counts` and `order_layer_counts` now provide effective order summaries keyed by symbol and portfolio layer, and BTC/generic event-preview payloads serialize `orderSymbolCounts` and `orderLayerCounts` so multi-symbol and core/tactical order concentration can be audited before positions close.
- The Signal Pipeline dashboard now renders `orderSymbolCounts`, `orderLayerCounts`, `orderModuleCounts`, `orderActionCounts`, and `orderStatusCounts` in the Event Order Status table and includes event/fill order counts in the event summary, so multi-symbol/multi-layer order action/state audits are visible without inspecting raw API JSON.
- `EventDrivenBacktestResult.order_latency` and `order_latency_summary` now track submitted-order wait time in bars from first submitted/partial state to filled, canceled, or rejected resolution; `BacktestOrderLatency` and `BacktestOrderLatencySummary` are exported from the platform package, BTC/generic event-preview payloads serialize `orderLatency` and `orderLatencySummary`, and the dashboard event summary renders average and maximum order wait beside order counts.
- The Signal Pipeline dashboard now renders an Event Order Latency table from `orderLatency`, showing each resolved order's id, status, symbol, layer, module, submitted bar, resolved bar, and wait bars so fill/cancel latency can be audited without raw API JSON.
- `EventDrivenBacktestResult.open_order_ages` and `open_order_age_summary` now report unresolved submitted/partially-filled order age at run end; `BacktestOpenOrderAge` and `BacktestOpenOrderAgeSummary` are exported from the platform package, BTC/generic event-preview payloads serialize `openOrderAges` and `openOrderAgeSummary`, and the dashboard Event Order Latency table plus event summary cards include those still-open order counts, rows, average age, and max age with current bar and age bars.
- `EventDrivenBacktestResult.order_lifecycle_summary` now derives total, filled, open, resolved, and terminal order counts plus fill/open/terminal rates from effective event orders; `order_lifecycle_by_action`, `order_lifecycle_by_module`, `order_lifecycle_by_symbol`, `order_lifecycle_by_layer`, `order_lifecycle_by_direction`, `order_lifecycle_by_correlation_group`, `order_lifecycle_by_exchange`, and `order_lifecycle_by_market_type` apply the same lifecycle summary per order action, `SignalModule`, symbol, portfolio layer, direction, `MarketSpec.correlation_group`, exchange, and `MarketSpec.market_type`, `BacktestOrderLifecycleSummary` is exported from the platform package, BTC/generic event-preview payloads serialize `orderLifecycleSummary`, `orderLifecycleByAction`, `orderLifecycleByModule`, `orderLifecycleBySymbol`, `orderLifecycleByLayer`, `orderLifecycleByDirection`, `orderLifecycleByCorrelationGroup`, `orderLifecycleByExchange`, and `orderLifecycleByMarketType`, and dashboard event summary cards plus the Event Action/Module/Symbol/Layer/Direction/Correlation/Exchange/Market Type Lifecycle tables show those execution-quality rates beside raw order count and latency metrics.
- `BacktestExecutionConfig.intrabar_stop_target` provides an optional more realistic stop/target simulation mode: when enabled and `High`/`Low` are available, open positions exit at the configured stop or target price when the current bar range touches it, while the default close-only trigger mode remains unchanged for compatibility.
- `BacktestExecutionConfig.intrabar_entry_limit` provides a default-off entry-touch simulation mode: entry-like submitted OPEN and scale-in REBALANCE orders require the current bar range to touch the order entry price before filling, while untouched OPEN orders remain submitted and do not leave a pre-created position in portfolio state.
- `EventDrivenBacktest` now carries existing submitted and partially filled orders forward into later same-symbol bar events, allowing pending `intrabar_entry_limit` orders to fill when a subsequent bar range touches their entry price instead of requiring a fresh signal on the fill bar.
- `BacktestExecutionConfig.max_entry_fill_fraction_per_bar` provides a default-off partial-fill simulation for entry-like submitted orders: OPEN and scale-in REBALANCE fills can be capped to a fraction of original order quantity per bar, with remaining quantity staying partially filled for later same-symbol events and entry fees charged on the incremental fill quantity.
- `BacktestExecutionConfig.max_entry_volume_fraction_per_bar` provides a default-off volume-participation fill cap for entry-like submitted orders: when `Volume` is present, OPEN and scale-in REBALANCE fills can be limited to `Volume * fraction` for the current bar before remaining quantity carries forward.
- `BacktestExecutionConfig.max_exit_fill_fraction_per_bar` and `max_exit_volume_fraction_per_bar` provide matching default-off partial-fill and volume-participation caps for exit-like submitted CLOSE / reduce REBALANCE orders and triggered stop/target exits, recording realized trades from each incremental exit fill while keeping portfolio order state cumulative.
- `BacktestExecutionConfig.max_entry_order_age_bars` and `max_exit_order_age_bars` provide default-off stale-order timeouts for submitted orders: pending OPEN / scale-in REBALANCE orders can expire either untouched or after a partial fill with the already-opened partial position preserved, while exit-like CLOSE / reduce REBALANCE orders can expire either untouched or after a partial fill with the realized trade and reduced position preserved. `EventDrivenBacktestResult.order_status_counts` includes those terminal canceled orders.
- `BacktestExecutionConfig.entry_spread_feature` and `exit_spread_feature` provide default-off order-book-spread execution adjustments for entry-like OPEN / scale-in REBALANCE fills and exit-like CLOSE / reduce REBALANCE / triggered stop-target fills, applying half-spread in the trade direction before the existing fixed-bps slippage model.
- BTC and generic event-preview payloads now serialize `terminalOrderCount` and `terminalOrders` from `EventDrivenBacktestResult.terminal_orders`, so API/dashboard consumers can inspect canceled or rejected terminal order details instead of only aggregate status counts.
- `EventDrivenBacktestResult.terminal_order_reason_counts` now aggregates terminal order reasons such as `entry_order_expired` and `exit_order_expired`; BTC/generic event-preview payloads serialize `terminalOrderReasonCounts`, and the dashboard renders those reason buckets in Event Order Status.
- Event-backtest REST routes can now pass explicit execution-simulation query parameters into `BacktestExecutionConfig`, including intrabar entry-limit and stop/target flags, fee/slippage settings, entry/exit partial-fill caps, entry/exit volume-participation caps, stale entry/exit order age, and optional entry/exit spread feature names.
- `EventDrivenBacktestResult.exposure_curve` now records per-event portfolio exposure snapshots marked with latest known prices, including long notional, short notional, gross notional, net notional, open risk, and position count for multi-symbol and long/short research runs.
- `EventDrivenBacktestResult.exposure_curve` now also includes `group_exposure` buckets keyed by `MarketSpec.correlation_group`, and BTC/generic preview payloads serialize them as `groupExposure` so the dashboard can show correlation-group gross exposure and open risk beside total portfolio exposure.
- `EventDrivenBacktestResult.exposure_curve` now also includes `symbol_exposure` buckets, and BTC/generic preview payloads serialize them as `symbolExposure` so the dashboard can show single-symbol gross exposure and open risk beside correlation-group exposure.
- `EventDrivenBacktestResult.exposure_curve` now also includes `layer_exposure` buckets, and BTC/generic preview payloads serialize them as `layerExposure` so the dashboard can show core/tactical or other portfolio-layer gross exposure and open risk beside symbol and correlation-group exposure.
- `EventDrivenBacktestResult.exposure_curve` now also includes `module_exposure` buckets, and BTC/generic preview payloads serialize them as `moduleExposure` so the dashboard can show which standardized signal modules are consuming gross exposure and open risk.
- `EventDrivenBacktestResult.exposure_curve` now also includes `exchange_exposure` and `market_type_exposure` buckets from `MarketSpec.exchange` and `MarketSpec.market_type`; BTC/generic preview payloads serialize them as `exchangeExposure` and `marketTypeExposure`, and the dashboard Event Exposure feed shows exchange and market-type gross exposure and open risk beside symbol/layer/module/correlation exposure.
- `BacktestExposureBucket`, `BacktestExposurePoint`, and `BacktestExposureSummary` are exported from the platform package, and `EventDrivenBacktestResult.exposure_summary` now derives peak position count, gross notional, absolute net notional, open risk, symbol gross notional, symbol open risk, layer gross notional, layer open risk, module gross notional, module open risk, group gross notional, group open risk, exchange gross notional, exchange open risk, market-type gross notional, market-type open risk, and the symbol/layer/module/correlation-group/exchange/market-type names responsible for those peaks from the exposure curve; BTC/generic preview payloads serialize it as `exposureSummary`, and the dashboard event summary cards show max gross exposure, max open risk, max symbol risk, max layer risk, max module risk, max group risk, max exchange risk, and max market type risk.
- `EventDrivenBacktestResult.performance_summary` now derives initial equity, final equity, total return, final unrealized PnL, realized PnL, fees, funding, max/min equity, max drawdown, return-to-max-drawdown, max drawdown duration, drawdown point count, time-in-drawdown, best/worst/average event returns, positive/negative event-return counts, event-return win rate, max positive/negative event-return streaks, average positive/negative event-return magnitude, event-return payoff ratio, event-return profit factor, event-return volatility, non-annualized event-return risk ratio, downside volatility, and Sortino ratio from the event equity curve; BTC/generic preview payloads serialize those fields in `summary`, and the dashboard event summary cards show total return, max drawdown, return-to-max-drawdown, max drawdown duration, time-in-drawdown, event-return extremes, event-return win rate, event-return streaks, event-return payoff ratio, event-return profit factor, event-return volatility, event-return risk ratio, downside volatility, and Sortino ratio beside realized PnL and exposure risk.
- `EventDrivenBacktestResult.performance_summary` now also derives trade count, win rate, average trade net PnL, average holding bars, realized trade notional, and realized turnover ratio from realized event trades; BTC/generic preview payloads serialize those fields in `summary`, and the dashboard event summary cards render them beside equity, drawdown, and exposure metrics.
- `EventDrivenBacktestResult.performance_summary` now also derives gross profit, gross loss, and profit factor from realized event trades; BTC/generic preview payloads serialize `grossProfit`, `grossLoss`, and `profitFactor`, and the dashboard event summary cards render them beside win rate and average trade metrics.
- `EventDrivenBacktestResult.performance_summary` now also derives average winning trade, average losing trade magnitude, and payoff ratio from realized event trades; BTC/generic preview payloads serialize `averageWinNetPnl`, `averageLossNetPnl`, and `payoffRatio`, and the dashboard event summary cards render them beside profit factor.
- `BacktestTrade` now carries entry/exit timestamps, entry/exit bar indexes, and holding bars for realized event-driven trades; BTC/generic preview payloads serialize those timing fields, and the Signal Pipeline dashboard renders holding duration in the Event Trades table.
- `BacktestAttributionBucket` now aggregates average realized holding bars for symbol, layer, and module attribution buckets; BTC/generic preview payloads serialize `averageHoldingBars`, and the Signal Pipeline dashboard renders it in Event Attribution.
- `BacktestAttributionBucket` now also aggregates realized trade notional, gross profit, gross loss, profit factor, average winning trade, average losing trade magnitude, and payoff ratio for each attribution bucket; BTC/generic preview payloads serialize those fields, and the Signal Pipeline dashboard renders Notional, PF, and Payoff columns in Event Attribution.
- `BacktestAttribution` now also groups realized trade performance by direction (`long` / `short`); BTC/generic preview payloads serialize `byDirection`, and the Signal Pipeline dashboard renders Direction rows in Event Attribution.
- `BacktestAttribution` now also groups realized trade performance by exit reason such as `target`, `stop`, `decrease_position`, and `opposite_signal_close`; BTC/generic preview payloads serialize `byExitReason`, and the Signal Pipeline dashboard renders Exit rows in Event Attribution.
- `BacktestAttribution` now also groups realized trade performance by `MarketSpec.exchange`, `MarketSpec.market_type`, and `MarketSpec.correlation_group`; BTC/generic preview payloads serialize `byExchange`, `byMarketType`, and `byCorrelationGroup`, and the Signal Pipeline dashboard renders Exchange, Market Type, and Correlation rows in Event Attribution.
- BTC/generic event-driven previews now serialize each `equityCurve` point with event return, current equity peak, drawdown amount, drawdown percent, and drawdown duration bars, making per-event return and underwater state visible beside cash, unrealized PnL, and total equity without changing legacy execution.
- The BTC event-driven backtest preview now serializes `exposureCurve` beside equity curve, realized trades, summary, and attribution, making portfolio exposure analytics available to dashboard/API consumers without changing legacy execution.
- The Signal Pipeline dashboard now renders the serialized event exposure curve as an Event Exposure feed, includes terminal order count in the event summary cards, and exposes entry-limit / stop-target-H-L / fee-rate / slippage-bps / stale-entry-age / stale-exit-age / entry-fill-cap / entry-volume-cap / exit-fill-cap / exit-volume-cap / entry-spread-feature / exit-spread-feature controls for event-backtest requests, making recent position count, long/short/gross/net notional, open risk, stale-order cancellations, partial-fill/participation assumptions, stop/target trigger assumptions, explicit cost assumptions, and spread-adjusted entry/exit research visible next to event equity and trades.

Remaining:

- Continue improving exchange fill simulation beyond intrabar stop/target triggers, spread-adjusted entries, partial fills, participation caps, and stale-order timeouts, and broaden portfolio analytics beyond the first exposure snapshots and realized trade attribution.
- Continue extending platform-order-plan execution from base/core-long/core-add/bear-probe/bear-confirm/bear-acceleration/tactical entries to the next `migrationReadiness`-ready legacy entry paths, preserving historical size semantics where the legacy runtime differs from platform quantity semantics.

### Phase 9: Signal Delivery

Status: started.

Signal delivery can target generated or verified TradingView outputs using one Python signal source of truth.

Implemented:

- `quant_platform/delivery.py`
- `quant_platform/delivery_config.py`
- `quant_platform/pine.py`
- `config/signal_delivery.example.json`
- `pine/compare_golden_vectors.py`
- `pine/signal_module_parity.py`
- `pine/examples/signal_module_parity.pine`
- `pine/examples/expected_vectors.json`
- `pine/examples/observed_template.csv`
- `DeliveryPayload`
- `DeliveryResult`
- `DeliveryConfigError`
- `InMemoryDeliveryChannel`
- `WebhookDeliveryChannel`
- `TelegramDeliveryChannel`
- `EmailDeliveryChannel`
- `build_delivery_channels()`
- `load_delivery_channels_json()`
- `PineGoldenVector`
- `write_pine_golden_vectors_json()`
- `load_pine_golden_vectors_json()`
- `load_pine_observations()`
- `compare_pine_golden_vectors()`
- `compare_pine_golden_vector_files()`
- `PineGenerationError`
- `generate_signal_module_pine()`
- `write_pine_script()`
- `write_signal_module_pine_parity_example()`
- `SignalPipeline`
- `tests/test_platform_delivery.py`
- `tests/test_platform_delivery_config.py`
- `tests/test_platform_pipeline.py`
- `tests/test_platform_pine.py`
- `tests/test_pine_golden_cli.py`
- `serve/signal_preview.py`
- `/api/signals/preview`
- `/api/signals/latest`
- `/api/signals/pipeline-preview`
- `tests/test_signal_preview_service.py`
- `tests/test_signal_preview_routes.py`
- `serve/static/js/pipeline.js`
- `tests/test_signal_pipeline_frontend.py`
- Delivery payloads now serialize standardized `Signal`, `RiskDecision`, and `PortfolioOrder` data for dashboard/API use.
- Webhook, Telegram, and email channels use injected transports so delivery is testable without hardcoded network credentials.
- Delivery channels can now be constructed from secret-safe config mappings or JSON files; webhook URLs, webhook auth headers, and Telegram credentials are resolved from environment variables at runtime instead of committed literals.
- Pine golden vectors can be generated from platform orders to support future Python/Pine signal consistency checks.
- Pine observations exported from TradingView can now be compared against platform `PineGoldenVector` rows with field-level mismatch messages for entry, stop, target, and score.
- Python expected Pine golden-vector artifacts can now be written/read as JSON and compared with TradingView/Pine observed CSV or JSON exports through `compare_pine_golden_vector_files()`, creating a deterministic CI boundary for Python/Pine parity.
- `python -m pine.compare_golden_vectors --expected ... --observed ...` now exposes the golden-vector comparator as a CI-friendly command with stable success output, mismatch exit code `1`, and UTF-8 BOM tolerance for PowerShell-exported files.
- `generate_signal_module_pine()` can now render a Pine v6 indicator from platform signal-module configuration, covering `BreakoutSignalConfig`, `PullbackSignalConfig`, `MeanReversionSignalConfig`, `SweepReversalSignalConfig`, `CrashShortSignalConfig`, `FailedBounceSignalConfig`, and `BullTrapSignalConfig`; generated scripts carry the Python timeframe, score settings, and dynamic alert rows compatible with the golden-vector observation schema.
- `write_signal_module_pine_parity_example()` now creates reproducible `pine/examples` artifacts: a generated Pine script, Python expected golden vectors, and an observation CSV template covering the current direct-compute signal modules.
- `python -m pine.signal_module_parity` now provides a manual/CI workflow that regenerates the parity example artifacts and optionally compares a supplied TradingView/Pine observed CSV or JSON export against the regenerated Python expected vectors.
- `write_signal_module_pine_parity_example(config_path=...)` and `python -m pine.signal_module_parity --config ...` can now generate both the Pine script and expected golden vectors from the same JSON signal-module config used by generic research previews, with optional module-set selection and timeframe injection.
- Standardized signal output can now be passed through risk, portfolio, and delivery layers in one platform pipeline.
- The Signal Pipeline dashboard now renders each signal's `required_data` dependencies in the Signals table, making standardized SignalModule data requirements visible without inspecting raw JSON payloads.
- `SignalPipeline` now carries `RiskBudgetDiagnostics`, and BTC/generic preview payloads expose `riskDiagnostics` beside signals, risk decisions, orders, and deliveries.
- The Signal Pipeline dashboard now renders `riskDiagnostics` as portfolio, symbol, module, correlation-group, exchange, and market-type risk usage rows.
- `/api/signals/latest` now exposes a read-only latest BTC standardized `SignalPipeline` snapshot with signals, risk decisions, portfolio orders, dashboard delivery payloads, and risk diagnostics without changing trade execution.
- The visualization server now exposes a read-only BTC standardized signal preview REST endpoint without changing trade execution.
- BTC standardized preview signals now include preferred stop/target values and have focused coverage showing they can pass through `RiskEngine`, `PortfolioEngine`, and in-memory dashboard delivery.
- The visualization server now also exposes a read-only BTC `SignalPipeline` preview REST endpoint with serialized signals, risk decisions, portfolio orders, and dashboard delivery payloads.
- `get_signal_research_preview()` provides a generic read-only preview entry point that resolves configured `MarketSpec` and `RegimeProfile` records, accepts injectable OHLCV/feature/signal builders, and routes resulting standardized signals through `RiskEngine`, `PortfolioEngine`, and dashboard delivery.
- Generic research preview and event-backtest responses now expose latest regime classification beside `regimeProfile`, so consumers can distinguish configured regime assumptions from the current classified market state.
- The Signal Pipeline dashboard now renders that latest regime classification in a Regime feed, including single-market `latestRegime` and multi-market `latestRegimes` payloads.
- `/api/signals/research-preview` exposes the generic preview boundary with `symbol`, `exchange`, and `market_type` parameters while leaving existing BTC-specific preview routes intact.
- Generic research previews now default to `load_research_preview_bars()`, which keeps the BTC cached-bar fallback but loads configured non-BTC bars through `DataConnectorRegistry` and `config/research_data_sources.json`, using route-selected Parquet or SQLite bar cache storage.
- Generic research preview and research event-backtest endpoints now expose `refresh_bars=true` beside `refresh_features=true`, giving API callers separate control over DataConnector-to-BarStore refresh and FeatureEngine-to-FeatureStore refresh.
- Generic research previews now default to the direct-compute `BreakoutSignalModule`, `PullbackSignalModule`, `MeanReversionSignalModule`, `SweepReversalSignalModule`, `CrashShortSignalModule`, `FailedBounceSignalModule`, and `BullTrapSignalModule` when no custom signal generator is injected, so configured non-BTC OHLCV can flow through signal, risk, portfolio, and delivery layers.
- Generic research previews and event-backtest previews now resolve those default direct-compute modules from `config/research_signal_modules.json` when present, giving Python research workflows a project-level signal-module configuration source before generated Pine and service defaults are fully unified.
- The Pine parity workflow can now consume that same `config/research_signal_modules.json` module set, so Python preview signals, generated Pine, and expected golden vectors share one project-level signal-module configuration source.
- The `SignalPipeline` dashboard now renders normalized portfolio order entry, stop, and target prices from the REST payload, making `MarketSpec` tick/lot effects visible in the frontend.
- The `SignalPipeline` dashboard now has symbol, exchange, and market-type selectors; BTC/Binance/swap keeps using compatibility preview and migration comparison routes, while configured non-BTC markets use generic research preview and research event-backtest routes.
- The `SignalPipeline` dashboard selectors now allow multiple selected symbols, exchanges, and market types; generic event-backtest requests serialize those selections into the existing comma-separated multi-market query format, while the single-bar preview still summarizes the first selected market.
- `/api/signals/markets` now exposes the configured `MarketSpec` catalog as read-only selector metadata, and the `SignalPipeline` dashboard loads that API to populate symbol, exchange, and market-type options instead of relying on hardcoded BTC/AAPL choices.
- `/api/signals/markets` and market payloads now expose structured session metadata (`sessionTimezone`, `sessionOpen`, `sessionClose`, `tradingDays`) so dashboard/API consumers can distinguish 24/7 crypto markets from regular-session equities without parsing an opaque label.
- `/api/signals/markets` and market payloads now expose `correlationGroup`, making market-configured risk grouping visible to dashboard/API consumers beside session and tradability metadata.
- `/api/signals/markets` and market payloads now expose `maxLeverage`, making market-level leverage capability visible to dashboard/API consumers beside the account-level risk cap.
- The `SignalPipeline` dashboard now renders that structured session metadata and market constraints in a Market Session feed for the currently selected configured markets, so multi-market research selections expose their timezone, hours, trading days, tick/lot sizes, fee/funding rates, contract multiplier, short/leverage support, and max leverage beside the rest of the pipeline diagnostics.
- The `SignalPipeline` dashboard now exposes cache refresh controls for generic research runs, passing `refresh_bars` and `refresh_features` through preview and event-backtest requests so UI users can explicitly refresh BarStore and FeatureStore data when needed.
- The visualization server now exposes a read-only BTC event-driven backtest preview REST endpoint that runs standardized signals through `SignalPipeline` and `EventDrivenBacktest`, returning equity curve, realized trades, summary, and attribution without replacing the legacy historical backtest.
- The BTC event-driven backtest preview REST payload now includes `exposureCurve` rows with long, short, gross, net, open-risk, and position-count snapshots from the platform event-driven engine.
- The Signal Pipeline dashboard now renders those `exposureCurve` rows in an Event Exposure panel, so portfolio exposure analytics are visible without inspecting raw JSON.
- The visualization server now also exposes `/api/signals/research-event-backtest-preview`, a generic read-only event-driven backtest endpoint that accepts `symbol`, `exchange`, and `market_type`, resolves configured market/regime records, and returns orders, realized trades, equity curve, exposure curve, and attribution for non-BTC research markets.
- Generic research event-backtest previews now share the default cached non-BTC FeatureEngine path with `/api/signals/research-preview`, including explicit `refresh_features` control when callers need to bypass cached features.
- The same endpoint now also accepts comma-separated or repeated `symbol`, `exchange`, and `market_type` query values for multi-market research event backtests, returning `symbols`, per-symbol `markets`, per-symbol `regimeProfiles`, portfolio equity/exposure curves, and realized-trade attribution from a single event run.
- The visualization server now exposes a read-only BTC migration comparison endpoint that reports legacy cached summary/trade-log metrics beside event-driven preview metrics and deltas.
- The frontend now includes a read-only Signal Pipeline dashboard module that renders the pipeline preview API, event-driven backtest preview, and migration comparison deltas side-by-side without altering trade execution.
- The Signal Pipeline dashboard now renders `riskAudit` summary counts and recent audit rows in the migration comparison view, so platform RiskEngine parity review is visible outside raw API responses.
- The Signal Pipeline dashboard now renders `pipelineAudit` summary counts and recent pipeline snapshot rows in the migration comparison view, so strategy-class-to-platform order-plan parity is visible outside raw API responses.
- The Signal Pipeline dashboard now renders `orderParity` mismatch counts and module-level parity rows in the migration comparison view, so legacy-vs-event order-plan parity is visible outside raw API responses.
- The Signal Pipeline dashboard now renders `migrationReadiness` module status and reasons in the migration comparison view, so the next execution-migration candidates are explicit instead of inferred from raw audit tables.
- `PortfolioEngine.close_position()` now applies `MarketSpec.lot_size` quantization to explicit partial-close quantities before creating the filled `CLOSE` order and scaling the remaining position, while full closes still close the current position quantity exactly.
- BTC base, weighted legacy, core-long, core pullback-add, bear-core probe/confirm/acceleration, tactical, and flash-crash dip-buy entry execution now consume the recorded platform order plan for direction, stop, and target, keeping size in legacy fractional form until the execution engine itself migrates away from backtesting.py semantics. Base partial/full exits, weighted legacy opposite-signal closes, plus dual-layer core, tactical, and bear-core full or partial exits now also produce platform `CLOSE` order audits beside unchanged legacy close execution.

Remaining:

- Add more generic direct-compute signal modules only as concrete research needs arise, keeping BTC compatibility modules as adapters until strategy-class reads migrate to `SignalPipeline`.
- Use module-level `migrationReadiness` to migrate the remaining BTC compatibility entry and exit flows to `SignalPipeline` order plans without changing historical signal behavior.
- Replace the Pine example observation template with real TradingView alert/export observations when running the parity workflow in CI or a manual release check.

## Invariants During Migration

- Existing BTC strategy behavior must remain runnable while contracts are added.
- New platform code must not import `quant_btc.strategy`.
- Signal modules should not own exchange fetching, storage, portfolio state, or delivery.
- Secrets must stay out of source files.

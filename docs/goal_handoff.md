# Goal Handoff: Generic Trading Signal Research Platform

Last updated: 2026-06-11

## Active Goal

Continue refactoring the project from a BTC strategy script collection into a generic trading signal research and alerting platform.

The target platform layers are:

- `AssetSpec` / `MarketSpec`
- `DataConnector`
- `BarStore` / `FeatureStore`
- `FeatureEngine`
- `RegimeModel`
- `SignalModule`
- `RiskEngine`
- `PortfolioEngine`
- `SignalDelivery`

The full structured migration record lives in `docs/platform_migration.md`.

## Current Status

The goal is in progress, not complete.

The repository now has a generic `quant_platform/` package with platform contracts and partial implementations for all target layers. BTC compatibility behavior is intentionally preserved while generic boundaries are added.

Recent progress:

- Project market specs are now configurable through `config/markets.json`.
- `MarketCatalog` can load/save JSON market records.
- The signal preview service exposes `resolve_market_spec(symbol, exchange, market_type)`.
- `config/markets.json` includes BTC/USDT Binance swap and a non-BTC AAPL/NASDAQ equity example.
- `MarketSpec` now carries structured trading-session metadata (`session_timezone`, `session_open`, `session_close`, `trading_days`) in addition to the legacy `trading_session` label, and project market JSON plus `/api/signals/markets` preserve those fields.
- `MarketSpec.is_trading_time()` can evaluate configured market sessions against UTC timestamps, and generic intraday research bar loading filters rows through that session boundary before feature, signal, risk, portfolio, and event layers run.
- `MarketSpec` now carries an optional `correlation_group`; project market JSON and `/api/signals/markets` preserve it, and `RiskEngine` uses it as the default correlation-budget group when `RiskLimits.correlation_groups` does not override the symbol.
- `MarketSpec` now carries optional `max_leverage`; project market JSON and `/api/signals/markets` preserve it, and `RiskEngine` caps leveraged notional exposure at the lower of account-level `RiskLimits.max_leverage` and the market-level maximum.
- The Signal Pipeline dashboard now renders configured market session metadata and tradability constraints in a Market Session feed, including session hours, trading days, tick size, lot size, fee/funding rates, contract multiplier, short support, leverage support, and max leverage when present.
- Regime profiles are now configurable through `config/regime_profiles.json`.
- `RegimeProfileRegistry` can load JSON profile config through `load_regime_profile_registry_json()`.
- The signal preview service exposes `resolve_regime_profile(market)`.
- Non-BTC regime profile resolution is covered by tests for AAPL/NASDAQ equity.
- Generic research preview and event-backtest payloads now include the latest `RegimeModel` classification (`latestRegime` for single-market runs and `latestRegimes` for multi-market event runs), so API/dashboard callers can see the resolved market state produced from each asset's `RegimeProfile` instead of only the profile metadata.
- The Signal Pipeline dashboard now renders those `latestRegime` / `latestRegimes` payloads in a Regime feed, making generic research market-state classification visible beside signal, risk, order, and event analytics.
- `get_signal_research_preview()` can run a generic read-only `SignalPipeline` for any configured market with injectable bar, feature, and signal builders.
- `/api/signals/research-preview` accepts `symbol`, `exchange`, and `market_type` so dashboard/API callers are no longer limited to BTC-specific preview helpers.
- `/api/signals/research-event-backtest-preview` accepts `symbol`, `exchange`, and `market_type` and runs a generic event-driven research backtest with configured market and regime metadata, so non-BTC assets can now use the platform event engine instead of the BTC-only event preview path.
- `load_data_connector_registry_json()` can build configured CSV/SQLite connector registries for research data sources.
- `load_data_connector_registry_json()` can register `type: "ccxt"` exchange adapters from JSON config, so Binance, Bybit, OKX, and other CCXT-backed exchanges can enter research data flows through `MarketSpec.exchange` instead of strategy code.
- `CcxtExchangeConnector` can fetch a normalized single order-book snapshot through `fetch_order_book_snapshots()`, mapping platform `depth` to CCXT order-book depth and returning level-by-level bid/ask columns plus spread.
- `YahooFinanceConnector` can fetch normalized OHLCV bars from Yahoo Finance chart responses through the generic `DataConnector` interface, and JSON connector config can now register `type: "yahoo"` adapters with explicit symbol mappings.
- `AlphaVantageConnector` can fetch normalized daily and intraday OHLCV bars from Alpha Vantage time-series responses through the generic `DataConnector` interface; JSON config registers it with `type: "alpha_vantage"` and requires runtime `api_key_env` instead of inline secrets.
- `PolygonConnector` can fetch normalized aggregate OHLCV bars from Polygon.io responses through the generic `DataConnector` interface; JSON config registers it with `type: "polygon"` and requires runtime `api_key_env` instead of inline secrets.
- `fetch_bars_with_cache()` provides a generic DataConnector-to-BarStore boundary: any connector can now read normalized bars from a `BarStore` first, fetch on cache miss or refresh, and write fetched bars back through the same `BarSeriesId` key instead of relying on BTC-specific pickle cache logic.
- `fetch_derivatives_with_cache()` now provides the same generic DataConnector-to-DerivativeStore boundary for funding/open-interest frames, and BTC derivative remote fetches use it while preserving the existing Parquet-before-pickle read fallback.
- Generic research preview bar loading now uses `fetch_bars_with_cache()` with a `ParquetBarStore` under `data/research_bars`, so configured non-BTC sources can share the same BarStore-first cache boundary as the platform connector layer.
- Generic intraday research preview/event-backtest bar loading now filters configured non-BTC bars by `MarketSpec.is_trading_time()`, so regular-session markets can drop after-hours and non-trading-day rows before FeatureEngine execution while BTC 24/7 compatibility remains unchanged.
- Generic research preview and research event-backtest callers can now pass `refresh_bars=true` through the API or `refresh_bars=True` through the service functions to bypass BarStore hits and refresh configured non-BTC research bars before feature generation.
- Generic research previews now default to a cached `FeatureEngine` run for non-BTC markets, writing technical, Donchian, volume, volatility, Bollinger, and price-action feature output through `ParquetFeatureStore(data/research_features)` before signal, risk, portfolio, and delivery layers run.
- Generic swap/futures research feature runs can now load configured funding/open-interest data through the generic `DataConnector` to `DerivativeStore` cache boundary, append `DerivativesFeatureModule` output, and isolate derivative-enabled FeatureStore keys from OHLCV-only caches.
- Generic swap/futures research feature runs now treat unavailable derivative adapters or derivative storage as optional: the default feature builder falls back to OHLCV-only features instead of failing the research preview.
- `OrderBookFeatureModule` can align normalized order-book snapshots to OHLCV bars and derive best bid/ask, spread, mid, relative spread, depth-size sums, and imbalance features without putting order-book logic into signal modules.
- Generic research feature runs can now load configured order-book snapshot routes through the generic `DataConnector` to `OrderBookStore` cache boundary, append `OrderBookFeatureModule` output, and isolate depth-enabled FeatureStore keys from OHLCV-only caches.
- `FeatureModuleRegistry` and `default_feature_module_registry()` can now build a `FeatureEngine` from JSON-like feature module records for config-only modules such as technical indicators, Donchian, volume, volatility, Bollinger, and price action.
- `run_feature_engine_with_cache()` now reads existing FeatureStore output before recomputing when a read-capable store is provided, so generic research previews can reuse persisted feature frames on cache hits instead of always recalculating.
- Generic research preview callers can pass `refresh_features=true` through `/api/signals/research-preview` or `refresh_features=True` through the service function to force the default non-BTC feature builder to recompute and rewrite FeatureStore output instead of using a cache hit.
- Generic research preview payloads now expose `featureCache` metadata from the default FeatureStore-backed feature run, so API/dashboard callers can distinguish cache hits, refresh writes, and injected feature-builder runs.
- The Signal Pipeline dashboard now renders the generic research preview `featureCache` payload in a Feature Cache feed, making FeatureStore hit/write state visible next to risk, signal, order, and regime panels.
- Generic research event-backtest previews now use the same default cached `FeatureEngine` path and `refresh_features` control as single-bar research previews, so non-BTC research runs share one FeatureStore boundary before event-driven simulation.
- Generic research event-backtest payloads now expose per-symbol `featureCaches` metadata, so single- and multi-market event runs can audit which FeatureStore entries were hit or refreshed before portfolio simulation.
- The Signal Pipeline dashboard now renders generic research event-backtest `featureCaches` in an Event Feature Cache feed, making per-symbol FeatureStore hit/write state visible beside event trades, equity, exposure, order status, and attribution.
- BTC and generic research event-backtest payloads now expose `finalPortfolio` from the event-driven `PortfolioEngine` state, including final open positions and open risk, and the Signal Pipeline dashboard renders that state in a Final Portfolio table.
- `SQLiteBarStore` now preserves optional `Turnover` columns for normalized bar series and upgrades existing OHLCV-only SQLite bar tables in place when turnover-backed bars are written.
- `OrderBookSeriesId`, `ParquetOrderBookStore`, and `SQLiteOrderBookStore` now provide a first platform storage boundary for normalized order-book snapshots keyed by symbol, exchange, market type, depth, sample interval, and source.
- `DataConnector` / `DataConnectorRegistry` can now expose optional normalized order-book snapshot fetches, and `fetch_order_book_snapshots_with_cache()` provides the matching DataConnector-to-OrderBookStore cache boundary.
- Generic research FeatureStore keys now include the resolved `RegimeProfile` default feature parameters for trend EMA, ATR, ADX, and Bollinger bands, so asset/profile-specific default features such as `ema50`, `_atr_10`, `_adx_21`, and `bb_upper_30` cannot collide under the same persisted `research_default_v1` feature set.
- Generic research event-backtest previews can now accept multiple configured markets in one request, run their feature streams through a single `EventDrivenBacktest` and `PortfolioEngine`, and return multi-symbol market/regime metadata, orders, trades, equity curve, exposure curve, and attribution.
- `config/research_data_sources.json` maps the AAPL/NASDAQ equity example to a local CSV source, and generic research previews can now load those non-BTC bars by default.
- `BreakoutSignalModule` is now a direct-compute generic `SignalModule` that emits current-bar Donchian breakout signals from OHLCV without legacy boolean signal columns.
- `PullbackSignalModule` is now a direct-compute generic `SignalModule` that emits current-bar EMA pullback continuation signals from OHLCV without mutating input bars.
- `MeanReversionSignalModule` is now a direct-compute generic `SignalModule` that emits current-bar rolling-band reclaim signals from OHLCV without mutating input bars.
- `SweepReversalSignalModule` is now a direct-compute generic `SignalModule` that emits current-bar range sweep-and-reclaim signals from OHLCV without mutating input bars.
- `CrashShortSignalModule` is now a direct-compute generic `SignalModule` that emits current-bar crash impulse short signals from OHLCV with volume confirmation and without mutating input bars.
- `FailedBounceSignalModule` is now a direct-compute generic `SignalModule` that emits current-bar failed bounce short signals from OHLCV without mutating input bars.
- `BullTrapSignalModule` is now a direct-compute generic `SignalModule` that emits current-bar bull trap short signals from OHLCV with breakout-volume confirmation and without mutating input bars.
- Generic research previews default to the direct-compute breakout, pullback, mean-reversion, sweep-reversal, crash-short, failed-bounce, and bull-trap modules when no custom signal generator is injected, so the AAPL/NASDAQ example can flow through signal, risk, portfolio, and delivery layers.
- `SignalModuleRegistry` and `default_signal_module_registry()` can now build a `SignalModuleRunner` from JSON-like signal module records, covering the column adapter plus direct-compute breakout, pullback, mean-reversion, sweep-reversal, crash-short, failed-bounce, and bull-trap modules.
- `config/research_signal_modules.json` now defines the default generic research signal module set, and generic research preview/event-backtest flows load matching module sets through `SignalModuleRegistry` before falling back to the legacy hardcoded default list.
- The Signal Pipeline dashboard now renders each standardized signal's `required_data` dependencies in the Signals table, so module data requirements are visible beside module, direction, score, stop, and target.
- `RiskBudgetDiagnostics` now reports portfolio, symbol, module, and correlation-group risk budget usage from `RiskEngine`, and `SignalPipeline` / preview payloads expose the same snapshot after portfolio planning.
- The Signal Pipeline dashboard now renders `riskDiagnostics` as a risk-budget table, making portfolio, symbol, module, and correlation-group budget usage visible in the frontend.
- `RiskEngine` can now derive a symbol's default correlation risk group from `MarketSpec.correlation_group`, so multi-asset research portfolios can keep correlation exposure configuration with market metadata instead of requiring every caller to duplicate `RiskLimits.correlation_groups`.
- `SignalPipeline` now uses the same `RiskEngine` correlation-group resolver for existing portfolio positions, batch-level allowed decisions, and diagnostics, so `MarketSpec.correlation_group` participates in portfolio correlation budgets beyond isolated `RiskEngine.evaluate()` calls.
- `SignalPipeline` now prioritizes same-batch standardized signals by score before risk-budget evaluation, so a lower-score same-symbol/same-layer candidate cannot consume the only available risk budget before the stronger candidate reaches `PortfolioEngine` conflict resolution.
- `RiskEngine` can now apply market-level leverage caps from `MarketSpec.max_leverage`, allowing futures/swap markets to carry exchange-specific leverage capability while the global risk limit remains the account-level ceiling.
- `RiskEngine` and `PortfolioEngine` now apply `MarketSpec.contract_multiplier` when sizing futures/swap-like contracts and calculating position notional, so configured contract markets no longer treat contract quantity as spot units.
- `RiskEngine` now checks portfolio, symbol, module, and correlation-group risk budgets against the candidate's actual capped `risk_amount` after notional, leverage, and contract constraints are applied, so constrained markets are not rejected by a larger pre-cap target risk.
- Generic `RiskEngine` now supports a default-off portfolio maximum drawdown gate through `RiskLimits.max_drawdown_pct` and `RiskState.equity_peak`; the engine observes account equity during evaluation to maintain the peak, blocks new risk with `max_drawdown_limit` when the threshold is breached, and exposes current drawdown, threshold, and breach state through `riskDiagnostics.drawdown`.
- `EventDrivenBacktest` now passes mark-to-market account equity into each `SignalPipeline` evaluation, so `RiskEngine` drawdown limits can block later multi-symbol signals after realized or unrealized portfolio losses instead of using only the initial account equity.
- `EventDrivenBacktest` now records realized trade `net_pnl` back into `RiskState`, so consecutive-loss size reduction and pause rules affect later event-driven signals instead of staying isolated to direct `RiskEngine` unit tests.
- `/api/signals/latest` now exposes a read-only latest BTC standardized `SignalPipeline` snapshot with signals, risk decisions, portfolio orders, dashboard delivery payloads, and risk diagnostics without changing trade execution.
- BTC base strategy entry selection now goes through `select_btc_base_entry_signal()`, producing a standardized compatibility `Signal` before `BaseRiskStrategy` applies the existing stop, size, and order logic.
- BTC weighted legacy entry selection now goes through `select_btc_weighted_legacy_signal()`, producing a standardized compatibility `Signal` before `WeightedSignalStrategy` applies the existing 95% fractional size and opposite-signal exit behavior.
- BTC dual-layer tactical entry selection now goes through `select_btc_tactical_signal()`, producing a standardized compatibility `Signal` before `DualLayerStrategy` applies the existing tactical stop, size, state, and order logic.
- BTC core-long entry, core pullback add, and bear-core stage-1 probe selection now go through standardized compatibility `Signal` helpers before `DualLayerStrategy` applies the existing layer state and order logic.
- BTC bear-core stage-2 confirmation add and stage-3 acceleration add selection now go through standardized compatibility `Signal` helpers before `DualLayerStrategy` applies the existing add-size, group-exposure, state, and order logic.
- `build_btc_legacy_entry_risk_decision()` can now convert a legacy BTC fractional entry plan into a read-only platform `RiskDecision` audit object, and that decision can flow into `PortfolioEngine` to produce a standard order plan without replacing legacy execution.
- `SignalPipeline.run_decisions()` can now consume precomputed `RiskDecision` objects, so BTC legacy entry audit decisions can flow through the same PortfolioEngine, delivery, and risk-diagnostics result shape without re-running signal selection or changing strategy-class order execution.
- BTC base strategy entries, weighted legacy entries, dual-layer tactical entries, flash-crash dip-buy entries, core-long entries, core pullback adds, and bear-core probe/confirm/acceleration entries now record the corresponding legacy fractional entry as `_last_platform_risk_decision`, so strategy-class entry paths consume a platform `RiskDecision` audit object while preserving existing buy/sell execution.
- Those strategy-class entry paths now also record `_last_platform_pipeline_result` from `SignalPipeline.run_decisions()` for the confirmed legacy `RiskDecision`, giving migration audits a standard signals/risk-decisions/portfolio-plan/risk-diagnostics snapshot without changing legacy order execution.
- Strategy-class entry paths now append each read-only pipeline snapshot to `_platform_pipeline_results`, and the migration comparison service/API exposes them as a `pipelineAudit` payload with signals, risk decisions, portfolio orders, and risk diagnostics.
- `WeightedSignalStrategy` now also records a read-only `SignalPipeline` snapshot for opposite-signal legacy closes, using `PortfolioEngine(close_on_opposite_signal=True)` to produce a platform `CLOSE` order audit while preserving the existing `position.close()` execution path.
- `BaseRiskStrategy` partial take-profit and full-position exits now record read-only platform `CLOSE` order audits before the legacy close side effect runs, covering partial take-profit, time stop, invalidation, trailing-stop, and extra-exit paths.
- `DualLayerStrategy` core, tactical, and bear-core exits now record read-only platform `CLOSE` order audits before the legacy close side effects run, including bear-core V-reversal, giveback, waterfall guard, waterfall runner, and trend exits, so those exit flows start appearing in the same `pipelineAudit` result shape as migrated entries.
- The same confirmed BTC base, weighted legacy, tactical, flash-crash dip-buy, core-long, core pullback-add, and bear-core probe/confirm/acceleration entries now also record `_last_platform_risk_engine_decision`, produced by the generic `RiskEngine.evaluate()` from the legacy fractional risk amount, giving strategy-class paths a read-only RiskEngine parity check before enforcement is enabled.
- BTC base, weighted legacy, tactical, flash-crash dip-buy, core-long, core pullback-add, and bear-core probe/confirm/acceleration strategy entries now have a default-off `_ENFORCE_PLATFORM_RISK_ENGINE` switch; when explicitly enabled with an injected platform `RiskEngine`, blocked platform decisions stop the legacy entry before order/state mutation, while the default historical execution path stays unchanged.
- `BtcLegacyRiskAudit` now provides a serializable parity surface for each recorded legacy/platform risk pair, including `parity_status`, sizing deltas, engine block reason, and `would_block_if_enforced`; strategy classes append these snapshots to `_platform_risk_audits` without changing execution.
- The read-only migration comparison service/API now exposes a stable `riskAudit` payload with audit rows, parity-status counts, mismatch count, and would-block-if-enforced count so platform RiskEngine parity can be reviewed beside legacy-vs-event backtest deltas.
- The migration comparison service now defaults `riskAudit` to the real legacy dual-layer backtest `_platform_risk_audits` collection when the legacy `FractionalBacktest` runtime is available, while lightweight environments without that runtime keep returning an empty audit payload instead of failing.
- The Signal Pipeline dashboard now renders migration `riskAudit` counts and audit rows beside legacy-vs-event deltas, making platform RiskEngine parity review visible in the frontend.
- The Signal Pipeline dashboard now also renders migration `pipelineAudit` counts and recent pipeline snapshot rows beside legacy-vs-event deltas, making strategy-class-to-platform pipeline parity visible outside raw API responses.
- The BTC event-driven preview now serializes platform orders, and migration comparison exposes an `orderParity` payload comparing legacy strategy-class pipeline orders against event-driven platform orders by action, symbol, layer, direction, module, quantity, entry, stop, and target.
- `orderParity` now also exposes module-level `byModule` counts for legacy orders, event orders, matched orders, and mismatches, while keeping global missing/extra order details for deeper inspection.
- The Signal Pipeline dashboard now renders `orderParity` mismatch counts and module-level parity rows, so legacy-vs-event order-plan parity can be reviewed before replacing historical execution.
- Migration comparison now derives a conservative `migrationReadiness` payload from `riskAudit`, `pipelineAudit`, and `orderParity`, marking modules ready only when risk parity, pipeline/order audit evidence, and order parity all pass.
- The Signal Pipeline dashboard now renders module-level migration readiness status and reasons, turning the audit payloads into an explicit decision surface for choosing which legacy entry paths can migrate next.
- `PortfolioEngine` now has an explicit `rebalance_existing` mode that can turn a same-symbol, same-layer, same-direction higher target quantity into a `REBALANCE` order while keeping the default `position_exists` behavior unchanged.
- Filled `REBALANCE` orders now update the existing position's quantity, notional, weighted entry price, risk amount, stop, and target, closing the basic same-direction rebalance execution-state loop.
- Same-direction `REBALANCE` now also supports lower target quantities: the engine submits a `decrease_position` rebalance order and filled reductions scale the existing position quantity, notional, and risk amount down to the approved target.
- `PortfolioEngine` now has a default-off `close_on_opposite_signal` mode: when enabled, an opposite same-symbol/same-layer signal submits a `CLOSE` order for the existing position, and submitted close fills shrink or remove the position through the normal order-state path.
- `PortfolioEngine.close_position()` now applies `MarketSpec.lot_size` quantization to explicit partial-close quantities before creating the filled `CLOSE` order and scaling the remaining position, while full closes still close the current position quantity exactly.
- `EventDrivenBacktest` now fills pipeline-submitted `CLOSE` orders, records them as realized trades, and accounts realized PnL plus exit fees without double-counting open-order fees, so `close_on_opposite_signal` can flow through backtest execution instead of stopping at the portfolio plan.
- `EventDrivenBacktest` now also fills submitted `REBALANCE` orders, allowing same-direction scale-in plans from `PortfolioEngine(rebalance_existing=True)` to update position quantity, weighted entry, fees, and equity during event-driven runs.
- Partial-reduce `REBALANCE` fills now produce realized `BacktestTrade` rows and realized PnL in `EventDrivenBacktest`, with decrease-position fills treated as exits for fee and attribution accounting.
- `PortfolioEngine` now has a default-off `reverse_on_opposite_signal` mode that plans one-step same-layer reversals as ordered `CLOSE` then `OPEN` orders, and `EventDrivenBacktest` can fill that sequence on the same event while recording the closed leg as a realized trade and leaving the new direction open.
- `PortfolioEngine` now has a default-off `transfer_existing_layer` mode that can move one same-symbol, same-direction position from another layer into the incoming signal's target layer via an internal filled `TRANSFER` order, giving core/tactical layer management an explicit state transition instead of forcing a second position.
- `EventDrivenBacktest` now includes filled internal `TRANSFER` orders in `filled_orders`, so layer-transfer state changes are visible in event-driven research/audit outputs instead of only being reflected in the final `PortfolioState`.
- BTC and generic event-preview payloads now expose `filledOrderCount` and `filledOrders` from `EventDrivenBacktestResult.filled_orders`, separating planned order intent from execution fill state for API/dashboard consumers.
- `EventDrivenBacktestResult.order_status_counts` now aggregates effective order states after fills override submitted plans, and BTC/generic event-preview payloads serialize `orderStatusCounts` for planned, submitted, partially filled, filled, canceled, and rejected orders.
- `EventDrivenBacktestResult.order_action_counts` now aggregates effective order actions after fills/terminal states override submitted plans, and BTC/generic event-preview payloads serialize `orderActionCounts` for open, close, rebalance, transfer, and ignore orders.
- `EventDrivenBacktestResult.order_module_counts` now aggregates effective orders by their originating `SignalModule`, and BTC/generic event-preview payloads serialize `orderModuleCounts` so module-level order churn is visible before realized trades exist.
- `EventDrivenBacktestResult.order_symbol_counts` and `order_layer_counts` now aggregate effective orders by symbol and portfolio layer; BTC/generic event-preview payloads serialize `orderSymbolCounts` and `orderLayerCounts` so multi-symbol and core/tactical order concentration is visible before positions are closed.
- The Signal Pipeline dashboard now renders event order counts, symbol/layer/module buckets, action buckets from `orderActionCounts`, and status buckets from `orderStatusCounts`, making submitted-versus-filled order-state audits and symbol/layer/module/action mix visible beside event trades, equity, exposure, and attribution.
- `BacktestExecutionConfig.intrabar_stop_target` adds an optional High/Low-based stop/target fill mode for `EventDrivenBacktest`, so research runs can fill exits at the configured stop or target price when the current bar range touches it while the default close-only compatibility mode stays unchanged.
- `BacktestExecutionConfig.intrabar_entry_limit` adds a default-off High/Low entry-touch mode for `EventDrivenBacktest`: entry-like OPEN and scale-in REBALANCE orders fill at the order entry price only when the current bar range touches it; otherwise the order stays submitted and any compatibility pre-created OPEN position is removed.
- `EventDrivenBacktest` now re-evaluates existing submitted and partially filled orders for the current symbol on later bars, so an untouched `intrabar_entry_limit` order can remain pending and fill when a subsequent bar range reaches its entry price.
- `BacktestExecutionConfig.max_entry_fill_fraction_per_bar` adds a default-off per-bar fill cap for entry-like submitted orders, allowing event-driven research runs to model `PARTIALLY_FILLED` OPEN / scale-in REBALANCE orders across bars while default runs still fill the remaining order quantity immediately.
- `BacktestExecutionConfig.max_entry_volume_fraction_per_bar` adds a default-off bar-volume participation cap for entry-like submitted orders, allowing fills to be limited by `Volume * fraction` when bar volume is available while preserving existing behavior for bars without `Volume`.
- `BacktestExecutionConfig.max_exit_fill_fraction_per_bar` and `max_exit_volume_fraction_per_bar` add matching default-off fill caps for exit-like submitted CLOSE / reduce REBALANCE orders and triggered stop/target exits, recording per-bar realized trades from incremental exit fills while keeping submitted order state cumulative.
- `BacktestExecutionConfig.max_entry_order_age_bars` and `max_exit_order_age_bars` add default-off stale-order timeouts for event-driven research runs: untouched entry-like orders can expire, and exit-like orders can expire either untouched or after a partial fill with the already-realized trade and reduced position preserved.
- `BacktestExecutionConfig.entry_spread_feature` and `exit_spread_feature` add default-off order-book-spread execution adjustments for entry-like OPEN / scale-in REBALANCE fills and exit-like CLOSE / reduce REBALANCE / triggered stop-target fills, applying half-spread in the trade direction before the existing fixed-bps slippage model.
- BTC and generic event-preview payloads now expose `terminalOrderCount` and `terminalOrders` from `EventDrivenBacktestResult.terminal_orders`, so canceled/rejected terminal order details are visible beside planned and filled order state.
- `EventDrivenBacktestResult.terminal_order_reason_counts` now summarizes canceled/rejected terminal order reasons such as `entry_order_expired` and `exit_order_expired`; BTC/generic preview payloads serialize it as `terminalOrderReasonCounts`, and the dashboard appends those reason buckets to Event Order Status.
- Event-backtest REST routes can now accept execution-simulation query parameters such as `intrabar_entry_limit=true`, `max_entry_order_age_bars=...`, `max_exit_order_age_bars=...`, `max_exit_fill_fraction_per_bar=...`, `max_exit_volume_fraction_per_bar=...`, `entry_spread_feature=order_book_spread`, and `exit_spread_feature=order_book_spread`, passing them into `BacktestExecutionConfig` for research previews without changing default compatibility behavior.
- The Signal Pipeline dashboard now renders `terminalOrderCount` in the event-backtest summary cards and exposes controls for entry-limit fills, stale entry/exit order age, exit fill/volume caps, and optional entry/exit spread feature names, making stale-order cancellation and order-book-spread execution research available without editing query strings.
- `EventDrivenBacktestResult.exposure_curve` now records per-event portfolio exposure snapshots with long, short, gross, and net notional, open risk, and position count, giving multi-symbol and long/short research runs a portfolio-level analytics surface beyond realized trade attribution.
- `EventDrivenBacktestResult.exposure_curve` now also includes `group_exposure` buckets keyed by `MarketSpec.correlation_group`, and BTC/generic preview payloads serialize them as `groupExposure` so the dashboard can show correlation-group gross exposure and open risk beside total portfolio exposure.
- `EventDrivenBacktestResult.exposure_curve` now also includes `symbol_exposure` buckets, and BTC/generic preview payloads serialize them as `symbolExposure` so the dashboard can show single-symbol gross exposure and open risk beside correlation-group exposure.
- `EventDrivenBacktestResult.exposure_curve` now also includes `layer_exposure` buckets, and BTC/generic preview payloads serialize them as `layerExposure` so the dashboard can show core/tactical or other portfolio-layer gross exposure and open risk beside symbol and correlation-group exposure.
- `EventDrivenBacktestResult.exposure_curve` now also includes `module_exposure` buckets, and BTC/generic preview payloads serialize them as `moduleExposure` so the dashboard can show which standardized signal modules are consuming gross exposure and open risk.
- `EventDrivenBacktestResult.exposure_summary` now derives peak position count, gross notional, absolute net notional, open risk, symbol gross notional, symbol open risk, layer gross notional, layer open risk, module gross notional, module open risk, group gross notional, group open risk, and the symbol/layer/module/correlation-group names responsible for those peaks from the exposure curve; BTC/generic preview payloads serialize it as `exposureSummary`, and the dashboard event summary cards show max gross exposure, max open risk, max symbol risk, max layer risk, max module risk, and max group risk.
- `EventDrivenBacktestResult.performance_summary` now derives initial equity, final equity, total return, final unrealized PnL, realized PnL, fees, funding, max/min equity, and max drawdown from the event equity curve; BTC/generic preview payloads serialize those fields in `summary`, and the dashboard event summary cards show total return and max drawdown beside realized PnL and exposure risk.
- `EventDrivenBacktestResult.performance_summary` now also derives trade count, win rate, average trade net PnL, and average holding bars from realized event trades; BTC/generic preview payloads serialize those fields in `summary`, and the dashboard event summary cards render them beside equity, drawdown, and exposure metrics.
- `EventDrivenBacktestResult.performance_summary` now also derives gross profit, gross loss, and profit factor from realized event trades; BTC/generic preview payloads serialize `grossProfit`, `grossLoss`, and `profitFactor`, and the dashboard event summary cards render them beside win rate and average trade metrics.
- `EventDrivenBacktestResult.performance_summary` now also derives average winning trade, average losing trade magnitude, and payoff ratio from realized event trades; BTC/generic preview payloads serialize `averageWinNetPnl`, `averageLossNetPnl`, and `payoffRatio`, and the dashboard event summary cards render them beside profit factor.
- `BacktestTrade` now carries entry/exit timestamps, entry/exit bar indexes, and holding bars for realized event-driven trades; BTC/generic preview payloads serialize those timing fields, and the Signal Pipeline dashboard renders holding duration in the Event Trades table.
- `BacktestAttributionBucket` now aggregates average realized holding bars for symbol, layer, and module attribution buckets; BTC/generic preview payloads serialize `averageHoldingBars`, and the Signal Pipeline dashboard renders it in Event Attribution.
- `BacktestAttributionBucket` now also aggregates gross profit, gross loss, profit factor, average winning trade, average losing trade magnitude, and payoff ratio for each attribution bucket; BTC/generic preview payloads serialize those fields, and the Signal Pipeline dashboard renders PF and Payoff columns in Event Attribution.
- `BacktestAttribution` now also groups realized trade performance by direction (`long` / `short`); BTC/generic preview payloads serialize `byDirection`, and the Signal Pipeline dashboard renders Direction rows in Event Attribution.
- `BacktestAttribution` now also groups realized trade performance by exit reason such as `target`, `stop`, `decrease_position`, and `opposite_signal_close`; BTC/generic preview payloads serialize `byExitReason`, and the Signal Pipeline dashboard renders Exit rows in Event Attribution.
- The BTC event-driven preview/API now serializes that portfolio exposure history as `exposureCurve`, so dashboard and API callers can consume per-event long, short, gross, net, and open-risk snapshots beside equity, trades, and attribution.
- The Signal Pipeline dashboard now renders the event-driven `exposureCurve` as an Event Exposure feed, showing recent position count, long/short/gross/net notional, and open risk beside event equity and trades.
- Generic research event previews now use the same `EventDrivenBacktest` result shape as the BTC event preview, including market/regime metadata, orders, trades, equity curve, exposure curve, and attribution for configured non-BTC markets such as AAPL/NASDAQ.
- Generic research event previews now expose the existing event engine's multi-symbol path through the service/API boundary, so portfolio-level research can evaluate more than one configured symbol in timestamp order instead of calling one single-symbol preview per asset.
- The Signal Pipeline dashboard now exposes symbol, exchange, and market-type selectors; BTC/Binance/swap still uses compatibility preview and migration comparison endpoints, while non-BTC selections use generic research preview and research event-backtest endpoints.
- The Signal Pipeline dashboard selectors now support multi-select market combinations; event backtest requests serialize selected symbols, exchanges, and market types as the existing comma-separated generic research query format, while the single-bar preview panel continues to summarize the first selected market.
- `/api/signals/markets` now exposes configured `MarketSpec` records as read-only dashboard metadata, and the Signal Pipeline dashboard loads those records to populate symbol, exchange, and market-type selectors while retaining static defaults if the metadata endpoint is unavailable.
- The Signal Pipeline dashboard now displays selected configured markets' structured session metadata from `/api/signals/markets` in a Market Session feed, making timezone, session hours, and trading days visible beside cache, risk, signal, and event analytics.
- The Signal Pipeline dashboard now exposes `Refresh bars` and `Refresh features` controls that pass `refresh_bars` and `refresh_features` through generic research preview/event-backtest requests, giving UI callers the same DataConnector-to-BarStore and FeatureEngine-to-FeatureStore cache refresh controls as the API.
- BTC base strategy entries, weighted legacy entries, dual-layer core-long entries, dual-layer core pullback adds, bear-core probe/confirm/acceleration entries, dual-layer tactical entries, and flash-crash dip-buy entries now retain legacy fractional size semantics but execute direction, stop, and target from the recorded platform open-order plan when one is available, moving ready entry paths from audit-only pipeline output toward `SignalPipeline`-sourced execution parameters.
- The visualization data loader now reads BTC OHLCV from the platform `ParquetBarStore` before falling back to legacy pickle files, so dashboard/API reads use the same BarStore-first migration path as `quant_btc.data.fetch_ohlcv()`.
- `build_delivery_channels()` and `load_delivery_channels_json()` can build dashboard, webhook, Telegram, and email delivery channels from secret-safe config records; webhook URLs and Telegram credentials must resolve from environment variables at runtime, and `config/signal_delivery.example.json` contains only env-var references.
- Pine golden-vector expected artifacts can now be written/read as JSON and compared against TradingView/Pine observed CSV or JSON exports through one file-level API, and `python -m pine.compare_golden_vectors` gives CI a deterministic Python-vs-Pine consistency check boundary for generated Pine.
- `generate_signal_module_pine()` can now generate a Pine v6 indicator from platform signal-module configuration, currently covering `BreakoutSignalConfig`, `PullbackSignalConfig`, `MeanReversionSignalConfig`, `SweepReversalSignalConfig`, `CrashShortSignalConfig`, `FailedBounceSignalConfig`, and `BullTrapSignalConfig`; generated Pine carries the Python timeframe, score settings, and dynamic alert CSV rows compatible with the golden-vector observation schema.
- `write_signal_module_pine_parity_example()` now writes a generated Pine script, Python expected golden vectors, and an observation CSV template under `pine/examples/`, covering the current direct-compute signal modules from one reproducible Python entry point.
- `write_signal_module_pine_parity_example()` and `python -m pine.signal_module_parity --config ...` can now load the same JSON signal-module config used by generic research previews, so generated Pine and expected golden vectors come from the same module set instead of a second hardcoded list.

## Verification Snapshot

Latest verified command set:

```powershell
& 'C:\Users\10854\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_btc_derivative_bonus tests.test_btc_portfolio_model tests.test_btc_risk_model tests.test_platform_core tests.test_platform_features tests.test_platform_feature_store tests.test_platform_regimes tests.test_platform_signal_modules tests.test_platform_store tests.test_platform_bar_cache tests.test_platform_risk tests.test_platform_portfolio tests.test_platform_delivery tests.test_platform_delivery_config tests.test_platform_pine tests.test_platform_pipeline tests.test_platform_backtest tests.test_platform_ccxt_connector tests.test_platform_csv_connector tests.test_platform_sqlite_connector tests.test_platform_connector_config tests.test_platform_yahoo_connector tests.test_platform_yahoo_connector_config tests.test_platform_alpha_vantage_connector tests.test_platform_alpha_vantage_connector_config tests.test_platform_polygon_connector tests.test_platform_polygon_connector_config tests.test_pine_golden_cli tests.test_quant_btc_data_adapter tests.test_serve_data_loader tests.test_signal_preview_service tests.test_signal_preview_routes tests.test_signal_pipeline_frontend tests.test_valuescan_client tests.test_valuescan_metrics tests.test_valuescan_frontend tests.test_valuescan_routes -v
& 'C:\Users\10854\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_serve_data_loader -v
& 'C:\Users\10854\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_platform_store tests.test_platform_bar_cache -v
& 'C:\Users\10854\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_platform_bar_cache tests.test_quant_btc_data_adapter -v
& 'C:\Users\10854\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_platform_delivery tests.test_platform_delivery_config tests.test_platform_pipeline -v
& 'C:\Users\10854\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_platform_ccxt_connector tests.test_platform_csv_connector tests.test_platform_sqlite_connector tests.test_platform_connector_config tests.test_platform_yahoo_connector tests.test_platform_yahoo_connector_config tests.test_platform_alpha_vantage_connector tests.test_platform_alpha_vantage_connector_config tests.test_platform_polygon_connector tests.test_platform_polygon_connector_config -v
& 'C:\Users\10854\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_platform_pine -v
& 'C:\Users\10854\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_pine_golden_cli -v
& 'C:\Users\10854\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pine.signal_module_parity --output-dir pine/examples --config config/research_signal_modules.json --timeframe 1D --observed pine/examples/observed_template.csv --tolerance 0.01
& 'C:\Users\10854\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_signal_preview_service tests.test_signal_pipeline_frontend -v
& '.\.webvenv\Scripts\python.exe' -m unittest tests.test_signal_preview_routes -v
& '.\.webvenv\Scripts\python.exe' -m unittest tests.test_valuescan_routes -v
node --check serve\static\js\pipeline.js
node --check serve\static\js\valuescan.js
node --check serve\static\js\main.js
git diff --check
$patterns = @('(?i)(api[_-]?key|secret|password)\s*[:=]\s*["''][^"'']{8,}["'']','(?i)bearer\s+[A-Za-z0-9._\-]{16,}','sk-[A-Za-z0-9]{20,}','AKIA[0-9A-Z]{16}'); $matches = git diff -- . ':!*.pyc' | Select-String -Pattern $patterns; if ($matches) { $matches | ForEach-Object { $_.Line }; exit 1 } else { 'NO_SECRET_MATCHES' }
```

Latest result:

- Bundled runtime: `401 tests OK, skipped=14`
- Focused BTC risk model runtime: `38 tests OK`
- Focused BTC risk/portfolio runtime: `73 tests OK`
- Data loader focused runtime: `2 tests OK`
- Focused store/cache runtime: `7 tests OK`
- Focused derivative cache adapter runtime: `13 tests OK`
- Focused delivery/pipeline runtime: `20 tests OK`
- Focused connector runtime: `26 tests OK`
- Focused CCXT/order-book connector/cache/storage runtime: `47 tests OK`
- Focused BTC risk/pipeline runtime: `26 tests OK`
- Focused platform core/risk/signal preview service runtime: `68 tests OK`
- Focused platform risk runtime: `17 tests OK`
- Focused platform pipeline/risk/portfolio runtime: `45 tests OK`
- Focused platform risk/portfolio runtime: `34 tests OK`
- Focused platform core/signal preview service runtime: `53 tests OK`
- Focused platform core/signal preview/frontend runtime: `75 tests OK`
- Focused Pine generator runtime: `10 tests OK`
- Focused Pine CLI runtime: `6 tests OK`
- Pine parity workflow CLI returned `PINE_GOLDEN_VECTOR_MATCHES` with `config/research_signal_modules.json` and the regenerated example observation template.
- Focused feature runtime: `13 tests OK`
- Focused signal preview service runtime: `43 tests OK`
- Focused signal pipeline frontend runtime: `20 tests OK`
- Focused signal module/core/delivery/preview/frontend runtime: `124 tests OK`
- Focused platform backtest runtime: `28 tests OK`
- Focused platform backtest/pipeline/risk runtime: `41 tests OK`
- Focused risk/pipeline/preview/frontend runtime: `78 tests OK`
- Focused signal preview/frontend runtime: `62 tests OK`
- `.webvenv` Flask signal route runtime: `9 tests OK`
- `.webvenv` Flask Valuescan route runtime: `5 tests OK`
- JavaScript syntax checks passed.
- Secret scan returned `NO_SECRET_MATCHES`.
- `git diff --check` exited `0`; only CRLF warnings were reported.

Flask route tests are skipped in the bundled Python environment because Flask is not installed there. `.webvenv` contains the web runtime.

## Important Invariants

- Do not change existing BTC trading signal behavior while adding generic platform layers.
- Keep Valuescan credentials and any API secrets out of source files.
- New `quant_platform/` code should stay independent of `quant_btc.strategy`.
- Prefer TDD for new behavior: write a failing test first, confirm RED, implement minimal code, then verify.
- Use `docs/platform_migration.md` as the authoritative structured progress record.

## Files To Inspect First In A New Conversation

- `docs/platform_migration.md`
- `docs/goal_handoff.md`
- `quant_platform/__init__.py`
- `quant_platform/connectors.py`
- `serve/signal_preview.py`
- `config/markets.json`
- `config/regime_profiles.json`
- `config/research_data_sources.json`
- `config/research_signal_modules.json`
- `quant_platform/connector_config.py`
- `quant_platform/connectors_alpha_vantage.py`
- `quant_platform/connectors_polygon.py`
- `quant_platform/connectors_yahoo.py`
- `tests/test_platform_alpha_vantage_connector.py`
- `tests/test_platform_alpha_vantage_connector_config.py`
- `tests/test_platform_bar_cache.py`
- `tests/test_platform_polygon_connector.py`
- `tests/test_platform_polygon_connector_config.py`
- `tests/test_platform_yahoo_connector.py`
- `tests/test_platform_yahoo_connector_config.py`
- `quant_platform/delivery_config.py`
- `quant_platform/pine.py`
- `pine/examples/signal_module_parity.pine`
- `pine/examples/expected_vectors.json`
- `pine/examples/observed_template.csv`
- `pine/signal_module_parity.py`
- `tests/test_signal_preview_service.py`
- `tests/test_platform_regimes.py`
- `tests/test_platform_pine.py`

## Suggested Next Steps

1. Decide when and how legacy pickle cache compatibility should be retired after Parquet/SQLite paths cover current workflows.
2. Replace the Pine example `observed_template.csv` with real TradingView alert/export observations when running `python -m pine.signal_module_parity` in CI or a manual parity workflow.
3. Use `migrationReadiness` rows to choose the next BTC compatibility entry or exit path and extend platform-order-plan execution beyond the currently audited base/weighted/core-long/core-add/bear-probe/bear-confirm/bear-acceleration/tactical/dip-buy entries, base partial/full exits, weighted opposite-signal closes, and core/tactical/bear-core full or partial layer exits while preserving legacy size semantics.

## New Conversation Prompt

Use this prompt to continue in a new thread:

```text
Continue pursuing the active goal from the current workspace root (`Quant-for-BTC`).

Read docs/goal_handoff.md and docs/platform_migration.md first. Treat them as the current structured progress record. Keep the goal active unless every requirement in the original platform refactor objective is proven complete. Preserve BTC compatibility behavior and keep secrets out of source.

Start by inspecting the current worktree, then make the next TDD-backed architecture increment toward the generic trading signal research and alerting platform.
```

# Goal Handoff: Generic Trading Signal Research Platform

Last updated: 2026-06-04

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
- Regime profiles are now configurable through `config/regime_profiles.json`.
- `RegimeProfileRegistry` can load JSON profile config through `load_regime_profile_registry_json()`.
- The signal preview service exposes `resolve_regime_profile(market)`.
- Non-BTC regime profile resolution is covered by tests for AAPL/NASDAQ equity.
- `get_signal_research_preview()` can run a generic read-only `SignalPipeline` for any configured market with injectable bar, feature, and signal builders.
- `/api/signals/research-preview` accepts `symbol`, `exchange`, and `market_type` so dashboard/API callers are no longer limited to BTC-specific preview helpers.

## Verification Snapshot

Latest verified command set:

```powershell
& 'C:\Users\10854\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_btc_derivative_bonus tests.test_btc_portfolio_model tests.test_btc_risk_model tests.test_platform_core tests.test_platform_features tests.test_platform_feature_store tests.test_platform_regimes tests.test_platform_signal_modules tests.test_platform_store tests.test_platform_risk tests.test_platform_portfolio tests.test_platform_delivery tests.test_platform_pipeline tests.test_platform_backtest tests.test_platform_ccxt_connector tests.test_platform_csv_connector tests.test_platform_sqlite_connector tests.test_quant_btc_data_adapter tests.test_signal_preview_service tests.test_signal_preview_routes tests.test_signal_pipeline_frontend tests.test_valuescan_client tests.test_valuescan_metrics tests.test_valuescan_frontend tests.test_valuescan_routes -v
& '.\.webvenv\Scripts\python.exe' -m unittest tests.test_signal_preview_routes -v
node --check serve\static\js\pipeline.js
node --check serve\static\js\valuescan.js
node --check serve\static\js\main.js
git diff --check
$patterns = @('(?i)(api[_-]?key|secret|password)\s*[:=]\s*["''][^"'']{8,}["'']','(?i)bearer\s+[A-Za-z0-9._\-]{16,}','sk-[A-Za-z0-9]{20,}','AKIA[0-9A-Z]{16}'); $matches = git diff -- . ':!*.pyc' | Select-String -Pattern $patterns; if ($matches) { $matches | ForEach-Object { $_.Line }; exit 1 } else { 'NO_SECRET_MATCHES' }
```

Latest result:

- Bundled runtime: `193 tests OK, skipped=10`
- `.webvenv` Flask route runtime: `5 tests OK`
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
- `serve/signal_preview.py`
- `config/markets.json`
- `config/regime_profiles.json`
- `tests/test_signal_preview_service.py`
- `tests/test_platform_regimes.py`

## Suggested Next Steps

1. Back the generic research preview with configured non-BTC data sources and direct-compute `SignalModule` implementations.
2. Continue moving BTC strategy compatibility reads from strategy classes into standardized `SignalPipeline` paths without changing historical behavior.
3. Add richer risk and portfolio diagnostics for budget usage by symbol, module, and correlation group.
4. Decide when and how legacy pickle cache compatibility should be retired after Parquet/SQLite paths cover current workflows.
5. Add production configuration for webhook, Telegram, email, and Pine golden-vector CI comparison.

## New Conversation Prompt

Use this prompt to continue in a new thread:

```text
Continue pursuing the active goal from the current workspace root (`Quant-for-BTC`).

Read docs/goal_handoff.md and docs/platform_migration.md first. Treat them as the current structured progress record. Keep the goal active unless every requirement in the original platform refactor objective is proven complete. Preserve BTC compatibility behavior and keep secrets out of source.

Start by inspecting the current worktree, then make the next TDD-backed architecture increment toward the generic trading signal research and alerting platform.
```

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SignalPipelineFrontendTest(unittest.TestCase):
    def test_dashboard_declares_signal_pipeline_module_and_script(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('data-module="pipeline"', html)
        self.assertIn('id="module-pipeline"', html)
        self.assertIn('id="pipeline-symbol"', html)
        self.assertIn('id="pipeline-exchange"', html)
        self.assertIn('id="pipeline-market-type"', html)
        self.assertIn('id="pipeline-summary-cards"', html)
        self.assertIn('id="pipeline-backtest-summary-cards"', html)
        self.assertIn('id="pipeline-backtest-trade-rows"', html)
        self.assertIn('id="pipeline-backtest-attribution-rows"', html)
        self.assertIn('id="pipeline-equity-feed"', html)
        self.assertIn('id="pipeline-exposure-feed"', html)
        self.assertIn('id="pipeline-comparison-summary-cards"', html)
        self.assertIn('id="pipeline-comparison-rows"', html)
        self.assertIn('id="pipeline-order-parity-rows"', html)
        self.assertIn('id="pipeline-risk-audit-rows"', html)
        self.assertIn('id="pipeline-pipeline-audit-rows"', html)
        self.assertIn('id="pipeline-risk-budget-rows"', html)
        self.assertIn('js/pipeline.js', html)

    def test_router_initializes_pipeline_module(self):
        js = (ROOT / "serve" / "static" / "js" / "main.js").read_text(encoding="utf-8")

        self.assertIn("if (name === 'pipeline') initPipeline();", js)

    def test_pipeline_js_calls_pipeline_preview_api(self):
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("/signals/pipeline-preview", js)
        self.assertIn("/signals/event-backtest-preview", js)
        self.assertIn("/signals/migration-comparison-preview", js)
        self.assertIn("renderPipelineSignals", js)
        self.assertIn("renderPipelineRisk", js)
        self.assertIn("renderPipelineOrders", js)
        self.assertIn("renderPipelineRiskDiagnostics", js)
        self.assertIn("renderPipelineBacktest", js)
        self.assertIn("renderPipelineAttribution", js)
        self.assertIn("renderPipelineComparison", js)
        self.assertIn("renderPipelineOrderParity", js)
        self.assertIn("renderPipelineRiskAudit", js)
        self.assertIn("renderPipelineAudit", js)

    def test_pipeline_js_selects_generic_research_endpoints_for_non_btc_markets(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn('value="BTC/USDT"', html)
        self.assertIn('value="binance"', html)
        self.assertIn('value="swap"', html)
        self.assertIn('value="AAPL"', html)
        self.assertIn("pipeline-symbol", js)
        self.assertIn("pipeline-exchange", js)
        self.assertIn("pipeline-market-type", js)
        self.assertIn("isBtcCompatibilityMarket", js)
        self.assertIn("/signals/research-preview", js)
        self.assertIn("/signals/research-event-backtest-preview", js)
        self.assertIn("emptyPipelineComparison", js)

    def test_pipeline_js_can_request_multi_market_research_event_backtests(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn('id="pipeline-symbol" aria-label="Symbol" multiple', html)
        self.assertIn('id="pipeline-exchange" aria-label="Exchange" multiple', html)
        self.assertIn('id="pipeline-market-type" aria-label="Market type" multiple', html)
        self.assertIn("pipelineSelectedValues", js)
        self.assertIn("pipelineFirstMarket", js)
        self.assertIn("market.symbols.join(',')", js)
        self.assertIn("market.exchanges.join(',')", js)
        self.assertIn("market.marketTypes.join(',')", js)

    def test_pipeline_js_loads_market_selectors_from_configured_market_api(self):
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("/signals/markets", js)
        self.assertIn("loadPipelineMarkets", js)
        self.assertIn("renderPipelineMarketOptions", js)
        self.assertIn("market.marketType", js)
        self.assertIn("option.selected", js)

    def test_pipeline_js_renders_structured_market_session_metadata(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("Market Session", html)
        self.assertIn('id="pipeline-market-session-feed"', html)
        self.assertIn("pipelineMarketMetadata", js)
        self.assertIn("renderPipelineMarketSession", js)
        self.assertIn("market.sessionTimezone", js)
        self.assertIn("market.sessionOpen", js)
        self.assertIn("market.sessionClose", js)
        self.assertIn("market.tradingDays", js)
        self.assertIn("market.tickSize", js)
        self.assertIn("market.lotSize", js)
        self.assertIn("market.feeRate", js)
        self.assertIn("market.contractMultiplier", js)
        self.assertIn("market.supportsShort", js)
        self.assertIn("market.supportsLeverage", js)

    def test_pipeline_js_can_refresh_research_bar_and_feature_caches(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn('id="pipeline-refresh-bars"', html)
        self.assertIn('id="pipeline-refresh-features"', html)
        self.assertIn('id="pipeline-feature-cache-feed"', html)
        self.assertIn('id="pipeline-event-feature-cache-feed"', html)
        self.assertIn("pipelineChecked('pipeline-refresh-bars')", js)
        self.assertIn("pipelineChecked('pipeline-refresh-features')", js)
        self.assertIn("refresh_bars=", js)
        self.assertIn("refresh_features=", js)
        self.assertIn("renderPipelineFeatureCache", js)
        self.assertIn("renderPipelineEventFeatureCaches", js)
        self.assertIn("data.featureCache", js)
        self.assertIn("data.featureCaches", js)
        self.assertIn("cache.hit", js)
        self.assertIn("cache.cacheKey", js)

    def test_pipeline_js_can_configure_event_execution_assumptions(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn('id="pipeline-intrabar-entry-limit"', html)
        self.assertIn('id="pipeline-entry-order-age-bars"', html)
        self.assertIn('id="pipeline-exit-order-age-bars"', html)
        self.assertIn('id="pipeline-exit-fill-fraction"', html)
        self.assertIn('id="pipeline-exit-volume-fraction"', html)
        self.assertIn('id="pipeline-entry-spread-feature"', html)
        self.assertIn('id="pipeline-exit-spread-feature"', html)
        self.assertIn("pipelineExecutionSettings", js)
        self.assertIn("pipelineExecutionQuery", js)
        self.assertIn("pipelineChecked('pipeline-intrabar-entry-limit')", js)
        self.assertIn("pipelineNumberValue('pipeline-entry-order-age-bars')", js)
        self.assertIn("pipelineNumberValue('pipeline-exit-order-age-bars')", js)
        self.assertIn("pipelineNumberValue('pipeline-exit-fill-fraction')", js)
        self.assertIn("pipelineNumberValue('pipeline-exit-volume-fraction')", js)
        self.assertIn("pipelineTextValue('pipeline-entry-spread-feature')", js)
        self.assertIn("pipelineTextValue('pipeline-exit-spread-feature')", js)
        self.assertIn("intrabar_entry_limit=", js)
        self.assertIn("max_entry_order_age_bars=", js)
        self.assertIn("max_exit_order_age_bars=", js)
        self.assertIn("max_exit_fill_fraction_per_bar=", js)
        self.assertIn("max_exit_volume_fraction_per_bar=", js)
        self.assertIn("entry_spread_feature=", js)
        self.assertIn("exit_spread_feature=", js)
        self.assertIn("pipelineExecutionQuery(market.execution)", js)

    def test_pipeline_js_renders_event_exposure_curve(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("Event Exposure", html)
        self.assertIn('id="pipeline-exposure-feed"', html)
        self.assertIn("data.exposureCurve", js)
        self.assertIn("renderPipelineExposure", js)
        self.assertIn("point.longNotional", js)
        self.assertIn("point.shortNotional", js)
        self.assertIn("point.grossNotional", js)
        self.assertIn("point.netNotional", js)
        self.assertIn("point.openRisk", js)
        self.assertIn("point.groupExposure", js)
        self.assertIn("pipelineGroupExposureText", js)
        self.assertIn("point.symbolExposure", js)
        self.assertIn("pipelineSymbolExposureText", js)
        self.assertIn("point.layerExposure", js)
        self.assertIn("pipelineLayerExposureText", js)
        self.assertIn("point.moduleExposure", js)
        self.assertIn("pipelineModuleExposureText", js)
        self.assertIn("data.exposureSummary", js)
        self.assertIn("Total Return", js)
        self.assertIn("summary.totalReturnPct", js)
        self.assertIn("Max Drawdown", js)
        self.assertIn("summary.maxDrawdownPct", js)
        self.assertIn("Max Gross", js)
        self.assertIn("Max Open Risk", js)
        self.assertIn("Max Group Risk", js)
        self.assertIn("maxGroupOpenRiskGroup", js)
        self.assertIn("Max Symbol Risk", js)
        self.assertIn("maxSymbolOpenRiskSymbol", js)
        self.assertIn("Max Layer Risk", js)
        self.assertIn("maxLayerOpenRiskLayer", js)
        self.assertIn("Max Module Risk", js)
        self.assertIn("maxModuleOpenRiskModule", js)
        self.assertIn("Win Rate", js)
        self.assertIn("summary.winRate", js)
        self.assertIn("Avg Trade", js)
        self.assertIn("summary.averageTradeNetPnl", js)
        self.assertIn("Avg Hold", js)
        self.assertIn("summary.averageHoldingBars", js)
        self.assertIn("Gross Profit", js)
        self.assertIn("summary.grossProfit", js)
        self.assertIn("Gross Loss", js)
        self.assertIn("summary.grossLoss", js)
        self.assertIn("Profit Factor", js)
        self.assertIn("summary.profitFactor", js)
        self.assertIn("Avg Win", js)
        self.assertIn("summary.averageWinNetPnl", js)
        self.assertIn("Avg Loss", js)
        self.assertIn("summary.averageLossNetPnl", js)
        self.assertIn("Payoff", js)
        self.assertIn("summary.payoffRatio", js)

    def test_pipeline_js_renders_final_portfolio_state(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("Final Portfolio", html)
        self.assertIn('id="pipeline-final-portfolio-rows"', html)
        self.assertIn("data.finalPortfolio", js)
        self.assertIn("renderPipelineFinalPortfolio", js)
        self.assertIn("portfolio.positions", js)
        self.assertIn("position.riskAmount", js)

    def test_pipeline_js_renders_event_order_status_counts(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("Event Order Status", html)
        self.assertIn('id="pipeline-order-status-rows"', html)
        self.assertIn("data.orderStatusCounts", js)
        self.assertIn("renderPipelineOrderStatus", js)
        self.assertIn("filledOrderCount", js)
        self.assertIn("terminalOrderCount", js)
        self.assertIn("data.terminalOrderReasonCounts", js)
        self.assertIn("pipelineTerminalReasonText", js)
        self.assertIn("data.orderActionCounts", js)
        self.assertIn("pipelineOrderActionText", js)
        self.assertIn("data.orderModuleCounts", js)
        self.assertIn("pipelineOrderModuleText", js)
        self.assertIn("data.orderSymbolCounts", js)
        self.assertIn("pipelineOrderSymbolText", js)
        self.assertIn("data.orderLayerCounts", js)
        self.assertIn("pipelineOrderLayerText", js)
        self.assertIn("submitted", js)
        self.assertIn("filled", js)

    def test_pipeline_js_renders_event_trade_timing(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("Holding", html)
        self.assertIn("trade.holding_bars", js)
        self.assertIn("trade.entry_time", js)
        self.assertIn("trade.exit_time", js)

    def test_pipeline_js_renders_attribution_average_holding(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("<th>Hold</th>", html)
        self.assertIn("<th>PF</th>", html)
        self.assertIn("<th>Payoff</th>", html)
        self.assertIn("appendAttributionRows(rows, 'Direction'", js)
        self.assertIn("data.byDirection", js)
        self.assertIn("appendAttributionRows(rows, 'Exit'", js)
        self.assertIn("data.byExitReason", js)
        self.assertIn("row.averageHoldingBars", js)
        self.assertIn("row.profitFactor", js)
        self.assertIn("row.payoffRatio", js)

    def test_pipeline_js_renders_latest_regime_classification(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("Regime", html)
        self.assertIn('id="pipeline-regime-feed"', html)
        self.assertIn("renderPipelineRegime", js)
        self.assertIn("data.latestRegime", js)
        self.assertIn("data.latestRegimes", js)
        self.assertIn("regime.label", js)
        self.assertIn("regime.value", js)

    def test_pipeline_js_renders_risk_budget_diagnostics(self):
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("data.riskDiagnostics", js)
        self.assertIn("pipeline-risk-budget-rows", js)
        self.assertIn("appendRiskBudgetRows", js)
        self.assertIn("'Portfolio'", js)
        self.assertIn("'Symbol'", js)
        self.assertIn("'Module'", js)
        self.assertIn("'Correlation'", js)
        self.assertIn("utilization", js)
        self.assertIn("appendRiskDrawdownRow", js)
        self.assertIn("data.drawdown", js)
        self.assertIn("drawdown.currentPct", js)
        self.assertIn("drawdown.limitPct", js)
        self.assertIn("drawdown.breached", js)

    def test_pipeline_orders_render_normalized_plan_prices(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("<th>Entry</th>", html)
        self.assertIn("<th>Stop</th>", html)
        self.assertIn("<th>Target</th>", html)
        self.assertIn("order.entry_price", js)
        self.assertIn("order.stop_price", js)
        self.assertIn("order.target_price", js)

    def test_pipeline_signals_render_required_data_dependencies(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("<th>Data</th>", html)
        self.assertIn("pipelineRequiredDataText", js)
        self.assertIn("signal.required_data", js)

    def test_pipeline_js_renders_migration_risk_audit(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("Risk Audit", html)
        self.assertIn("<th>Status</th>", html)
        self.assertIn("<th>Would Block</th>", html)
        self.assertIn("<th>Risk Delta</th>", html)
        self.assertIn("data.riskAudit", js)
        self.assertIn("renderPipelineRiskAudit", js)
        self.assertIn("pipeline-risk-audit-rows", js)
        self.assertIn("wouldBlockIfEnforcedCount", js)
        self.assertIn("row.parity_status", js)
        self.assertIn("row.would_block_if_enforced", js)

    def test_pipeline_js_renders_migration_pipeline_audit(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("Pipeline Audit", html)
        self.assertIn("<th>Signals</th>", html)
        self.assertIn("<th>Risk Decisions</th>", html)
        self.assertIn("<th>Orders</th>", html)
        self.assertIn("data.pipelineAudit", js)
        self.assertIn("renderPipelineAudit", js)
        self.assertIn("pipeline-pipeline-audit-rows", js)
        self.assertIn("pipelineAudit.auditCount", js)
        self.assertIn("row.riskDiagnostics", js)

    def test_pipeline_js_renders_order_parity(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("Order Parity", html)
        self.assertIn("<th>Module</th>", html)
        self.assertIn("<th>Legacy</th>", html)
        self.assertIn("<th>Event</th>", html)
        self.assertIn("<th>Matched</th>", html)
        self.assertIn("<th>Mismatch</th>", html)
        self.assertIn("data.orderParity", js)
        self.assertIn("Object.keys(data.byModule || {})", js)
        self.assertIn("renderPipelineOrderParity", js)
        self.assertIn("pipeline-order-parity-rows", js)
        self.assertIn("orderParity.mismatchCount", js)
        self.assertIn("row.mismatchCount", js)

    def test_pipeline_js_renders_migration_readiness(self):
        html = (ROOT / "serve" / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "serve" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")

        self.assertIn("Migration Readiness", html)
        self.assertIn('id="pipeline-migration-readiness-rows"', html)
        self.assertIn("<th>Ready</th>", html)
        self.assertIn("<th>Reason</th>", html)
        self.assertIn("data.migrationReadiness", js)
        self.assertIn("renderPipelineMigrationReadiness", js)
        self.assertIn("readyToMigrate", js)


if __name__ == "__main__":
    unittest.main()

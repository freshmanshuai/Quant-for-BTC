// Signal Pipeline Preview Module

let pipelineLoaded = false;
let pipelineMarketsLoaded = false;
let pipelineMarketMetadata = [];

function initPipeline() {
  const refresh = document.getElementById('pipeline-refresh');
  if (refresh && !refresh.dataset.bound) {
    refresh.dataset.bound = '1';
    refresh.onclick = loadPipeline;
  }

  if (!pipelineLoaded) {
    pipelineLoaded = true;
    if (!pipelineMarketsLoaded) {
      pipelineMarketsLoaded = true;
      loadPipelineMarkets().finally(loadPipeline);
      return;
    }
    loadPipeline();
  }
}

async function loadPipelineMarkets() {
  try {
    const data = await pipelineFetchJson(API + '/signals/markets');
    pipelineMarketMetadata = data.markets || [];
    renderPipelineMarketOptions(pipelineMarketMetadata);
    renderPipelineMarketSession();
  } catch (error) {
    // Static defaults remain usable when the optional market metadata API is unavailable.
  }
}

function renderPipelineMarketOptions(markets) {
  if (!markets.length) return;
  const symbols = Array.from(new Set(markets.map(market => market.symbol).filter(Boolean))).sort();
  const exchanges = Array.from(new Set(markets.map(market => market.exchange).filter(Boolean))).sort();
  const marketTypes = Array.from(new Set(markets.map(market => market.marketType).filter(Boolean))).sort();
  renderPipelineSelectOptions('pipeline-symbol', symbols, 'BTC/USDT');
  renderPipelineSelectOptions('pipeline-exchange', exchanges, 'binance');
  renderPipelineSelectOptions('pipeline-market-type', marketTypes, 'swap');
}

function renderPipelineMarketSession() {
  const feed = document.getElementById('pipeline-market-session-feed');
  if (!feed) return;
  const symbols = pipelineSelectedValues('pipeline-symbol', 'BTC/USDT');
  const exchanges = pipelineSelectedValues('pipeline-exchange', 'binance');
  const marketTypes = pipelineSelectedValues('pipeline-market-type', 'swap');
  const rows = pipelineMarketMetadata.filter(market =>
    symbols.includes(market.symbol) &&
    exchanges.includes(market.exchange) &&
    marketTypes.includes(market.marketType)
  );
  if (!rows.length) {
    feed.innerHTML = '<div class="stream-item"><div class="stream-content">No market session metadata</div></div>';
    return;
  }
  feed.innerHTML = rows.map(market => {
    const session = formatMarketSession(market);
    return '<div class="stream-item"><div class="stream-meta">' +
      pipelineEscape([market.symbol, market.exchange, market.marketType].filter(Boolean).join(' | ')) +
      '</div><div class="stream-content">' + pipelineEscape(session) + '</div></div>';
  }).join('');
}

function formatMarketSession(market) {
  const timezone = market.sessionTimezone || 'timezone n/a';
  const hours = market.sessionOpen && market.sessionClose
    ? market.sessionOpen + '-' + market.sessionClose
    : (market.tradingSession || 'hours n/a');
  const days = Array.isArray(market.tradingDays) && market.tradingDays.length
    ? market.tradingDays.join(',')
    : 'days n/a';
  const constraints = [
    'tick ' + constraintText(market.tickSize),
    'lot ' + constraintText(market.lotSize),
    'fee ' + rateText(market.feeRate),
    'funding ' + rateText(market.fundingRate),
    'contract ' + constraintText(market.contractMultiplier),
    'short ' + yesNoText(market.supportsShort),
    'leverage ' + yesNoText(market.supportsLeverage),
  ];
  if (market.maxLeverage !== null && market.maxLeverage !== undefined) {
    constraints.push('max lev ' + constraintText(market.maxLeverage) + 'x');
  }
  return timezone + ' | ' + hours + ' | ' + days + ' | ' + constraints.join(' | ');
}

function constraintText(value) {
  return value === null || value === undefined ? '--' : String(value);
}

function rateText(value) {
  return value === null || value === undefined ? '--' : pctText(Number(value) * 100, 4);
}

function yesNoText(value) {
  return value ? 'yes' : 'no';
}

function renderPipelineSelectOptions(id, values, fallback) {
  const input = document.getElementById(id);
  if (!input || !values.length) return;
  const selected = pipelineSelectedValues(id, fallback);
  input.innerHTML = values.map(value => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    option.selected = selected.includes(value);
    return option.outerHTML;
  }).join('');
}

async function loadPipeline() {
  const timeframe = document.getElementById('pipeline-timeframe').value || '4h';
  const symbols = pipelineSelectedValues('pipeline-symbol', 'BTC/USDT');
  const exchanges = pipelineSelectedValues('pipeline-exchange', 'binance');
  const marketTypes = pipelineSelectedValues('pipeline-market-type', 'swap');
  const refreshBars = pipelineChecked('pipeline-refresh-bars');
  const refreshFeatures = pipelineChecked('pipeline-refresh-features');
  const execution = pipelineExecutionSettings();
  const equityInput = document.getElementById('pipeline-equity');
  const equity = Math.max(1, Number(equityInput.value || 10000));
  equityInput.value = String(equity);
  setPipelineStatus('Loading');

  try {
    const market = {
      timeframe,
      symbols,
      exchanges,
      marketTypes,
      refreshBars,
      refreshFeatures,
      execution,
      equity,
    };
    market.symbol = market.symbols.join(',');
    market.exchange = market.exchanges.join(',');
    market.marketType = market.marketTypes.join(',');
    const previewUrl = pipelinePreviewUrl(market);
    const backtestUrl = pipelineBacktestUrl(market);
    const data = await pipelineFetchJson(previewUrl);
    const backtest = await pipelineFetchJson(backtestUrl);
    const comparison = isBtcCompatibilityMarket(market)
      ? await pipelineFetchJson(pipelineComparisonUrl(market))
      : emptyPipelineComparison();
    renderPipelineMarketSession();
    renderPipeline(data);
    renderPipelineBacktest(backtest);
    renderPipelineComparison(comparison);
    setPipelineStatus('Loaded');
  } catch (error) {
    renderPipelineError(error.message);
    setPipelineStatus('Unavailable');
  }
}

function pipelineSelectedValues(id, fallback) {
  const input = document.getElementById(id);
  const selected = Array.from(input.selectedOptions || [])
    .map(option => option.value)
    .filter(Boolean);
  if (selected.length) return selected;
  return pipelineValueList(input.value, fallback);
}

function pipelineChecked(id) {
  const input = document.getElementById(id);
  return Boolean(input && input.checked);
}

function pipelineNumberValue(id) {
  const input = document.getElementById(id);
  if (!input) return null;
  const value = String(input.value || '').trim();
  if (!value) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function pipelineTextValue(id) {
  const input = document.getElementById(id);
  return input ? String(input.value || '').trim() : '';
}

function pipelineExecutionSettings() {
  return {
    intrabarEntryLimit: pipelineChecked('pipeline-intrabar-entry-limit'),
    maxEntryOrderAgeBars: pipelineNumberValue('pipeline-entry-order-age-bars'),
    maxExitOrderAgeBars: pipelineNumberValue('pipeline-exit-order-age-bars'),
    maxExitFillFraction: pipelineNumberValue('pipeline-exit-fill-fraction'),
    maxExitVolumeFraction: pipelineNumberValue('pipeline-exit-volume-fraction'),
    entrySpreadFeature: pipelineTextValue('pipeline-entry-spread-feature'),
    exitSpreadFeature: pipelineTextValue('pipeline-exit-spread-feature'),
  };
}

function pipelineValueList(value, fallback) {
  if (Array.isArray(value)) return value.filter(Boolean);
  return String(value || fallback || '')
    .split(',')
    .map(item => item.trim())
    .filter(Boolean);
}

function pipelineFirstMarket(market) {
  return {
    timeframe: market.timeframe,
    symbol: pipelineValueList(market.symbols || market.symbol, 'BTC/USDT')[0] || 'BTC/USDT',
    exchange: pipelineValueList(market.exchanges || market.exchange, 'binance')[0] || 'binance',
    marketType: pipelineValueList(market.marketTypes || market.marketType, 'swap')[0] || 'swap',
    refreshBars: market.refreshBars,
    refreshFeatures: market.refreshFeatures,
    execution: market.execution,
    equity: market.equity,
  };
}

function isBtcCompatibilityMarket(market) {
  return market.symbol === 'BTC/USDT' && market.exchange === 'binance' && market.marketType === 'swap';
}

function pipelinePreviewUrl(market) {
  const previewMarket = pipelineFirstMarket(market);
  if (isBtcCompatibilityMarket(previewMarket)) {
    return API + '/signals/pipeline-preview?' + pipelineBaseQuery(previewMarket);
  }
  return API + '/signals/research-preview?' + pipelineResearchQuery(previewMarket);
}

function pipelineBacktestUrl(market) {
  const executionQuery = pipelineExecutionQuery(market.execution);
  if (isBtcCompatibilityMarket(market)) {
    return API + '/signals/event-backtest-preview?' + pipelineBaseQuery(market) + executionQuery;
  }
  return API + '/signals/research-event-backtest-preview?' + pipelineResearchQuery(market) + executionQuery;
}

function pipelineComparisonUrl(market) {
  return API + '/signals/migration-comparison-preview?' + pipelineBaseQuery(market);
}

function pipelineBaseQuery(market) {
  return 'timeframe=' + encodeURIComponent(market.timeframe) +
    '&symbol=' + encodeURIComponent(market.symbol) +
    '&equity=' + encodeURIComponent(market.equity);
}

function pipelineResearchQuery(market) {
  return pipelineBaseQuery(market) +
    '&exchange=' + encodeURIComponent(market.exchange) +
    '&market_type=' + encodeURIComponent(market.marketType) +
    '&refresh_bars=' + encodeURIComponent(Boolean(market.refreshBars)) +
    '&refresh_features=' + encodeURIComponent(Boolean(market.refreshFeatures));
}

function pipelineExecutionQuery(execution) {
  const params = [];
  const config = execution || {};
  if (config.intrabarEntryLimit) {
    params.push('intrabar_entry_limit=true');
  }
  if (config.maxEntryOrderAgeBars !== null && config.maxEntryOrderAgeBars !== undefined) {
    params.push('max_entry_order_age_bars=' + encodeURIComponent(config.maxEntryOrderAgeBars));
  }
  if (config.maxExitOrderAgeBars !== null && config.maxExitOrderAgeBars !== undefined) {
    params.push('max_exit_order_age_bars=' + encodeURIComponent(config.maxExitOrderAgeBars));
  }
  if (config.maxExitFillFraction !== null && config.maxExitFillFraction !== undefined) {
    params.push('max_exit_fill_fraction_per_bar=' + encodeURIComponent(config.maxExitFillFraction));
  }
  if (config.maxExitVolumeFraction !== null && config.maxExitVolumeFraction !== undefined) {
    params.push('max_exit_volume_fraction_per_bar=' + encodeURIComponent(config.maxExitVolumeFraction));
  }
  if (config.entrySpreadFeature) {
    params.push('entry_spread_feature=' + encodeURIComponent(config.entrySpreadFeature));
  }
  if (config.exitSpreadFeature) {
    params.push('exit_spread_feature=' + encodeURIComponent(config.exitSpreadFeature));
  }
  return params.length ? '&' + params.join('&') : '';
}

function emptyPipelineComparison() {
  return {
    legacy: {},
    event: {},
    delta: {},
    riskAudit: {},
    pipelineAudit: {},
    orderParity: {},
    migrationReadiness: {},
  };
}

async function pipelineFetchJson(url) {
  const response = await fetch(url);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.message || body.error || ('HTTP ' + response.status));
  }
  return body;
}

function renderPipeline(data) {
  renderPipelineSummary(data);
  renderPipelineRegime(data.latestRegime || data.latestRegimes);
  renderPipelineFeatureCache(data.featureCache);
  renderPipelineRiskDiagnostics(data.riskDiagnostics || {});
  renderPipelineSignals(data.signals || []);
  renderPipelineRisk(data.riskDecisions || []);
  renderPipelineOrders(data.orders || []);
  renderPipelineDeliveries(data.deliveries || []);
}

function renderPipelineSummary(data) {
  const cards = [
    { label: 'Signals', value: String(data.signalCount || 0) },
    { label: 'Allowed', value: String((data.riskDecisions || []).filter(d => d.allowed).length), cls: 'green' },
    { label: 'Orders', value: String(data.orderCount || 0) },
    { label: 'Rows', value: String(data.rows || 0) },
  ];
  document.getElementById('pipeline-summary-cards').innerHTML = cards.map(c =>
    '<div class="summary-card"><div class="label">' + pipelineEscape(c.label) +
    '</div><div class="value ' + (c.cls || '') + '">' + pipelineEscape(c.value) + '</div></div>'
  ).join('');
}

function renderPipelineFeatureCache(cache) {
  const feed = document.getElementById('pipeline-feature-cache-feed');
  if (!feed) return;
  if (!cache) {
    feed.innerHTML = '<div class="stream-item"><div class="stream-content">No feature cache metadata</div></div>';
    return;
  }
  const status = cache.hit ? 'hit' : 'write';
  const columns = Array.isArray(cache.columns) ? cache.columns.length : 0;
  feed.innerHTML = '<div class="stream-item"><div class="stream-meta">' +
    pipelineEscape(status + ' | rows ' + numberText(cache.rows, 0) + ' | columns ' + numberText(columns, 0)) +
    '</div><div class="stream-content">' + pipelineEscape(cache.cacheKey || cache.path || '') + '</div></div>';
}

function renderPipelineSignals(rows) {
  const tbody = document.getElementById('pipeline-signal-rows');
  const shown = rows.slice(0, 50);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="6">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(signal =>
    '<tr><td>' + pipelineEscape(signal.module) + '</td><td>' + pipelineEscape(signal.direction) +
    '</td><td class="' + scoreClass(signal.score) + '">' + numberText(signal.score, 1) +
    '</td><td>' + moneyText(signal.preferred_stop) + '</td><td>' + moneyText(signal.preferred_target) +
    '</td><td>' + pipelineEscape(pipelineRequiredDataText(signal.required_data)) + '</td></tr>'
  ).join('');
}

function pipelineRequiredDataText(requiredData) {
  return Array.isArray(requiredData) && requiredData.length ? requiredData.join(', ') : '--';
}

function renderPipelineRisk(rows) {
  const tbody = document.getElementById('pipeline-risk-rows');
  const shown = rows.slice(0, 50);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="5">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(decision => {
    const signal = decision.signal || {};
    return '<tr><td>' + pipelineEscape(signal.module) + '</td><td class="' + (decision.allowed ? 'score-positive' : 'score-negative') + '">' +
      pipelineEscape(decision.allowed ? 'yes' : 'no') + '</td><td>' + numberText(decision.quantity, 4) +
      '</td><td>' + moneyText(decision.risk_amount) + '</td><td>' + pipelineEscape(decision.reason) + '</td></tr>';
  }).join('');
}

function renderPipelineRiskDiagnostics(data) {
  const tbody = document.getElementById('pipeline-risk-budget-rows');
  const rows = [];
  appendRiskBudgetRows(rows, 'Portfolio', { portfolio: data.portfolio });
  appendRiskBudgetRows(rows, 'Symbol', data.symbols || {});
  appendRiskBudgetRows(rows, 'Module', data.modules || {});
  appendRiskBudgetRows(rows, 'Correlation', data.correlation_groups || {});
  appendRiskDrawdownRow(rows, data.drawdown || {});
  const shown = rows.slice(0, 60);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="6">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(row =>
    '<tr><td>' + pipelineEscape(row.group) + '</td><td>' + pipelineEscape(row.key) +
    '</td><td>' + moneyText(row.used) + '</td><td>' + moneyText(row.budget) +
    '</td><td>' + moneyText(row.remaining) + '</td><td class="' + (row.breached ? 'score-negative' : '') + '">' +
    pctText(Number(row.utilization || 0) * 100, 1) +
    '</td></tr>'
  ).join('');
}

function appendRiskBudgetRows(rows, group, data) {
  Object.keys(data || {}).forEach(key => {
    const usage = data[key] || {};
    rows.push({
      group,
      key,
      used: usage.used,
      budget: usage.budget,
      remaining: usage.remaining,
      utilization: usage.utilization,
    });
  });
}

function appendRiskDrawdownRow(rows, drawdown) {
  if (!drawdown || drawdown.currentPct === undefined || drawdown.currentPct === null) return;
  rows.push({
    group: 'Drawdown',
    key: 'portfolio',
    used: Number(drawdown.currentPct || 0) * 100,
    budget: drawdown.limitPct === null || drawdown.limitPct === undefined ? null : Number(drawdown.limitPct || 0) * 100,
    remaining: drawdown.limitPct === null || drawdown.limitPct === undefined
      ? null
      : (Number(drawdown.limitPct || 0) - Number(drawdown.currentPct || 0)) * 100,
    utilization: drawdown.limitPct ? Number(drawdown.currentPct || 0) / Number(drawdown.limitPct) : 0,
    breached: Boolean(drawdown.breached),
  });
}

function renderPipelineOrders(rows) {
  const tbody = document.getElementById('pipeline-order-rows');
  const shown = rows.slice(0, 50);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="8">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(order =>
    '<tr><td>' + pipelineEscape(order.action) + '</td><td>' + pipelineEscape(order.symbol) +
    '</td><td>' + pipelineEscape(order.layer) + '</td><td>' + pipelineEscape(order.direction) +
    '</td><td>' + moneyText(order.entry_price) + '</td><td>' + moneyText(order.stop_price) +
    '</td><td>' + moneyText(order.target_price) + '</td><td>' + pipelineEscape(order.status) + '</td></tr>'
  ).join('');
}

function renderPipelineDeliveries(rows) {
  const feed = document.getElementById('pipeline-delivery-feed');
  const shown = rows.slice(0, 30);
  if (!shown.length) {
    feed.innerHTML = '<div class="stream-item"><div class="stream-content">No data</div></div>';
    return;
  }
  feed.innerHTML = shown.map(item => {
    const signal = item.signal || {};
    const order = item.order || {};
    return '<div class="stream-item"><div class="stream-meta">' + pipelineEscape(item.channel || 'dashboard') +
      ' | ' + pipelineEscape(order.order_id || '') + '</div><div class="stream-content">' +
      pipelineEscape([signal.symbol, signal.module, signal.direction, 'score ' + numberText(signal.score, 1), order.status].filter(Boolean).join(' | ')) +
      '</div></div>';
  }).join('');
}

function renderPipelineBacktest(data) {
  renderPipelineBacktestSummary(data);
  renderPipelineRegime(data.latestRegime || data.latestRegimes);
  renderPipelineEventFeatureCaches(data.featureCaches);
  renderPipelineBacktestTrades(data.trades || []);
  renderPipelineEquity(data.equityCurve || []);
  renderPipelineExposure(data.exposureCurve || []);
  renderPipelineFinalPortfolio(data.finalPortfolio || {});
  renderPipelineOrderStatus(
    data.orderStatusCounts || {},
    data.orderActionCounts || {},
    data.orderSymbolCounts || {},
    data.orderLayerCounts || {},
    data.orderModuleCounts || {},
    data.terminalOrderReasonCounts || {}
  );
  renderPipelineAttribution(data.attribution || {});
}

function renderPipelineBacktestSummary(data) {
  const summary = data.summary || {};
  const exposureSummary = data.exposureSummary || {};
  const cards = [
    { label: 'Event Orders', value: String(data.orderCount || 0) },
    { label: 'Filled Orders', value: String(data.filledOrderCount || 0), cls: 'green' },
    { label: 'Terminal Orders', value: String(data.terminalOrderCount || 0), cls: Number(data.terminalOrderCount || 0) > 0 ? 'red' : '' },
    { label: 'Event Trades', value: String(data.tradeCount || 0) },
    { label: 'Win Rate', value: pctText(Number(summary.winRate || 0) * 100, 1) },
    { label: 'Avg Trade', value: moneyText(summary.averageTradeNetPnl), cls: Number(summary.averageTradeNetPnl || 0) >= 0 ? 'green' : 'red' },
    { label: 'Avg Hold', value: summary.averageHoldingBars == null ? '--' : numberText(summary.averageHoldingBars, 1) + ' bars' },
    { label: 'Gross Profit', value: moneyText(summary.grossProfit), cls: Number(summary.grossProfit || 0) > 0 ? 'green' : '' },
    { label: 'Gross Loss', value: moneyText(summary.grossLoss), cls: Number(summary.grossLoss || 0) > 0 ? 'red' : '' },
    { label: 'Profit Factor', value: summary.profitFactor == null ? '--' : numberText(summary.profitFactor, 2) },
    { label: 'Avg Win', value: summary.averageWinNetPnl == null ? '--' : moneyText(summary.averageWinNetPnl), cls: summary.averageWinNetPnl == null ? '' : 'green' },
    { label: 'Avg Loss', value: summary.averageLossNetPnl == null ? '--' : moneyText(summary.averageLossNetPnl), cls: summary.averageLossNetPnl == null ? '' : 'red' },
    { label: 'Payoff', value: summary.payoffRatio == null ? '--' : numberText(summary.payoffRatio, 2) },
    { label: 'Final Equity', value: moneyText(summary.finalEquity) },
    { label: 'Total Return', value: pctText(Number(summary.totalReturnPct || 0) * 100, 2), cls: Number(summary.totalReturnPct || 0) >= 0 ? 'green' : 'red' },
    {
      label: 'Max Drawdown',
      value: pctText(Number(summary.maxDrawdownPct || 0) * 100, 2),
      cls: Number(summary.maxDrawdownPct || 0) > 0 ? 'red' : 'score-neutral',
      suffix: moneyText(summary.maxDrawdownAmount),
    },
    { label: 'Realized PnL', value: moneyText(summary.realizedPnl), cls: Number(summary.realizedPnl || 0) >= 0 ? 'green' : 'red' },
    { label: 'Fees', value: moneyText(summary.feesPaid) },
    { label: 'Max Gross', value: moneyText(exposureSummary.maxGrossNotional) },
    { label: 'Max Open Risk', value: moneyText(exposureSummary.maxOpenRisk) },
    {
      label: 'Max Group Risk',
      value: moneyText(exposureSummary.maxGroupOpenRisk),
      cls: exposureSummary.maxGroupOpenRiskGroup ? '' : 'score-neutral',
      suffix: exposureSummary.maxGroupOpenRiskGroup || '',
    },
    {
      label: 'Max Symbol Risk',
      value: moneyText(exposureSummary.maxSymbolOpenRisk),
      cls: exposureSummary.maxSymbolOpenRiskSymbol ? '' : 'score-neutral',
      suffix: exposureSummary.maxSymbolOpenRiskSymbol || '',
    },
    {
      label: 'Max Layer Risk',
      value: moneyText(exposureSummary.maxLayerOpenRisk),
      cls: exposureSummary.maxLayerOpenRiskLayer ? '' : 'score-neutral',
      suffix: exposureSummary.maxLayerOpenRiskLayer || '',
    },
    {
      label: 'Max Module Risk',
      value: moneyText(exposureSummary.maxModuleOpenRisk),
      cls: exposureSummary.maxModuleOpenRiskModule ? '' : 'score-neutral',
      suffix: exposureSummary.maxModuleOpenRiskModule || '',
    },
  ];
  document.getElementById('pipeline-backtest-summary-cards').innerHTML = cards.map(c => {
    const suffix = c.suffix ? '<div class="label">' + pipelineEscape(c.suffix) + '</div>' : '';
    return '<div class="summary-card"><div class="label">' + pipelineEscape(c.label) +
      '</div><div class="value ' + (c.cls || '') + '">' + pipelineEscape(c.value) +
      '</div>' + suffix + '</div>';
  }).join('');
}

function renderPipelineEventFeatureCaches(caches) {
  const feed = document.getElementById('pipeline-event-feature-cache-feed');
  if (!feed) return;
  const keys = Object.keys(caches || {});
  if (!keys.length) {
    feed.innerHTML = '<div class="stream-item"><div class="stream-content">No event feature cache metadata</div></div>';
    return;
  }
  feed.innerHTML = keys.sort().map(symbol => {
    const cache = caches[symbol];
    if (!cache) {
      return '<div class="stream-item"><div class="stream-meta">' + pipelineEscape(symbol) +
        '</div><div class="stream-content">No feature cache metadata</div></div>';
    }
    const status = cache.hit ? 'hit' : 'write';
    const columns = Array.isArray(cache.columns) ? cache.columns.length : 0;
    return '<div class="stream-item"><div class="stream-meta">' +
      pipelineEscape(symbol + ' | ' + status + ' | rows ' + numberText(cache.rows, 0) + ' | columns ' + numberText(columns, 0)) +
      '</div><div class="stream-content">' + pipelineEscape(cache.cacheKey || cache.path || '') + '</div></div>';
  }).join('');
}

function renderPipelineOrderStatus(counts, actionCounts, symbolCounts, layerCounts, moduleCounts, reasonCounts) {
  const tbody = document.getElementById('pipeline-order-status-rows');
  const statuses = ['planned', 'submitted', 'partially_filled', 'filled', 'canceled', 'rejected'];
  const actions = ['open', 'close', 'rebalance', 'transfer', 'ignore'];
  const rows = statuses.map(status => ({
    status: status,
    count: Number((counts || {})[status] || 0),
  })).concat(actions.map(action => ({
    status: pipelineOrderActionText(action),
    count: Number((actionCounts || {})[action] || 0),
  }))).concat(Object.keys(symbolCounts || {}).sort().map(symbol => ({
    status: pipelineOrderSymbolText(symbol),
    count: Number((symbolCounts || {})[symbol] || 0),
  }))).concat(Object.keys(layerCounts || {}).sort().map(layer => ({
    status: pipelineOrderLayerText(layer),
    count: Number((layerCounts || {})[layer] || 0),
  }))).concat(Object.keys(moduleCounts || {}).sort().map(module => ({
    status: pipelineOrderModuleText(module),
    count: Number((moduleCounts || {})[module] || 0),
  }))).concat(Object.keys(reasonCounts || {}).sort().map(reason => ({
    status: pipelineTerminalReasonText(reason),
    count: Number((reasonCounts || {})[reason] || 0),
  })));
  tbody.innerHTML = rows.map(row => {
    const cls = row.status === 'filled' && row.count > 0 ? 'score-positive' : '';
    return '<tr><td>' + pipelineEscape(row.status) +
      '</td><td class="' + cls + '">' + numberText(row.count, 0) + '</td></tr>';
  }).join('');
}

function pipelineTerminalReasonText(reason) {
  return 'reason:' + String(reason || 'unknown');
}

function pipelineOrderActionText(action) {
  return 'action:' + String(action || 'unknown');
}

function pipelineOrderSymbolText(symbol) {
  return 'symbol:' + String(symbol || 'unknown');
}

function pipelineOrderLayerText(layer) {
  return 'layer:' + String(layer || 'unknown');
}

function pipelineOrderModuleText(module) {
  return 'module:' + String(module || 'unknown');
}

function renderPipelineBacktestTrades(rows) {
  const tbody = document.getElementById('pipeline-backtest-trade-rows');
  const shown = rows.slice(0, 50);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="6">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(trade =>
    '<tr><td>' + pipelineEscape(trade.module) + '</td><td>' + pipelineEscape(trade.exit_reason) +
    '</td><td>' + pipelineEscape(pipelineTradeHoldingText(trade)) +
    '</td><td>' + numberText(trade.quantity, 4) + '</td><td>' + moneyText(trade.gross_pnl) +
    '</td><td class="' + (Number(trade.net_pnl || 0) >= 0 ? 'score-positive' : 'score-negative') + '">' +
    moneyText(trade.net_pnl) + '</td></tr>'
  ).join('');
}

function pipelineTradeHoldingText(trade) {
  const bars = trade.holding_bars === null || trade.holding_bars === undefined ? '--' : numberText(trade.holding_bars, 0) + ' bars';
  const entry = trade.entry_time || '';
  const exit = trade.exit_time || '';
  return [bars, [entry, exit].filter(Boolean).join(' -> ')].filter(Boolean).join(' | ');
}

function renderPipelineEquity(rows) {
  const feed = document.getElementById('pipeline-equity-feed');
  const shown = rows.slice(-20).reverse();
  if (!shown.length) {
    feed.innerHTML = '<div class="stream-item"><div class="stream-content">No data</div></div>';
    return;
  }
  feed.innerHTML = shown.map(point =>
    '<div class="stream-item"><div class="stream-meta">' + pipelineEscape(point.time || '') +
    ' | ' + pipelineEscape(point.symbol || '') + '</div><div class="stream-content">' +
    pipelineEscape('Equity ' + moneyText(point.equity) + ' | Cash ' + moneyText(point.cash) +
    ' | Unrealized ' + moneyText(point.unrealized_pnl)) + '</div></div>'
  ).join('');
}

function renderPipelineExposure(rows) {
  const feed = document.getElementById('pipeline-exposure-feed');
  const shown = rows.slice(-20).reverse();
  if (!shown.length) {
    feed.innerHTML = '<div class="stream-item"><div class="stream-content">No data</div></div>';
    return;
  }
  feed.innerHTML = shown.map(point =>
    '<div class="stream-item"><div class="stream-meta">' + pipelineEscape(point.time || '') +
    ' | ' + pipelineEscape(point.symbol || '') + '</div><div class="stream-content">' +
    pipelineEscape('Positions ' + numberText(point.positionCount, 0) +
    ' | Long ' + moneyText(point.longNotional) +
    ' | Short ' + moneyText(point.shortNotional) +
    ' | Gross ' + moneyText(point.grossNotional) +
    ' | Net ' + moneyText(point.netNotional) +
    ' | Open Risk ' + moneyText(point.openRisk) +
    ' | Symbols ' + pipelineSymbolExposureText(point.symbolExposure) +
    ' | Layers ' + pipelineLayerExposureText(point.layerExposure) +
    ' | Modules ' + pipelineModuleExposureText(point.moduleExposure) +
    ' | Groups ' + pipelineGroupExposureText(point.groupExposure)) + '</div></div>'
  ).join('');
}

function pipelineModuleExposureText(moduleExposure) {
  const modules = Object.keys(moduleExposure || {}).sort();
  if (!modules.length) return '--';
  return modules.slice(0, 3).map(module => {
    const exposure = moduleExposure[module] || {};
    return module + ' gross ' + moneyText(exposure.grossNotional) + ' risk ' + moneyText(exposure.openRisk);
  }).join('; ');
}

function pipelineLayerExposureText(layerExposure) {
  const layers = Object.keys(layerExposure || {}).sort();
  if (!layers.length) return '--';
  return layers.slice(0, 3).map(layer => {
    const exposure = layerExposure[layer] || {};
    return layer + ' gross ' + moneyText(exposure.grossNotional) + ' risk ' + moneyText(exposure.openRisk);
  }).join('; ');
}

function pipelineSymbolExposureText(symbolExposure) {
  const symbols = Object.keys(symbolExposure || {}).sort();
  if (!symbols.length) return '--';
  return symbols.slice(0, 3).map(symbol => {
    const exposure = symbolExposure[symbol] || {};
    return symbol + ' gross ' + moneyText(exposure.grossNotional) + ' risk ' + moneyText(exposure.openRisk);
  }).join('; ');
}

function pipelineGroupExposureText(groupExposure) {
  const groups = Object.keys(groupExposure || {}).sort();
  if (!groups.length) return '--';
  return groups.slice(0, 3).map(group => {
    const exposure = groupExposure[group] || {};
    return group + ' gross ' + moneyText(exposure.grossNotional) + ' risk ' + moneyText(exposure.openRisk);
  }).join('; ');
}

function renderPipelineFinalPortfolio(portfolio) {
  const tbody = document.getElementById('pipeline-final-portfolio-rows');
  if (!tbody) return;
  const positions = Array.isArray(portfolio.positions) ? portfolio.positions : [];
  if (!positions.length) {
    tbody.innerHTML = '<tr><td colspan="7">No open positions</td></tr>';
    return;
  }
  tbody.innerHTML = positions.map(position =>
    '<tr><td>' + pipelineEscape(position.symbol || '') +
    '</td><td>' + pipelineEscape(position.layer || '') +
    '</td><td>' + pipelineEscape(position.direction || '') +
    '</td><td>' + numberText(position.quantity, 4) +
    '</td><td>' + moneyText(position.entryPrice) +
    '</td><td>' + moneyText(position.riskAmount) +
    '</td><td>' + pipelineEscape(position.module || '') + '</td></tr>'
  ).join('');
}

function renderPipelineRegime(data) {
  const feed = document.getElementById('pipeline-regime-feed');
  const rows = normalizeRegimeRows(data);
  if (!rows.length) {
    feed.innerHTML = '<div class="stream-item"><div class="stream-content">No data</div></div>';
    return;
  }
  feed.innerHTML = rows.map(row => {
    const regime = row.regime || {};
    return '<div class="stream-item"><div class="stream-meta">' +
      pipelineEscape([row.symbol, regime.time].filter(Boolean).join(' | ')) +
      '</div><div class="stream-content">' +
      pipelineEscape('Regime ' + (regime.label || 'unknown') + ' | value ' + numberText(regime.value, 0)) +
      '</div></div>';
  }).join('');
}

function normalizeRegimeRows(data) {
  if (!data) return [];
  if (Object.prototype.hasOwnProperty.call(data, 'value')) {
    return [{ symbol: '', regime: data }];
  }
  return Object.keys(data).sort()
    .filter(symbol => data[symbol])
    .map(symbol => ({ symbol, regime: data[symbol] }));
}

function renderPipelineAttribution(data) {
  const tbody = document.getElementById('pipeline-backtest-attribution-rows');
  const rows = [];
  appendAttributionRows(rows, 'Symbol', data.bySymbol || {});
  appendAttributionRows(rows, 'Layer', data.byLayer || {});
  appendAttributionRows(rows, 'Module', data.byModule || {});
  appendAttributionRows(rows, 'Direction', data.byDirection || {});
  appendAttributionRows(rows, 'Exit', data.byExitReason || {});
  const shown = rows.slice(0, 60);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="8">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(row =>
    '<tr><td>' + pipelineEscape(row.group) + '</td><td>' + pipelineEscape(row.key) +
    '</td><td>' + numberText(row.tradeCount, 0) + '</td><td>' + moneyText(row.netPnl) +
    '</td><td>' + numberText((row.winRate || 0) * 100, 1) + '%</td><td>' +
    pipelineEscape(row.averageHoldingBars == null ? '--' : numberText(row.averageHoldingBars, 1)) +
    '</td><td>' + pipelineEscape(row.profitFactor == null ? '--' : numberText(row.profitFactor, 2)) +
    '</td><td>' + pipelineEscape(row.payoffRatio == null ? '--' : numberText(row.payoffRatio, 2)) +
    '</td></tr>'
  ).join('');
}

function appendAttributionRows(rows, group, data) {
  Object.keys(data).forEach(key => {
    rows.push(Object.assign({ group, key }, data[key]));
  });
}

function renderPipelineComparison(data) {
  renderPipelineComparisonSummary(data);
  renderPipelineComparisonRows(data);
  renderPipelineOrderParity(data.orderParity || {});
  renderPipelineMigrationReadiness(data.migrationReadiness || {});
  renderPipelineRiskAudit(data.riskAudit || {});
  renderPipelineAudit(data.pipelineAudit || {});
}

function renderPipelineComparisonSummary(data) {
  const legacy = data.legacy || {};
  const event = data.event || {};
  const delta = data.delta || {};
  const audit = data.riskAudit || {};
  const pipelineAudit = data.pipelineAudit || {};
  const orderParity = data.orderParity || {};
  const readiness = data.migrationReadiness || {};
  const cards = [
    { label: 'Legacy Trades', value: String(legacy.tradeCount || 0) },
    { label: 'Event Trades', value: String(event.tradeCount || 0) },
    { label: 'PnL Delta', value: moneyText(delta.totalPnl), cls: Number(delta.totalPnl || 0) >= 0 ? 'green' : 'red' },
    { label: 'Equity Delta', value: moneyText(delta.finalEquity), cls: Number(delta.finalEquity || 0) >= 0 ? 'green' : 'red' },
    { label: 'Risk Audits', value: String(audit.auditCount || 0) },
    { label: 'Pipeline Audits', value: String(pipelineAudit.auditCount || 0) },
    {
      label: 'Ready Modules',
      value: String(readiness.readyCount || 0),
      cls: Number(readiness.readyCount || 0) > 0 ? 'green' : '',
    },
    {
      label: 'Order Mismatch',
      value: String(orderParity.mismatchCount || 0),
      cls: Number(orderParity.mismatchCount || 0) > 0 ? 'red' : 'green',
    },
    {
      label: 'Would Block',
      value: String(audit.wouldBlockIfEnforcedCount || 0),
      cls: Number(audit.wouldBlockIfEnforcedCount || 0) > 0 ? 'red' : 'green',
    },
  ];
  document.getElementById('pipeline-comparison-summary-cards').innerHTML = cards.map(c =>
    '<div class="summary-card"><div class="label">' + pipelineEscape(c.label) +
    '</div><div class="value ' + (c.cls || '') + '">' + pipelineEscape(c.value) + '</div></div>'
  ).join('');
}

function renderPipelineComparisonRows(data) {
  const tbody = document.getElementById('pipeline-comparison-rows');
  const legacy = data.legacy || {};
  const event = data.event || {};
  const delta = data.delta || {};
  const rows = [
    { label: 'Trades', legacy: legacy.tradeCount, event: event.tradeCount, delta: delta.tradeCount, format: numberText },
    { label: 'PnL', legacy: legacy.totalPnl, event: event.realizedPnl, delta: delta.totalPnl, format: moneyText },
    { label: 'Final Equity', legacy: legacy.finalEquity, event: event.finalEquity, delta: delta.finalEquity, format: moneyText },
    { label: 'Win Rate', legacy: legacy.winRatePct, event: event.winRatePct, delta: delta.winRatePct, format: pctText },
  ];
  tbody.innerHTML = rows.map(row =>
    '<tr><td>' + pipelineEscape(row.label) + '</td><td>' + pipelineEscape(row.format(row.legacy, 1)) +
    '</td><td>' + pipelineEscape(row.format(row.event, 1)) + '</td><td class="' +
    (Number(row.delta || 0) >= 0 ? 'score-positive' : 'score-negative') + '">' +
    pipelineEscape(row.format(row.delta, 1)) + '</td></tr>'
  ).join('');
}

function renderPipelineOrderParity(data) {
  const tbody = document.getElementById('pipeline-order-parity-rows');
  const rows = Object.keys(data.byModule || {}).sort().map(module =>
    Object.assign({ module: module }, data.byModule[module])
  );
  const shown = rows.slice(0, 50);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="5">Matched ' + numberText(data.matchedCount, 0) + '</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(row =>
    '<tr><td>' + pipelineEscape(row.module || '') +
    '</td><td>' + numberText(row.legacyOrderCount, 0) +
    '</td><td>' + numberText(row.eventOrderCount, 0) +
    '</td><td class="score-positive">' + numberText(row.matchedCount, 0) +
    '</td><td class="' + (Number(row.mismatchCount || 0) > 0 ? 'score-negative' : 'score-positive') +
    '">' + numberText(row.mismatchCount, 0) + '</td></tr>'
  ).join('');
}

function renderPipelineMigrationReadiness(data) {
  const tbody = document.getElementById('pipeline-migration-readiness-rows');
  const shown = (data.modules || []).slice(0, 50);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="4">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(row => {
    const ok = Boolean(row.readyToMigrate);
    const statusClass = ok ? 'score-positive' : 'score-negative';
    const reasons = (row.reasons || []).join(', ');
    return '<tr><td>' + pipelineEscape(row.module || '') +
      '</td><td class="' + statusClass + '">' + pipelineEscape(row.status || 'unknown') +
      '</td><td>' + pipelineEscape(ok ? 'yes' : 'no') +
      '</td><td>' + pipelineEscape(reasons) + '</td></tr>';
  }).join('');
}

function renderPipelineRiskAudit(data) {
  const tbody = document.getElementById('pipeline-risk-audit-rows');
  const shown = (data.audits || []).slice(0, 50);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="5">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(row => {
    const statusClass = row.parity_status === 'matched' ? 'score-positive' : 'score-negative';
    return '<tr><td>' + pipelineEscape(row.bar_index == null ? '' : numberText(row.bar_index, 0)) +
      '</td><td>' + pipelineEscape(row.module || '') +
      '</td><td class="' + statusClass + '">' + pipelineEscape(row.parity_status || 'unknown') +
      '</td><td>' + pipelineEscape(row.would_block_if_enforced ? 'yes' : 'no') +
      '</td><td>' + moneyText(row.risk_amount_delta) + '</td></tr>';
  }).join('');
}

function renderPipelineAudit(data) {
  const tbody = document.getElementById('pipeline-pipeline-audit-rows');
  const shown = (data.audits || []).slice(0, 50);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="4">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(row => {
    const diagnostics = row.riskDiagnostics || {};
    const portfolio = diagnostics.portfolio || {};
    return '<tr><td>' + numberText(row.signalCount, 0) +
      '</td><td>' + numberText(row.riskDecisionCount, 0) +
      '</td><td>' + numberText(row.orderCount, 0) +
      '</td><td>' + moneyText(portfolio.used) + '</td></tr>';
  }).join('');
}

function renderPipelineError(message) {
  document.getElementById('pipeline-summary-cards').innerHTML =
    '<div class="summary-card"><div class="label">Pipeline</div><div class="value red">Offline</div></div>';
  document.getElementById('pipeline-signal-rows').innerHTML = '<tr><td colspan="6">' + pipelineEscape(message) + '</td></tr>';
  document.getElementById('pipeline-risk-budget-rows').innerHTML = '<tr><td colspan="6">No data</td></tr>';
  document.getElementById('pipeline-risk-rows').innerHTML = '<tr><td colspan="5">No data</td></tr>';
  document.getElementById('pipeline-order-rows').innerHTML = '<tr><td colspan="8">No data</td></tr>';
  document.getElementById('pipeline-delivery-feed').innerHTML = '';
  document.getElementById('pipeline-backtest-summary-cards').innerHTML =
    '<div class="summary-card"><div class="label">Event Backtest</div><div class="value red">Offline</div></div>';
  document.getElementById('pipeline-backtest-trade-rows').innerHTML = '<tr><td colspan="5">No data</td></tr>';
  document.getElementById('pipeline-backtest-attribution-rows').innerHTML = '<tr><td colspan="6">No data</td></tr>';
  document.getElementById('pipeline-equity-feed').innerHTML = '';
  document.getElementById('pipeline-exposure-feed').innerHTML = '';
  document.getElementById('pipeline-order-status-rows').innerHTML = '<tr><td colspan="2">No data</td></tr>';
  document.getElementById('pipeline-regime-feed').innerHTML = '<div class="stream-item"><div class="stream-content">No data</div></div>';
  document.getElementById('pipeline-comparison-summary-cards').innerHTML =
    '<div class="summary-card"><div class="label">Migration</div><div class="value red">Offline</div></div>';
  document.getElementById('pipeline-comparison-rows').innerHTML = '<tr><td colspan="4">No data</td></tr>';
  document.getElementById('pipeline-order-parity-rows').innerHTML = '<tr><td colspan="5">No data</td></tr>';
  document.getElementById('pipeline-migration-readiness-rows').innerHTML = '<tr><td colspan="4">No data</td></tr>';
  document.getElementById('pipeline-risk-audit-rows').innerHTML = '<tr><td colspan="5">No data</td></tr>';
  document.getElementById('pipeline-pipeline-audit-rows').innerHTML = '<tr><td colspan="4">No data</td></tr>';
}

function setPipelineStatus(text) {
  const status = document.getElementById('pipeline-status');
  if (status) status.textContent = text;
}

function scoreClass(value) {
  const score = Number(value || 0);
  if (score >= 75) return 'score-positive';
  if (score <= 40) return 'score-negative';
  return 'score-neutral';
}

function moneyText(value) {
  const n = Number(value || 0);
  return n ? '$' + n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '--';
}

function numberText(value, digits) {
  const n = Number(value || 0);
  return n.toFixed(digits);
}

function pctText(value, digits) {
  return numberText(value, digits) + '%';
}

function pipelineEscape(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

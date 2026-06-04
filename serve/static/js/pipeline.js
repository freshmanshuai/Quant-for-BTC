// Signal Pipeline Preview Module

let pipelineLoaded = false;

function initPipeline() {
  const refresh = document.getElementById('pipeline-refresh');
  if (refresh && !refresh.dataset.bound) {
    refresh.dataset.bound = '1';
    refresh.onclick = loadPipeline;
  }

  if (!pipelineLoaded) {
    pipelineLoaded = true;
    loadPipeline();
  }
}

async function loadPipeline() {
  const timeframe = document.getElementById('pipeline-timeframe').value || '4h';
  const equityInput = document.getElementById('pipeline-equity');
  const equity = Math.max(1, Number(equityInput.value || 10000));
  equityInput.value = String(equity);
  setPipelineStatus('Loading');

  try {
    const previewUrl =
      API + '/signals/pipeline-preview?timeframe=' + encodeURIComponent(timeframe) +
      '&symbol=' + encodeURIComponent('BTC/USDT') +
      '&equity=' + encodeURIComponent(equity);
    const backtestUrl =
      API + '/signals/event-backtest-preview?timeframe=' + encodeURIComponent(timeframe) +
      '&symbol=' + encodeURIComponent('BTC/USDT') +
      '&equity=' + encodeURIComponent(equity);
    const comparisonUrl =
      API + '/signals/migration-comparison-preview?timeframe=' + encodeURIComponent(timeframe) +
      '&symbol=' + encodeURIComponent('BTC/USDT') +
      '&equity=' + encodeURIComponent(equity);
    const data = await pipelineFetchJson(previewUrl);
    const backtest = await pipelineFetchJson(backtestUrl);
    const comparison = await pipelineFetchJson(comparisonUrl);
    renderPipeline(data);
    renderPipelineBacktest(backtest);
    renderPipelineComparison(comparison);
    setPipelineStatus('Loaded');
  } catch (error) {
    renderPipelineError(error.message);
    setPipelineStatus('Unavailable');
  }
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

function renderPipelineSignals(rows) {
  const tbody = document.getElementById('pipeline-signal-rows');
  const shown = rows.slice(0, 50);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="5">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(signal =>
    '<tr><td>' + pipelineEscape(signal.module) + '</td><td>' + pipelineEscape(signal.direction) +
    '</td><td class="' + scoreClass(signal.score) + '">' + numberText(signal.score, 1) +
    '</td><td>' + moneyText(signal.preferred_stop) + '</td><td>' + moneyText(signal.preferred_target) + '</td></tr>'
  ).join('');
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
  renderPipelineBacktestTrades(data.trades || []);
  renderPipelineEquity(data.equityCurve || []);
  renderPipelineAttribution(data.attribution || {});
}

function renderPipelineBacktestSummary(data) {
  const summary = data.summary || {};
  const cards = [
    { label: 'Event Trades', value: String(data.tradeCount || 0) },
    { label: 'Final Equity', value: moneyText(summary.finalEquity) },
    { label: 'Realized PnL', value: moneyText(summary.realizedPnl), cls: Number(summary.realizedPnl || 0) >= 0 ? 'green' : 'red' },
    { label: 'Fees', value: moneyText(summary.feesPaid) },
  ];
  document.getElementById('pipeline-backtest-summary-cards').innerHTML = cards.map(c =>
    '<div class="summary-card"><div class="label">' + pipelineEscape(c.label) +
    '</div><div class="value ' + (c.cls || '') + '">' + pipelineEscape(c.value) + '</div></div>'
  ).join('');
}

function renderPipelineBacktestTrades(rows) {
  const tbody = document.getElementById('pipeline-backtest-trade-rows');
  const shown = rows.slice(0, 50);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="5">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(trade =>
    '<tr><td>' + pipelineEscape(trade.module) + '</td><td>' + pipelineEscape(trade.exit_reason) +
    '</td><td>' + numberText(trade.quantity, 4) + '</td><td>' + moneyText(trade.gross_pnl) +
    '</td><td class="' + (Number(trade.net_pnl || 0) >= 0 ? 'score-positive' : 'score-negative') + '">' +
    moneyText(trade.net_pnl) + '</td></tr>'
  ).join('');
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

function renderPipelineAttribution(data) {
  const tbody = document.getElementById('pipeline-backtest-attribution-rows');
  const rows = [];
  appendAttributionRows(rows, 'Symbol', data.bySymbol || {});
  appendAttributionRows(rows, 'Layer', data.byLayer || {});
  appendAttributionRows(rows, 'Module', data.byModule || {});
  const shown = rows.slice(0, 60);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="5">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(row =>
    '<tr><td>' + pipelineEscape(row.group) + '</td><td>' + pipelineEscape(row.key) +
    '</td><td>' + numberText(row.tradeCount, 0) + '</td><td>' + moneyText(row.netPnl) +
    '</td><td>' + numberText((row.winRate || 0) * 100, 1) + '%</td></tr>'
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
}

function renderPipelineComparisonSummary(data) {
  const legacy = data.legacy || {};
  const event = data.event || {};
  const delta = data.delta || {};
  const cards = [
    { label: 'Legacy Trades', value: String(legacy.tradeCount || 0) },
    { label: 'Event Trades', value: String(event.tradeCount || 0) },
    { label: 'PnL Delta', value: moneyText(delta.totalPnl), cls: Number(delta.totalPnl || 0) >= 0 ? 'green' : 'red' },
    { label: 'Equity Delta', value: moneyText(delta.finalEquity), cls: Number(delta.finalEquity || 0) >= 0 ? 'green' : 'red' },
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

function renderPipelineError(message) {
  document.getElementById('pipeline-summary-cards').innerHTML =
    '<div class="summary-card"><div class="label">Pipeline</div><div class="value red">Offline</div></div>';
  document.getElementById('pipeline-signal-rows').innerHTML = '<tr><td colspan="5">' + pipelineEscape(message) + '</td></tr>';
  document.getElementById('pipeline-risk-rows').innerHTML = '<tr><td colspan="5">No data</td></tr>';
  document.getElementById('pipeline-order-rows').innerHTML = '<tr><td colspan="8">No data</td></tr>';
  document.getElementById('pipeline-delivery-feed').innerHTML = '';
  document.getElementById('pipeline-backtest-summary-cards').innerHTML =
    '<div class="summary-card"><div class="label">Event Backtest</div><div class="value red">Offline</div></div>';
  document.getElementById('pipeline-backtest-trade-rows').innerHTML = '<tr><td colspan="5">No data</td></tr>';
  document.getElementById('pipeline-backtest-attribution-rows').innerHTML = '<tr><td colspan="5">No data</td></tr>';
  document.getElementById('pipeline-equity-feed').innerHTML = '';
  document.getElementById('pipeline-comparison-summary-cards').innerHTML =
    '<div class="summary-card"><div class="label">Migration</div><div class="value red">Offline</div></div>';
  document.getElementById('pipeline-comparison-rows').innerHTML = '<tr><td colspan="4">No data</td></tr>';
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

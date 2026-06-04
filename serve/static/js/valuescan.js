// Valuescan AI Tracking Module

let valuescanLoaded = false;
let valuescanTrendChart = null;
let valuescanStreams = [];
const VALUESCAN_FETCH_TIMEOUT_MS = 15000;

function initValuescan() {
  const refresh = document.getElementById('vs-refresh');
  if (refresh && !refresh.dataset.bound) {
    refresh.dataset.bound = '1';
    refresh.onclick = loadValuescan;
  }

  if (!valuescanLoaded) {
    valuescanLoaded = true;
    loadValuescan();
  } else if (valuescanTrendChart) {
    valuescanTrendChart.resize();
  }
}

async function loadValuescan() {
  const token = (document.getElementById('vs-token-input').value || 'BTC').trim().toUpperCase();
  document.getElementById('vs-token-input').value = token;
  setValuescanStatus('Loading');
  closeValuescanStreams();
  renderValuescanFeatures({ features: [], columns: [] });

  const tokenParam = encodeURIComponent(token);
  const overviewTask = fetchJson(API + '/valuescan/ai/overview?token=' + tokenParam)
    .then(overview => {
      renderValuescanOverview(overview);
      setValuescanStatus('Overview loaded');
      return overview;
    })
    .catch(error => {
      renderValuescanError(error.message);
      setValuescanStatus('Valuescan error');
      appendStreamItem('overview', error.message);
      return null;
    });

  const listsTask = fetchJson(API + '/valuescan/ai/lists')
    .then(renderValuescanLists)
    .catch(error => appendStreamItem('lists', error.message));

  const featuresTask = fetchJson(API + '/valuescan/ai/features?token=' + tokenParam + '&timeframe=4h&limit=3')
    .then(renderValuescanFeatures)
    .catch(error => {
      renderValuescanFeatures({ features: [], columns: [] });
      appendStreamItem('features', error.message);
    });

  const overview = await overviewTask;
  await Promise.all([listsTask, featuresTask]);
  const tokenId = overview && overview.token && overview.token.vsTokenId ? String(overview.token.vsTokenId) : '';
  startValuescanStreams(tokenId);
}

async function fetchJson(url, timeoutMs = VALUESCAN_FETCH_TIMEOUT_MS) {
  const controller = window.AbortController ? new AbortController() : null;
  const timer = controller ? window.setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(url, controller ? { signal: controller.signal } : {});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body.message || body.error || ('HTTP ' + response.status));
    }
    return body;
  } catch (error) {
    if (error && error.name === 'AbortError') {
      throw new Error('Request timed out: ' + url.replace(API, ''));
    }
    throw error;
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}

function renderValuescanOverview(data) {
  const sentiment = data.socialSentiment || {};
  const trend = (data.priceMarket || [])[0] || {};
  const bull = ratioValue(sentiment.bullishRatio);
  const bear = ratioValue(sentiment.bearishRatio);
  const trendLabel = trend.priceMarketType === 1 ? 'Rising' : trend.priceMarketType === 2 ? 'Falling' : 'Mixed';
  const trendClass = trend.priceMarketType === 1 ? 'green' : trend.priceMarketType === 2 ? 'red' : '';

  const cards = [
    { label: 'Token', value: (data.token && data.token.symbol) || 'BTC' },
    { label: 'Bullish', value: pctText(bull), cls: bull >= bear ? 'green' : '' },
    { label: 'Bearish', value: pctText(bear), cls: bear > bull ? 'red' : '' },
    { label: 'Whale Trend', value: trendLabel, cls: trendClass },
  ];
  document.getElementById('vs-summary-cards').innerHTML = cards.map(c =>
    '<div class="summary-card"><div class="label">' + escapeHtml(c.label) + '</div><div class="value ' + (c.cls || '') + '">' + escapeHtml(c.value) + '</div></div>'
  ).join('');

  renderDenseRows(data.supportResistance || []);
  renderTrendChart(data.priceMarket || []);
  renderSentiment(sentiment);
  renderMarketAnalysis(data.marketAnalysis || []);
}

function renderValuescanError(message) {
  document.getElementById('vs-summary-cards').innerHTML =
    '<div class="summary-card"><div class="label">Valuescan</div><div class="value red">Offline</div></div>';
  document.getElementById('vs-dense-rows').innerHTML = '<tr><td colspan="2">' + escapeHtml(message) + '</td></tr>';
  document.getElementById('vs-sentiment-bars').innerHTML = '';
  document.getElementById('vs-sentiment-notes').innerHTML = '';
  document.getElementById('vs-market-analysis').innerHTML = '';
  renderValuescanFeatures({ features: [], columns: [] });
}

function renderDenseRows(rows) {
  const tbody = document.getElementById('vs-dense-rows');
  const shown = rows.slice(0, 30);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="2">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(r => {
    const price = Number(r.price || 0);
    return '<tr><td>$' + (price ? price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : escapeHtml(String(r.price || ''))) +
      '</td><td>' + escapeHtml(String(r.denseArea || '')) + '</td></tr>';
  }).join('');
}

function renderTrendChart(rows) {
  const el = document.getElementById('vs-trend-chart');
  if (!el) return;
  if (!window.echarts) {
    const latest = (rows || [])[0] || {};
    el.innerHTML = '<div class="chart-fallback">Whale Trend: ' + escapeHtml(trendName(latest.priceMarketType)) + '</div>';
    return;
  }
  if (!valuescanTrendChart) valuescanTrendChart = echarts.init(el, 'dark');
  const points = rows.slice().reverse().map(r => [Number(r.date || r.updateTime || 0), Number(r.priceMarketType || 0)]);
  valuescanTrendChart.setOption({
    backgroundColor: '#161b22',
    tooltip: { trigger: 'axis', formatter: p => formatTime(p[0].data[0]) + '<br>' + trendName(p[0].data[1]) },
    grid: { left: 42, right: 16, top: 18, bottom: 36 },
    xAxis: { type: 'time', axisLabel: { color: '#8b949e' } },
    yAxis: {
      type: 'value', min: 0, max: 3, interval: 1,
      axisLabel: { color: '#8b949e', formatter: v => v === 1 ? 'Up' : v === 2 ? 'Down' : '' }
    },
    series: [{
      type: 'line',
      data: points,
      step: 'end',
      showSymbol: false,
      lineStyle: { color: '#d2991d', width: 1.5 },
      areaStyle: { color: 'rgba(210,153,29,.12)' },
    }],
  });
}

function renderSentiment(data) {
  const rows = [
    ['Bullish', ratioValue(data.bullishRatio), 'bull'],
    ['Neutral', ratioValue(data.neutralRatio), 'neutral'],
    ['Bearish', ratioValue(data.bearishRatio), 'bear'],
  ];
  document.getElementById('vs-sentiment-bars').innerHTML = rows.map(r =>
    '<div class="sentiment-row"><div class="sentiment-label"><span>' + r[0] + '</span><span>' + pctText(r[1]) +
    '</span></div><div class="sentiment-track"><div class="sentiment-fill ' + r[2] + '" style="width:' + Math.max(0, Math.min(100, r[1] * 100)) +
    '%"></div></div></div>'
  ).join('');

  const notes = []
    .concat((data.bullishContents || []).slice(0, 1))
    .concat((data.neutralContents || []).slice(0, 1))
    .concat((data.bearishContents || []).slice(0, 1));
  document.getElementById('vs-sentiment-notes').innerHTML = notes.map(n =>
    '<div class="note-item">' + escapeHtml(n.english || n.content || '') + '</div>'
  ).join('');
}

function renderMarketAnalysis(rows) {
  const target = document.getElementById('vs-market-analysis');
  const shown = rows.slice(0, 8);
  if (!shown.length) {
    target.innerHTML = '<div class="analysis-item"><div class="analysis-content">No data</div></div>';
    return;
  }
  target.innerHTML = shown.map(item =>
    '<div class="analysis-item"><div class="analysis-meta">' + escapeHtml(item.uniqueId || '') + ' | ' + formatTime(item.ts) +
    '</div><div class="analysis-content">' + escapeHtml(item.content || '') + '</div></div>'
  ).join('');
}

function renderValuescanLists(data) {
  renderCoinRows('vs-opportunity-rows', data.opportunities || [], true);
  renderCoinRows('vs-risk-rows', data.risks || [], false);
  renderFundsRows(data.funds || []);

  const messages = data.messages || {};
  []
    .concat((messages.opportunities || []).slice(0, 3).map(m => ['opportunity', m]))
    .concat((messages.risks || []).slice(0, 3).map(m => ['risk', m]))
    .concat((messages.funds || []).slice(0, 3).map(m => ['funds', m]))
    .forEach(pair => appendStreamItem(pair[0], summarizeSignal(pair[1])));
}

function renderValuescanFeatures(data) {
  const tbody = document.getElementById('vs-feature-rows');
  if (!tbody) return;
  const rows = data.features || [];
  const latest = rows.length ? rows[rows.length - 1] : {};
  const columns = (data.columns || []).slice(0, 12);
  if (!columns.length) {
    tbody.innerHTML = '<tr><td colspan="2">No data</td></tr>';
    return;
  }
  tbody.innerHTML = columns.map(col => {
    const value = latest[col];
    return '<tr><td>' + escapeHtml(col) + '</td><td>' + numberText(value) + '</td></tr>';
  }).join('');
}

function renderCoinRows(targetId, rows, positive) {
  const tbody = document.getElementById(targetId);
  const shown = rows.slice(0, 25);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="4">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(r => {
    const score = Number(r.score ?? r.scoring ?? 0);
    const pct24 = Number(r.percentChange24h ?? 0);
    const cls = positive ? 'score-positive' : 'score-negative';
    return '<tr><td>' + escapeHtml(r.symbol || '') + '</td><td class="' + cls + '">' + score.toFixed(0) +
      '</td><td>' + escapeHtml(String(r.grade ?? '')) + '</td><td class="' + (pct24 >= 0 ? 'score-positive' : 'score-negative') + '">' +
      pct24.toFixed(1) + '%</td></tr>';
  }).join('');
}

function renderFundsRows(rows) {
  const tbody = document.getElementById('vs-funds-rows');
  const shown = rows.slice(0, 25);
  if (!shown.length) {
    tbody.innerHTML = '<tr><td colspan="3">No data</td></tr>';
    return;
  }
  tbody.innerHTML = shown.map(r =>
    '<tr><td>' + escapeHtml(r.symbol || '') + '</td><td>' + tradeTypeName(r.tradeType) + '</td><td>' +
    formatTime(r.updateTime) + '</td></tr>'
  ).join('');
}

function startValuescanStreams(tokenId) {
  if (!window.EventSource) {
    appendStreamItem('stream', 'EventSource is not available in this browser.');
    return;
  }
  openValuescanStream(API + '/valuescan/ai/stream?type=market', 'market');
  openValuescanStream(API + '/valuescan/ai/stream?type=signal&tokens=' + encodeURIComponent(tokenId || ''), 'signal');
}

function openValuescanStream(url, label) {
  const source = new EventSource(url);
  valuescanStreams.push(source);
  source.addEventListener('connected', e => appendStreamItem(label, e.data || 'connected'));
  source.addEventListener('heartbeat', e => setValuescanStatus((e.data || 'ping') + ' ' + label));
  source.addEventListener('market', e => appendStreamItem('market', e.data));
  source.addEventListener('signal', e => appendStreamItem('signal', normalizeSignalPayload(e.data)));
  source.addEventListener('error', e => {
    if (e.data) appendStreamItem('error', e.data);
  });
  source.onmessage = e => appendStreamItem(label, e.data || '');
}

function closeValuescanStreams() {
  valuescanStreams.forEach(s => s.close());
  valuescanStreams = [];
  const feed = document.getElementById('vs-stream-feed');
  if (feed) feed.innerHTML = '';
}

function appendStreamItem(type, content) {
  const feed = document.getElementById('vs-stream-feed');
  if (!feed) return;
  const text = typeof content === 'string' ? content : JSON.stringify(content);
  const item = document.createElement('div');
  item.className = 'stream-item';
  item.innerHTML = '<div class="stream-meta">' + escapeHtml(type) + ' | ' + formatTime(Date.now()) +
    '</div><div class="stream-content">' + escapeHtml(text) + '</div>';
  feed.prepend(item);
  while (feed.children.length > 60) feed.removeChild(feed.lastChild);
}

function normalizeSignalPayload(raw) {
  try {
    const outer = JSON.parse(raw);
    if (outer.content) {
      try { return summarizeSignal(JSON.parse(outer.content)); }
      catch (_) { return outer.content; }
    }
    return summarizeSignal(outer);
  } catch (_) {
    return raw;
  }
}

function summarizeSignal(signal) {
  const parts = [
    signal.symbol || signal.name || 'token',
    signal.scoring != null ? 'score ' + signal.scoring : '',
    signal.grade != null ? 'grade ' + signal.grade : '',
    signal.price != null ? '$' + signal.price : '',
    signal.percentChange24h != null ? Number(signal.percentChange24h).toFixed(1) + '% 24h' : '',
  ].filter(Boolean);
  return parts.join(' | ');
}

function setValuescanStatus(text) {
  const status = document.getElementById('vs-status');
  if (status) status.textContent = text;
}

function ratioValue(v) {
  const n = Number(v || 0);
  return n > 1 ? n / 100 : n;
}

function pctText(v) {
  return (Number(v || 0) * 100).toFixed(1) + '%';
}

function numberText(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return '--';
  return Math.abs(n) >= 10 ? n.toFixed(1) : n.toFixed(3);
}

function trendName(v) {
  return Number(v) === 1 ? 'Rising' : Number(v) === 2 ? 'Falling' : 'Mixed';
}

function tradeTypeName(v) {
  if (Number(v) === 1) return 'Spot';
  if (Number(v) === 2) return 'Perp';
  if (Number(v) === 3) return 'Delivery';
  return String(v || '');
}

function formatTime(ts) {
  const n = Number(ts || 0);
  if (!n) return '--';
  return new Date(n).toLocaleString();
}

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

window.addEventListener('resize', () => { valuescanTrendChart && valuescanTrendChart.resize(); });

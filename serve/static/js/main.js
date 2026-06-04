// Navigation router + shared state

const API = '/api';

function switchModule(name) {
  document.querySelectorAll('.module').forEach(m => m.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const mod = document.getElementById('module-' + name);
  const nav = document.querySelector('[data-module="' + name + '"]');
  if (mod) mod.classList.add('active');
  if (nav) nav.classList.add('active');

  if (name === 'ohlcv') initOHLCV();
  if (name === 'returns') initReturns();
  if (name === 'orders') initOrders();
  if (name === 'pipeline') initPipeline();
  if (name === 'valuescan') initValuescan();
}

document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => switchModule(item.dataset.module));
});

// Load sidebar summary
fetch(API + '/returns/summary')
  .then(r => r.json())
  .then(d => {
    document.getElementById('s-pnl').textContent = '$' + (d.total_pnl || 0).toLocaleString();
    document.getElementById('s-wr').textContent = (d.win_rate_pct || 0) + '%';
  })
  .catch(() => {});

// Init first module (show orders first for debugging)
switchModule('orders');

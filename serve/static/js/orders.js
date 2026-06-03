// Trade Orders — simplified v3

let allOrders = [];
let currentPage = 1, perPage = 50;
let currentSort = 'trade_id', sortDir = 'desc';

function initOrders() {
  fetch(API + '/orders/list?per_page=5000')
    .then(r => r.json())
    .then(d => {
      allOrders = d.orders || [];
      document.getElementById('orders-summary').textContent =
        d.total + ' trades | PnL: $' + Math.round(allOrders.reduce((s,o) => s + (+o.pnl||0), 0)).toLocaleString();
      sortAndRender();
    })
    .catch(e => { console.error(e); document.getElementById('orders-tbody').innerHTML = '<tr><td colspan=13>Error loading: ' + e.message + '</td></tr>'; });
}

function sortAndRender() {
  const col = currentSort;
  const dir = sortDir === 'asc' ? 1 : -1;
  allOrders.sort((a, b) => {
    let va = a[col], vb = b[col];
    if (va == null) va = 0;
    if (vb == null) vb = 0;
    if (typeof va === 'string') return dir * va.localeCompare(vb);
    return dir * ((+va || 0) - (+vb || 0));
  });
  renderPage();
}

function renderPage() {
  const tbody = document.getElementById('orders-tbody');
  const start = (currentPage - 1) * perPage;
  const page = allOrders.slice(start, start + perPage);
  if (!page.length) { tbody.innerHTML = '<tr><td colspan=13>No data loaded (' + allOrders.length + ' total)</td></tr>'; return; }

  tbody.innerHTML = page.map(o => {
    const pnl = +o.pnl || 0;
    const pnlPct = +o.pnl_pct || 0;
    return '<tr class="' + (pnl > 0 ? 'win' : 'loss') + '">' +
      '<td>' + o.trade_id + '</td>' +
      '<td>' + (o.entry_time||'').slice(0,19) + '</td>' +
      '<td>' + (o.exit_time||'').slice(0,19) + '</td>' +
      '<td>' + (o.duration||'').slice(0,12) + '</td>' +
      '<td style="color:' + (o.direction==='LONG'?'var(--green)':'var(--red)') + '">' + (o.direction||'?')[0] + '</td>' +
      '<td style="font-size:11px">' + (o.module||'') + '</td>' +
      '<td>' + Math.round(+o.entry_price||0).toLocaleString() + '</td>' +
      '<td>' + Math.round(+o.exit_price||0).toLocaleString() + '</td>' +
      '<td style="color:' + (pnl>0?'var(--green)':'var(--red)') + '">' + Math.round(pnl).toLocaleString() + '</td>' +
      '<td style="color:' + (pnlPct>0?'var(--green)':'var(--red)') + '">' + (+o.pnl_pct||0).toFixed(1) + '%</td>' +
      '<td style="color:var(--green)">' + (+o.max_mfe_pct||0).toFixed(1) + '%</td>' +
      '<td style="color:var(--red)">' + (+o.max_mae_pct||0).toFixed(1) + '%</td>' +
      '<td style="font-size:11px">' + (o.exit_reason||'') + '</td></tr>';
  }).join('');

  // Pagination
  const total = Math.ceil(allOrders.length / perPage) || 1;
  let ph = '';
  for (let i = 1; i <= Math.min(total, 20); i++)
    ph += '<button class="' + (i===currentPage?'active':'') + '" data-p="' + i + '">' + i + '</button>';
  document.getElementById('pagination').innerHTML = ph;
  document.querySelectorAll('.pagination button[data-p]').forEach(b => {
    b.onclick = function() { currentPage = +this.dataset.p; renderPage(); };
  });
}

// Column header sorting
document.querySelectorAll('#orders-table th[data-sort]').forEach(th => {
  th.onclick = function() {
    if (currentSort === this.dataset.sort) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    else { currentSort = this.dataset.sort; sortDir = 'asc'; }
    sortAndRender();
  };
});

// Module filter
document.getElementById('filter-module').onchange = function() {
  fetch(API + '/orders/list?per_page=5000&module=' + this.value)
    .then(r => r.json())
    .then(d => { allOrders = d.orders || []; currentPage = 1; sortAndRender(); });
};

// Direction filter
document.getElementById('filter-direction').onchange = function() {
  fetch(API + '/orders/list?per_page=5000&direction=' + this.value)
    .then(r => r.json())
    .then(d => { allOrders = d.orders || []; currentPage = 1; sortAndRender(); });
};

// Load module filter options
fetch(API + '/orders/filters')
  .then(r => r.json())
  .then(d => {
    const sel = document.getElementById('filter-module');
    sel.innerHTML = '<option value="all">All Modules</option>' + (d.modules||[]).map(m => '<option>' + m + '</option>').join('');
  });

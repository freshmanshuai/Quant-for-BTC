// Returns Analysis Module

let eqChart = null, hmChart = null, distChart = null;

function initReturns() {
  loadSummary();
  if (!eqChart) { eqChart = echarts.init(document.getElementById('chart-equity'), 'dark'); loadEquity(); }
  else eqChart.resize();
  if (!hmChart) { hmChart = echarts.init(document.getElementById('chart-heatmap'), 'dark'); loadHeatmap(); }
  else hmChart.resize();
  if (!distChart) { distChart = echarts.init(document.getElementById('chart-distribution'), 'dark'); loadDistribution(); }
  else distChart.resize();
}

function loadSummary() {
  fetch(API + '/returns/summary')
    .then(r => r.json())
    .then(d => {
      const cards = [
        {label: 'Total Return', value: (d.total_return_pct||0).toFixed(1) + '%', cls: d.total_return_pct >= 0 ? 'green' : 'red'},
        {label: 'Max Drawdown', value: (d.max_drawdown_pct||0).toFixed(1) + '%', cls: 'red'},
        {label: 'Win Rate', value: (d.win_rate_pct||0).toFixed(1) + '%'},
        {label: 'Profit Factor', value: (d.profit_factor||0).toFixed(2)},
        {label: 'Total Trades', value: d.total_trades || 0},
        {label: 'Final Equity', value: '$' + ((d.final_equity||0)/1000).toFixed(0) + 'K'},
      ];
      document.getElementById('summary-cards').innerHTML = cards.map(c =>
        `<div class="summary-card"><div class="label">${c.label}</div><div class="value ${c.cls||''}">${c.value}</div></div>`
      ).join('');
    });
}

function loadEquity() {
  fetch(API + '/returns/equity')
    .then(r => r.json())
    .then(d => {
      eqChart.setOption({
        backgroundColor: '#0d1117',
        tooltip: { trigger: 'axis' },
        grid: [
          { left: 70, right: 20, top: 20, height: '60%' },
          { left: 70, right: 20, top: '73%', height: '20%' },
        ],
        xAxis: [{ type: 'time', gridIndex: 0, axisLabel: { color: '#8b949e' } }, { type: 'time', gridIndex: 1, axisLabel: { show: false } }],
        yAxis: [
          { type: 'value', gridIndex: 0, axisLabel: { color: '#8b949e', formatter: v => '$' + (v/1000).toFixed(0) + 'K' } },
          { type: 'value', gridIndex: 1, axisLabel: { color: '#8b949e', formatter: v => v.toFixed(0) + '%' } },
        ],
        series: [
          { type: 'line', data: d.data.map(r => [r.date, r.equity]), smooth: true, showSymbol: false,
            lineStyle: { color: '#58a6ff', width: 1.5 }, areaStyle: { color: 'rgba(88,166,255,0.08)' }, xAxisIndex: 0, yAxisIndex: 0 },
          { type: 'line', data: d.data.map(r => [r.date, r.drawdown_pct]), smooth: true, showSymbol: false,
            lineStyle: { color: '#f85149', width: 1 }, areaStyle: { color: 'rgba(248,81,73,0.15)' }, xAxisIndex: 1, yAxisIndex: 1 },
        ],
        dataZoom: [{ type: 'inside', xAxisIndex: [0,1] }, { type: 'slider', xAxisIndex: [0,1], bottom: 5, height: 18 }],
      });
    });
}

function loadHeatmap() {
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  fetch(API + '/returns/heatmap')
    .then(r => r.json())
    .then(d => {
      const hd = d.data.map(r => [r.month - 1, d.years.indexOf(r.year), r.return_pct]);
      hmChart.setOption({
        backgroundColor: '#0d1117',
        tooltip: { formatter: p => `${months[p.data[0]]} ${d.years[p.data[1]]}: ${p.data[2].toFixed(1)}%` },
        grid: { left: 60, right: 20, top: 10, bottom: 30 },
        xAxis: { type: 'category', data: months, axisLabel: { color: '#8b949e', fontSize: 11 } },
        yAxis: { type: 'category', data: d.years, axisLabel: { color: '#8b949e' } },
        visualMap: { min: -15, max: 15, orient: 'vertical', right: 0, top: 40,
          inRange: { color: ['#f85149', '#30363d', '#3fb950'] }, textStyle: { color: '#8b949e' } },
        series: [{ type: 'heatmap', data: hd, label: { show: true, fontSize: 9, color: '#c9d1d9', formatter: p => p.data[2].toFixed(1) + '%' } }],
      });
    });
}

function loadDistribution() {
  fetch(API + '/returns/distribution')
    .then(r => r.json())
    .then(d => {
      const wins = d.data.filter(x => x.is_win).map(x => x.pnl_pct);
      const losses = d.data.filter(x => !x.is_win).map(x => x.pnl_pct);
      distChart.setOption({
        backgroundColor: '#0d1117',
        tooltip: { trigger: 'axis' },
        grid: { left: 60, right: 20, top: 20, bottom: 30 },
        xAxis: { type: 'category', data: d.data.map((_,i) => i+1), axisLabel: { color: '#8b949e', fontSize: 10 } },
        yAxis: { type: 'value', axisLabel: { color: '#8b949e', formatter: v => v.toFixed(0) + '%' } },
        series: [
          { type: 'bar', data: d.data.map(x => x.pnl_pct), itemStyle: { color: p => p.data > 0 ? '#3fb950' : '#f85149' } },
        ],
      });
    });
}

window.addEventListener('resize', () => { eqChart && eqChart.resize(); hmChart && hmChart.resize(); distChart && distChart.resize(); });

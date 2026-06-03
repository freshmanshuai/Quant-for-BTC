// BTC Price Candlestick Chart

let ohlcvChart = null;
let currentTF = '15m';

function initOHLCV() {
  if (ohlcvChart) { ohlcvChart.resize(); return; }
  ohlcvChart = echarts.init(document.getElementById('chart-ohlcv'), 'dark');
  loadOHLCV(currentTF);
}

document.querySelectorAll('.tf-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentTF = btn.dataset.tf;
    loadOHLCV(currentTF);
  });
});

function loadOHLCV(tf) {
  const url = tf === '15m'
    ? API + '/ohlcv/data?timeframe=15m&from=2026-04-01'
    : API + '/ohlcv/data?timeframe=' + tf;

  fetch(url)
    .then(r => r.json())
    .then(d => {
      if (!d.data) return;
      const ohlc = d.data.map(b => [b.t, b.o, b.c, b.l, b.h]);
      const vols = d.data.map(b => [b.t, b.v, b.c >= b.o ? 1 : -1]);

      ohlcvChart.setOption({
        backgroundColor: '#0d1117',
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        grid: [
          { left: 60, right: 20, top: 20, height: '65%' },
          { left: 60, right: 20, top: '78%', height: '15%' },
        ],
        xAxis: [
          { type: 'time', gridIndex: 0, axisLabel: { color: '#8b949e' } },
          { type: 'time', gridIndex: 1, axisLabel: { show: false } },
        ],
        yAxis: [
          { type: 'value', gridIndex: 0, scale: true, axisLabel: { color: '#8b949e', formatter: v => '$' + v.toLocaleString() } },
          { type: 'value', gridIndex: 1, axisLabel: { color: '#8b949e' } },
        ],
        series: [
          { type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
            itemStyle: { color: '#3fb950', color0: '#f85149', borderColor: '#3fb950', borderColor0: '#f85149' } },
          { type: 'bar', data: vols.map(v => [v[0], v[1]]), xAxisIndex: 1, yAxisIndex: 1,
            itemStyle: { color: p => p.data[1] > 0 ? '#3fb950' : '#f85149' } },
        ],
        dataZoom: [
          { type: 'inside', xAxisIndex: [0, 1] },
          { type: 'slider', xAxisIndex: [0, 1], bottom: 10, height: 20 },
        ],
      });
    });
}

window.addEventListener('resize', () => ohlcvChart && ohlcvChart.resize());

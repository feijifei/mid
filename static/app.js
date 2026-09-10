const money = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compactMoney = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 });
const staticDemo = window.LOWFREQ_STATIC_DEMO === true;
let selectedPeriod = "1y";
let activeSeries = "portfolio";
let lastResult = null;
let selectedDate = null;
let activeMarket = "cn";
const defaultSymbols = {
  cn: ["600519", "000333", "600887", "600900", "601088", "600941", "601857", "601398", "600036", "601318"],
  pink: ["TCEHY", "RHHBY", "NSRGY", "VWAGY", "BYDDY", "SFTBY", "NTDOY", "BASFY", "DTEGY", "BACHY"],
};

function symbolStorageKey(market = activeMarket) {
  return `lowfreq-symbols-${market}-v1`;
}

function loadSelectedSymbols(market = activeMarket) {
  try {
    const stored = JSON.parse(localStorage.getItem(symbolStorageKey(market)) || "null");
    if (Array.isArray(stored) && stored.length) return stored;
  } catch (_error) {
    localStorage.removeItem(symbolStorageKey(market));
  }
  return [...defaultSymbols[market]];
}

let selectedSymbols = loadSelectedSymbols();
let instrumentNames = {};

const seriesLabels = {
  portfolio: "总体组合",
  "510300": "510300 沪深300",
  "510500": "510500 中证500",
  "518880": "518880 黄金",
  "511010": "511010 国债",
};

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function seriesColor(key) {
  const configured = getComputedStyle(document.documentElement).getPropertyValue(`--series-${key}`).trim();
  if (configured) return configured;
  const palette = ["#2563a5", "#d97706", "#7c3aed", "#b42335", "#16837a", "#8b5a2b"];
  return palette[Math.max(0, selectedSymbols.indexOf(key)) % palette.length];
}

function instrumentLabel(symbol) {
  const name = instrumentNames[symbol];
  return name && name !== symbol ? `${symbol} ${name}` : symbol;
}

async function request(url, options = {}) {
  if (staticDemo) {
    if (url === "/api/backtests") {
      const payload = JSON.parse(options.body || "{}");
      const market = payload.market || "cn";
      const period = payload.period || "1y";
      const response = await fetch(`./demo-data/${market}-${period}.json`);
      if (!response.ok) throw new Error("静态回测数据读取失败");
      return response.json();
    }
    if (url === "/api/strategies" || url === "/api/strategies/reload") {
      const response = await fetch("./demo-data/strategies.json");
      return response.json();
    }
    if (url === "/api/orders") return [];
    if (url === "/api/health") return { status: "ok", data_source: "GitHub Pages静态演示" };
    if (url.startsWith("/api/paper/") || url === "/api/demo/reset") {
      throw new Error("静态演示版不执行模拟下单");
    }
  }
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || "请求失败");
  return body;
}

function toast(message) {
  const el = document.querySelector("#toast");
  el.textContent = message; el.style.display = "block";
  setTimeout(() => { el.style.display = "none"; }, 2600);
}

function renderSimulationSnapshot(point) {
  if (!point) return;
  document.querySelector("#equity").textContent = money.format(point.equity);
  document.querySelector("#cash").textContent = money.format(point.cash);
  document.querySelector("#market-value").textContent = money.format(point.market_value);
  const positions = document.querySelector("#positions");
  positions.innerHTML = point.positions.length ? point.positions.map(p => `<tr><td>${escapeHtml(instrumentLabel(p.symbol))}</td><td>${p.quantity}</td><td>${Number(p.average_price).toFixed(4)}</td><td>${Number(p.last_price).toFixed(4)}</td><td>${money.format(p.market_value)}</td></tr>`).join("") : `<tr><td class="empty" colspan="5">该节点为空仓</td></tr>`;
  document.querySelector("#positions-as-of").textContent = `${point.date} 收盘后`;
  document.querySelector("#as-of").textContent = `回测模拟账户 · ${point.date} 收盘后`;
}

function renderCurrency(currency) {
  const unit = currency === "USD" ? "美元" : "人民币";
  document.querySelectorAll(".currency-unit").forEach(element => { element.textContent = unit; });
}

function selectSimulationDate(date) {
  if (!lastResult) return;
  const snapshots = lastResult.equity_curve;
  const point = snapshots.find(item => item.date === date)
    || snapshots.reduce((nearest, item) => item.date <= date ? item : nearest, snapshots[0]);
  selectedDate = point.date;
  renderSimulationSnapshot(point);
  renderActiveSeries();
  document.querySelector("#trade-detail").innerHTML = `<span>账户快照 · ${escapeHtml(point.date)}</span><strong>持仓${point.positions.length}只 · 现金占比${(point.cash / point.equity * 100).toFixed(1)}%</strong>`;
}

async function refreshPlatformStatus() {
  const [orders, health] = await Promise.all([request("/api/orders"), request("/api/health")]);
  const orderTable = document.querySelector("#orders");
  orderTable.innerHTML = orders.length ? orders.slice(0, 8).map(o => `<tr><td>${escapeHtml(instrumentLabel(o.symbol))}</td><td>${o.side}</td><td>${o.quantity}</td><td>${o.status}</td></tr>`).join("") : `<tr><td class="empty" colspan="4">暂无订单</td></tr>`;
  document.querySelector("#data-source-status").textContent = health.data_source;
}

async function refreshStrategies() {
  const strategies = await request("/api/strategies");
  document.querySelector("#strategy-list").innerHTML = strategies.map(s => `<div class="strategy-row"><div><strong>${s.name}</strong><p>${s.strategy_id}</p></div><span>${s.description}</span><span class="tag">v${s.version}</span></div>`).join("");
}

function calculateMetrics(points, trades) {
  const returns = points.slice(1).map((point, index) => point.equity / points[index].equity - 1);
  const totalReturn = points.at(-1).equity / points[0].equity - 1;
  const annualized = Math.pow(1 + totalReturn, 252 / Math.max(returns.length, 1)) - 1;
  const average = returns.reduce((sum, value) => sum + value, 0) / Math.max(returns.length, 1);
  const variance = returns.reduce((sum, value) => sum + Math.pow(value - average, 2), 0) / Math.max(returns.length - 1, 1);
  const dailyVolatility = Math.sqrt(variance);
  let peak = points[0].equity, maxDrawdown = 0;
  points.forEach(point => { peak = Math.max(peak, point.equity); maxDrawdown = Math.min(maxDrawdown, point.equity / peak - 1); });
  return { total_return: totalReturn, annualized_return: annualized, max_drawdown: maxDrawdown, sharpe: dailyVolatility ? average / dailyVolatility * Math.sqrt(252) : 0, trade_count: trades.length };
}

function renderMetrics(metrics) {
  document.querySelector("#backtest-metrics").innerHTML = [
    ["累计收益", `${(metrics.total_return * 100).toFixed(2)}%`],
    ["年化收益", `${(metrics.annualized_return * 100).toFixed(2)}%`],
    ["最大回撤", `${(metrics.max_drawdown * 100).toFixed(2)}%`],
    ["Sharpe", metrics.sharpe.toFixed(2)],
    ["成交次数", Number(metrics.trade_count).toFixed(0)],
  ].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("");
}

function renderSeriesControl(result) {
  const control = document.querySelector("#series-control");
  control.innerHTML = Object.keys(result.series).map(key => {
    const selected = key === activeSeries;
    return `<button class="series-option${selected ? " active" : ""}" aria-pressed="${selected}" data-series="${escapeHtml(key)}"><span class="series-swatch" style="--series-color:${seriesColor(key)}"></span>${escapeHtml(key === "portfolio" ? seriesLabels.portfolio : instrumentLabel(key))}</button>`;
  }).join("");
  control.querySelectorAll(".series-option").forEach(button => button.addEventListener("click", () => {
    activeSeries = button.dataset.series;
    renderActiveSeries();
  }));
}

function renderActiveSeries() {
  if (!lastResult) return;
  document.querySelectorAll(".series-option").forEach(button => {
    const selected = button.dataset.series === activeSeries;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", selected);
  });
  const points = lastResult.series[activeSeries];
  const trades = activeSeries === "portfolio" ? lastResult.trades : lastResult.trades.filter(trade => trade.symbol === activeSeries);
  renderChart(points, trades, activeSeries, lastResult.baseline_value, selectedDate);
  renderMetrics(activeSeries === "portfolio" ? lastResult.metrics : calculateMetrics(points, trades));
  const activeLabel = activeSeries === "portfolio" ? seriesLabels.portfolio : instrumentLabel(activeSeries);
  document.querySelector("#chart-description").textContent = `${lastResult.data_source} · ${lastResult.start_date} 至 ${lastResult.end_date} · ${activeLabel}`;
  document.querySelector("#trade-detail").innerHTML = `<span>交易事件</span><strong>${escapeHtml(activeLabel)} · 共${trades.length}笔</strong>`;
}

function holdingsText(trade) {
  const snapshot = trade.portfolio_after;
  if (!snapshot) return "持仓快照不可用";
  const positions = snapshot.positions.map(position => `${instrumentLabel(position.symbol)} ${position.quantity}份（${(position.weight * 100).toFixed(1)}%）`);
  positions.push(`现金 ${(snapshot.cash_weight * 100).toFixed(1)}%`);
  return positions.join(" · ");
}

function renderChart(points, trades, seriesKey, baselineValue, selectedSnapshotDate) {
  const chart = document.querySelector("#chart");
  const width = Math.max(Math.round(chart.clientWidth), 320);
  const height = Math.max(Math.round(chart.clientHeight), 260);
  const margin = { top: 18, right: 22, bottom: 42, left: width < 560 ? 54 : 72 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const values = [...points.map(p => p.equity), baselineValue];
  const rawMin = Math.min(...values), rawMax = Math.max(...values);
  const padding = Math.max((rawMax - rawMin) * 0.08, rawMax * 0.002);
  const min = rawMin - padding, max = rawMax + padding;
  const span = max - min || 1;
  const baselineY = margin.top + (max - baselineValue) / span * plotHeight;
  const path = points.map((p, i) => {
    const x = margin.left + i / Math.max(points.length - 1, 1) * plotWidth;
    const y = margin.top + (max - p.equity) / span * plotHeight;
    return `${i ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const yTicks = Array.from({ length: 5 }, (_, i) => {
    const value = min + span * i / 4;
    const y = margin.top + plotHeight - plotHeight * i / 4;
    return `<line x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}" stroke="#e6eaed"/><text data-axis-label="y" x="${margin.left - 10}" y="${y + 4}" text-anchor="end">${compactMoney.format(value)}</text>`;
  }).join("");
  const tickCount = width < 560 ? 3 : 5;
  const xTickIndexes = Array.from({ length: tickCount }, (_, i) => Math.round(i * (points.length - 1) / (tickCount - 1)));
  const xTicks = [...new Set(xTickIndexes)].map(index => {
    const x = margin.left + index / Math.max(points.length - 1, 1) * plotWidth;
    const anchor = index === 0 ? "start" : index === points.length - 1 ? "end" : "middle";
    return `<line x1="${x}" y1="${margin.top}" x2="${x}" y2="${height - margin.bottom}" stroke="#f0f2f4"/><text data-axis-label="x" x="${x}" y="${height - 16}" text-anchor="${anchor}">${points[index].date}</text>`;
  }).join("");
  const dateIndexes = new Map(points.map((point, index) => [point.date, index]));
  const markers = trades.flatMap(trade => {
    const index = dateIndexes.get(trade.trade_date);
    if (index === undefined) return [];
    const point = points[index];
    const x = margin.left + index / Math.max(points.length - 1, 1) * plotWidth;
    const y = margin.top + (max - point.equity) / span * plotHeight;
    return [{ trade, x, y }];
  });
  const markerMarkup = markers.map((marker, index) => {
    const { trade, x, y } = marker;
    const buy = trade.side === "BUY";
    const pointsValue = buy
      ? `${x},${y - 7} ${x - 6},${y + 5} ${x + 6},${y + 5}`
      : `${x},${y + 7} ${x - 6},${y - 5} ${x + 6},${y - 5}`;
    const color = buy ? "#16794b" : "#b42335";
    return `<g class="trade-marker" data-marker-index="${index}" role="button" aria-label="${buy ? "买入" : "卖出"} ${escapeHtml(trade.symbol)} ${escapeHtml(trade.trade_date)}"><circle cx="${x}" cy="${y}" r="14" fill="transparent"/><polygon points="${pointsValue}" fill="${color}" stroke="white" stroke-width="1.5"/></g>`;
  }).join("");
  const lineColor = seriesColor(seriesKey);
  const selectedIndex = selectedSnapshotDate ? points.findIndex(point => point.date === selectedSnapshotDate) : -1;
  const selectedPoint = selectedIndex >= 0 ? points[selectedIndex] : null;
  const selectedX = selectedPoint ? margin.left + selectedIndex / Math.max(points.length - 1, 1) * plotWidth : 0;
  const selectedY = selectedPoint ? margin.top + (max - selectedPoint.equity) / span * plotHeight : 0;
  chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="策略权益曲线">
    <defs><clipPath id="plot-clip"><rect x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${plotHeight}"/></clipPath></defs>
    <g class="chart-grid">${yTicks}${xTicks}</g>
    <text data-axis-label="title" x="${margin.left}" y="12">账户权益（${lastResult?.currency === "USD" ? "美元" : "人民币"}）</text>
    <line data-zero-return-line x1="${margin.left}" y1="${baselineY}" x2="${width - margin.right}" y2="${baselineY}" stroke="#7c8791" stroke-width="1.5" stroke-dasharray="6 5"/>
    <text data-axis-label="baseline" x="${width - margin.right - 4}" y="${baselineY - 6}" text-anchor="end">0% 基准 · ${compactMoney.format(baselineValue)}</text>
    <g clip-path="url(#plot-clip)"><path d="${path}" fill="none" stroke="${lineColor}" stroke-width="2.5"/></g>
    <g id="chart-selection" style="display:${selectedPoint ? "block" : "none"}"><line x1="${selectedX}" x2="${selectedX}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="#7c8791" stroke-width="1.5" stroke-dasharray="3 3"/><circle cx="${selectedX}" cy="${selectedY}" r="5" fill="${lineColor}" stroke="white" stroke-width="2"/></g>
    <g id="chart-focus" style="display:none"><line y1="${margin.top}" y2="${height - margin.bottom}" stroke="#7c8791" stroke-dasharray="3 3"/><circle r="4" fill="${lineColor}" stroke="white" stroke-width="2"/></g>
    <rect id="chart-overlay" x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${plotHeight}" fill="transparent"/>
    <g class="trade-markers" clip-path="url(#plot-clip)">${markerMarkup}</g>
  </svg><div id="chart-tooltip" class="chart-tooltip"></div>`;
  chart.querySelectorAll("text").forEach(label => { label.setAttribute("fill", "#687480"); label.setAttribute("font-size", "11"); });
  const overlay = chart.querySelector("#chart-overlay");
  const focus = chart.querySelector("#chart-focus");
  const tooltip = chart.querySelector("#chart-tooltip");
  overlay.addEventListener("pointermove", event => {
    const rect = chart.getBoundingClientRect();
    const localX = event.clientX - rect.left;
    const index = Math.max(0, Math.min(points.length - 1, Math.round((localX - margin.left) / plotWidth * (points.length - 1))));
    const point = points[index];
    const x = margin.left + index / Math.max(points.length - 1, 1) * plotWidth;
    const y = margin.top + (max - point.equity) / span * plotHeight;
    focus.style.display = "block";
    focus.querySelector("line").setAttribute("x1", x); focus.querySelector("line").setAttribute("x2", x);
    focus.querySelector("circle").setAttribute("cx", x); focus.querySelector("circle").setAttribute("cy", y);
    const change = (point.equity / points[0].equity - 1) * 100;
    tooltip.innerHTML = `<strong>${point.date}</strong><span>权益 ${money.format(point.equity)}</span><span>区间收益 ${change.toFixed(2)}%</span>`;
    tooltip.style.display = "block";
    tooltip.style.left = `${Math.min(Math.max(x + 12, 8), width - 150)}px`;
    tooltip.style.top = `${Math.max(y - 58, 8)}px`;
  });
  overlay.addEventListener("pointerleave", () => { focus.style.display = "none"; tooltip.style.display = "none"; });
  overlay.addEventListener("click", event => {
    const rect = chart.getBoundingClientRect();
    const localX = event.clientX - rect.left;
    const index = Math.max(0, Math.min(points.length - 1, Math.round((localX - margin.left) / plotWidth * (points.length - 1))));
    selectSimulationDate(points[index].date);
  });
  chart.querySelectorAll(".trade-marker").forEach(marker => {
    const item = markers[Number(marker.dataset.markerIndex)];
    const { trade, x, y } = item;
    const action = trade.side === "BUY" ? "买入" : "卖出";
    const showTrade = () => {
      tooltip.innerHTML = `<strong>${action} ${escapeHtml(instrumentLabel(trade.symbol))} · ${escapeHtml(trade.trade_date)}</strong><span>${trade.quantity}份 @ ${Number(trade.price).toFixed(4)}</span><span>${escapeHtml(trade.reason)}</span><span>调仓后：${escapeHtml(holdingsText(trade))}</span>`;
      tooltip.style.display = "block";
      tooltip.style.left = `${Math.min(Math.max(x + 12, 8), width - 250)}px`;
      tooltip.style.top = `${Math.max(y - 76, 8)}px`;
    };
    marker.addEventListener("pointerenter", showTrade);
    marker.addEventListener("pointerleave", () => { tooltip.style.display = "none"; });
    marker.addEventListener("click", () => {
      selectSimulationDate(trade.trade_date);
      document.querySelector("#trade-detail").innerHTML = `<span>${action} ${escapeHtml(instrumentLabel(trade.symbol))} · ${escapeHtml(trade.trade_date)}</span><div><strong>${escapeHtml(trade.reason)}</strong><small>调仓后持仓：${escapeHtml(holdingsText(trade))}</small></div>`;
      showTrade();
    });
  });
}

document.querySelectorAll(".period-option").forEach(option => option.addEventListener("click", () => {
  document.querySelectorAll(".period-option").forEach(item => item.classList.remove("active"));
  option.classList.add("active"); selectedPeriod = option.dataset.period;
}));

async function runBacktest() {
  const button = document.querySelector("#run-backtest");
  button.disabled = true; button.textContent = "计算中";
  try {
    const result = await request("/api/backtests", { method: "POST", body: JSON.stringify({ strategy_id: "simple_trend", period: selectedPeriod, symbols: selectedSymbols, market: activeMarket }) });
    instrumentNames = result.instrument_names || {};
    lastResult = result; activeSeries = "portfolio"; selectedDate = result.equity_curve.at(-1).date;
    renderCurrency(result.currency);
    renderSimulationSnapshot(result.equity_curve.at(-1));
    renderSeriesControl(result); renderActiveSeries();
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = "运行回测"; }
}

document.querySelector("#run-backtest").addEventListener("click", runBacktest);

document.querySelectorAll(".market-option").forEach(option => option.addEventListener("click", () => {
  if (option.dataset.market === activeMarket) return;
  activeMarket = option.dataset.market;
  selectedSymbols = loadSelectedSymbols();
  instrumentNames = {};
  document.querySelector(".market-control").dataset.active = activeMarket;
  document.querySelectorAll(".market-option").forEach(item => {
    const selected = item === option;
    item.classList.toggle("active", selected);
    item.setAttribute("aria-pressed", selected);
  });
  renderUniverse();
  runBacktest();
}));

function renderUniverse() {
  const list = document.querySelector("#universe-list");
  list.innerHTML = selectedSymbols.map(symbol => `<div class="universe-item"><span>${escapeHtml(instrumentLabel(symbol))}</span>${staticDemo ? "" : `<button type="button" data-remove-symbol="${escapeHtml(symbol)}" aria-label="移除 ${escapeHtml(symbol)}">×</button>`}</div>`).join("");
  list.querySelectorAll("[data-remove-symbol]").forEach(button => button.addEventListener("click", () => {
    if (selectedSymbols.length === 1) {
      document.querySelector("#universe-error").textContent = "标的池至少保留一只证券";
      return;
    }
    selectedSymbols = selectedSymbols.filter(symbol => symbol !== button.dataset.removeSymbol);
    localStorage.setItem(symbolStorageKey(), JSON.stringify(selectedSymbols));
    renderUniverse();
  }));
  document.querySelector("#open-universe").textContent = `选股（${selectedSymbols.length}）`;
}

document.querySelector("#open-universe").addEventListener("click", () => {
  document.querySelector("#universe-error").textContent = "";
  renderUniverse();
  const input = document.querySelector("#symbol-input");
  input.placeholder = activeMarket === "pink" ? "例如 TCEHY" : "例如 600519";
  input.inputMode = activeMarket === "pink" ? "text" : "numeric";
  document.querySelector(".symbol-input").hidden = staticDemo;
  document.querySelector("#apply-universe").textContent = staticDemo ? "关闭" : "应用并回测";
  document.querySelector("#universe-error").textContent = staticDemo ? "静态演示版使用预设标的池" : "";
  document.querySelector("#universe-dialog").showModal();
});

document.querySelector("#close-universe").addEventListener("click", () => document.querySelector("#universe-dialog").close());
document.querySelector("#apply-universe").addEventListener("click", () => {
  document.querySelector("#universe-dialog").close();
  if (!staticDemo) runBacktest();
});
document.querySelector("#universe-form").addEventListener("submit", event => {
  event.preventDefault();
  const input = document.querySelector("#symbol-input");
  const symbol = input.value.trim().toUpperCase();
  const error = document.querySelector("#universe-error");
  const valid = activeMarket === "pink" ? /^[A-Z0-9-]{1,10}$/.test(symbol) : /^\d{6}$/.test(symbol);
  if (!valid) {
    error.textContent = activeMarket === "pink" ? "请输入有效的OTC英文代码" : "请输入6位股票或ETF代码";
    return;
  }
  if (!selectedSymbols.includes(symbol)) selectedSymbols.push(symbol);
  localStorage.setItem(symbolStorageKey(), JSON.stringify(selectedSymbols));
  input.value = ""; error.textContent = ""; renderUniverse();
});

document.querySelector("#paper-rebalance").addEventListener("click", async () => {
  try {
    const result = await request("/api/paper/rebalance/simple_trend", { method: "POST" });
    document.querySelector("#trade-result").textContent = JSON.stringify(result, null, 2);
    await refreshPlatformStatus(); toast("模拟调仓已完成");
  } catch (error) { toast(error.message); }
});

document.querySelector("#reset-demo").addEventListener("click", async () => {
  await request("/api/demo/reset", { method: "POST" });
  document.querySelector("#trade-result").textContent = "模拟账户已重置";
  await refreshPlatformStatus(); toast("账户已重置");
});

document.querySelector("#reload-strategies").addEventListener("click", async () => {
  try { await request("/api/strategies/reload", { method: "POST" }); await refreshStrategies(); toast("策略已重新加载"); }
  catch (error) { toast(error.message); }
});

document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll(".nav-item, .view").forEach(el => el.classList.remove("active"));
  button.classList.add("active"); document.querySelector(`#${button.dataset.view}`).classList.add("active");
  document.querySelector("#page-title").textContent = {overview: "运行总览", research: "策略研究", trading: "模拟交易"}[button.dataset.view];
}));

renderUniverse();
if (staticDemo) {
  document.querySelector("#reload-strategies").hidden = true;
  document.querySelector(".icon-link").hidden = true;
  document.querySelector('.nav-item[data-view="trading"]').hidden = true;
}
Promise.all([refreshPlatformStatus(), refreshStrategies(), runBacktest()]).catch(error => toast(error.message));
window.addEventListener("resize", () => { if (lastResult) renderActiveSeries(); });

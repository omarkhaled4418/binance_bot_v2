/* ═══════════════════════════════════════════════════════════════════
   Binance Sell Bot – Frontend Logic with Client-Side Credentials
   ═══════════════════════════════════════════════════════════════════ */

// ── Socket.IO connection ─────────────────────────────────────────────────────
const socket = io();

// ── DOM refs ─────────────────────────────────────────────────────────────────
const modeBadge        = document.getElementById('mode-badge');
const statusBadge      = document.getElementById('status-badge');
const botForm          = document.getElementById('bot-form');
const btnTestnet       = document.getElementById('btn-testnet');
const btnLive          = document.getElementById('btn-live');
const modeInput        = document.getElementById('mode-input');

// API Credentials refs
const apiKeyInput      = document.getElementById('api-key');
const apiSecretInput   = document.getElementById('api-secret');
const apiKeyLabel      = document.getElementById('api-key-label');
const apiSecretLabel   = document.getElementById('api-secret-label');
const toggleSecretBtn  = document.getElementById('toggle-secret-btn');
const toggleApiCardBtn = document.getElementById('toggle-api-card-btn');
const apiCardBody      = document.getElementById('api-card-body');
const verifyKeysBtn    = document.getElementById('verify-keys-btn');
const clearKeysBtn     = document.getElementById('clear-keys-btn');
const apiVerifyResult  = document.getElementById('api-verify-result');

// Trading form refs
const symbolInput      = document.getElementById('symbol');
const targetTypeSelect = document.getElementById('target-type');
const targetLabel      = document.getElementById('target-label');
const targetHint       = document.getElementById('target-hint');
const targetPriceInput = document.getElementById('target-price');
const quantityTypeSelect = document.getElementById('quantity-type');
const quantityLabel      = document.getElementById('quantity-label');
const quantityHint       = document.getElementById('quantity-hint');
const quantityInput    = document.getElementById('quantity');
const dropPercentageInput = document.getElementById('drop-percentage');
const n8nWebhookUrlInput  = document.getElementById('n8n-webhook-url');
const autoConvertSelect   = document.getElementById('auto-convert');
const autoRestartSelect   = document.getElementById('auto-restart-on-trigger');
const checkPriceBtn    = document.getElementById('check-price-btn');
const currentPriceHint = document.getElementById('current-price-hint');
const startBtn         = document.getElementById('start-btn');
const stopBtn          = document.getElementById('stop-btn');
const formError        = document.getElementById('form-error');

// Stat & chart refs
const statPrice        = document.getElementById('stat-price');
const statTarget       = document.getElementById('stat-target');
const statDistance     = document.getElementById('stat-distance');
const statAmount       = document.getElementById('stat-amount');

const chartSymbolLabel = document.getElementById('chart-symbol');
const chartPlaceholder = document.getElementById('chart-placeholder');
const targetIndicator  = document.getElementById('target-indicator');
const targetIndicatorV = document.getElementById('target-indicator-value');

const logBody          = document.getElementById('log-body');
const clearLogBtn      = document.getElementById('clear-log-btn');

const triggeredOverlay = document.getElementById('triggered-overlay');
const overlayDesc      = document.getElementById('overlay-desc');
const overlayCloseBtn  = document.getElementById('overlay-close-btn');

// ── State ─────────────────────────────────────────────────────────────────────
let currentMode   = 'testnet';  // 'testnet' | 'live'
let botStatus     = 'idle';     // 'idle' | 'running' | 'triggered' | 'error'
let priceHistory  = [];         // { time, price }[]
let targetPrice   = 0;
let currentPrice  = 0;
let configSymbol  = '';

const MAX_PRICE_POINTS = 120;   // keep last 120 ticks on chart

// ── Target & Quantity Select toggles ──────────────────────────────────────────
targetTypeSelect.addEventListener('change', () => {
  if (targetTypeSelect.value === 'percentage') {
    targetLabel.textContent = 'Target Profit (%)';
    targetPriceInput.placeholder = 'e.g. 10 (for +10% profit)';
    targetHint.textContent = 'Sell order triggers when price rises by this % above entry price';
  } else {
    targetLabel.textContent = 'Target Sell Price (USDT)';
    targetPriceInput.placeholder = 'e.g. 70000';
    targetHint.textContent = 'Sell order triggers when price reaches this value';
  }
});

quantityTypeSelect.addEventListener('change', () => {
  if (quantityTypeSelect.value === 'usdt') {
    quantityLabel.textContent = 'Amount to Sell (USDT)';
    quantityInput.placeholder = 'e.g. 100';
    quantityHint.textContent = 'Total USDT value to sell (e.g. $100)';
  } else {
    quantityLabel.textContent = 'Amount to Sell (Coin Quantity)';
    quantityInput.placeholder = 'e.g. 0.001';
    quantityHint.textContent = 'Base asset quantity (e.g. BTC, ETH…)';
  }
});

// ── API Key Local Storage Management ──────────────────────────────────────────
function getStorageKeys(mode) {
  return {
    keyName: mode === 'live' ? 'binance_live_api_key' : 'binance_testnet_api_key',
    secretName: mode === 'live' ? 'binance_live_api_secret' : 'binance_testnet_api_secret',
  };
}

function loadSavedKeys(mode) {
  const { keyName, secretName } = getStorageKeys(mode);
  apiKeyInput.value = localStorage.getItem(keyName) || '';
  apiSecretInput.value = localStorage.getItem(secretName) || '';
  
  if (apiKeyLabel) {
    apiKeyLabel.textContent = mode === 'live' ? 'Live Binance API Key' : 'Testnet Binance API Key';
  }
  if (apiSecretLabel) {
    apiSecretLabel.textContent = mode === 'live' ? 'Live Binance API Secret' : 'Testnet Binance API Secret';
  }

  // Load saved n8n webhook URL
  const savedWebhook = localStorage.getItem('n8n_webhook_url');
  if (savedWebhook && !n8nWebhookUrlInput.value) {
    n8nWebhookUrlInput.value = savedWebhook;
  }
}

function saveKeys(mode) {
  const { keyName, secretName } = getStorageKeys(mode);
  if (apiKeyInput.value.trim()) {
    localStorage.setItem(keyName, apiKeyInput.value.trim());
  } else {
    localStorage.removeItem(keyName);
  }

  if (apiSecretInput.value.trim()) {
    localStorage.setItem(secretName, apiSecretInput.value.trim());
  } else {
    localStorage.removeItem(secretName);
  }
}

apiKeyInput.addEventListener('input', () => saveKeys(currentMode));
apiSecretInput.addEventListener('input', () => saveKeys(currentMode));

n8nWebhookUrlInput.addEventListener('input', () => {
  localStorage.setItem('n8n_webhook_url', n8nWebhookUrlInput.value.trim());
});

// Toggle Secret Visibility
toggleSecretBtn.addEventListener('click', () => {
  if (apiSecretInput.type === 'password') {
    apiSecretInput.type = 'text';
    toggleSecretBtn.textContent = '🔒 Hide';
  } else {
    apiSecretInput.type = 'password';
    toggleSecretBtn.textContent = '👁️ Show';
  }
});

// Collapse/Expand API Card
toggleApiCardBtn.addEventListener('click', () => {
  const isHidden = apiCardBody.style.display === 'none';
  apiCardBody.style.display = isHidden ? 'block' : 'none';
  toggleApiCardBtn.textContent = isHidden ? 'Collapse ▲' : 'Expand ▼';
});

// Clear Keys Button
clearKeysBtn.addEventListener('click', () => {
  if (confirm(`Clear saved credentials for ${currentMode.toUpperCase()} mode?`)) {
    const { keyName, secretName } = getStorageKeys(currentMode);
    localStorage.removeItem(keyName);
    localStorage.removeItem(secretName);
    apiKeyInput.value = '';
    apiSecretInput.value = '';
    apiVerifyResult.className = 'api-verify-result hidden';
    apiVerifyResult.textContent = '';
    appendLog('info', `🗑️ Cleared saved credentials for ${currentMode.toUpperCase()} mode.`);
  }
});

// Verify & Check Balance Button
verifyKeysBtn.addEventListener('click', async () => {
  const key = apiKeyInput.value.trim();
  const secret = apiSecretInput.value.trim();
  const isTestnet = currentMode === 'testnet';

  apiVerifyResult.className = 'api-verify-result';
  apiVerifyResult.textContent = '⏳ Verifying keys with Binance…';

  try {
    const res = await fetch('/api/verify-keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key: key,
        api_secret: secret,
        testnet: isTestnet,
      }),
    });

    const data = await res.json();
    if (!res.ok || !data.ok) {
      apiVerifyResult.className = 'api-verify-result error';
      apiVerifyResult.innerHTML = `<strong>❌ Connection Failed:</strong><br>${data.error || 'Invalid API Key or Secret'}`;
      return;
    }

    apiVerifyResult.className = 'api-verify-result success';
    const tradingBadge = data.can_trade ? '🟢 Trading Enabled' : '🟡 View Only';
    apiVerifyResult.innerHTML = `
      <strong>✅ Connected Successfully (${data.mode})!</strong><br>
      • Status: ${tradingBadge}<br>
      • Free USDT Balance: <strong>$${fmt(data.usdt_balance, 2)} USDT</strong>
    `;

    appendLog('success', `🔑 [${data.mode}] API Keys Verified! Free Balance: $${fmt(data.usdt_balance, 2)} USDT`);

  } catch (err) {
    apiVerifyResult.className = 'api-verify-result error';
    apiVerifyResult.textContent = '❌ Network error verifying keys: ' + err.message;
  }
});

// ── Chart.js setup ────────────────────────────────────────────────────────────
const ctx = document.getElementById('price-chart').getContext('2d');

const chart = new Chart(ctx, {
  type: 'line',
  data: {
    labels: [],
    datasets: [
      {
        label: 'Price',
        data: [],
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(59,130,246,0.08)',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.4,
        fill: true,
      },
      {
        label: 'Target',
        data: [],
        borderColor: '#f59e0b',
        borderWidth: 1.5,
        borderDash: [6, 4],
        pointRadius: 0,
        fill: false,
      },
    ],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 200 },
    interaction: { intersect: false, mode: 'index' },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#151d2e',
        borderColor: 'rgba(255,255,255,0.1)',
        borderWidth: 1,
        titleColor: '#94a3b8',
        bodyColor: '#f1f5f9',
        callbacks: {
          label: ctx => ` ${ctx.dataset.label}: ${Number(ctx.raw).toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
        },
      },
    },
    scales: {
      x: {
        ticks: { color: '#475569', maxTicksLimit: 8, font: { family: "'JetBrains Mono', monospace", size: 10 } },
        grid: { color: 'rgba(255,255,255,0.04)' },
      },
      y: {
        ticks: {
          color: '#475569',
          font: { family: "'JetBrains Mono', monospace", size: 10 },
          callback: v => Number(v).toLocaleString(),
        },
        grid: { color: 'rgba(255,255,255,0.04)' },
      },
    },
  },
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(n, d = 4) {
  if (n === null || n === undefined || n === '') return '—';
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: d });
}

function now() {
  return new Date().toLocaleTimeString('en-US', { hour12: false });
}

function showError(msg) {
  formError.textContent = msg;
  formError.classList.remove('hidden');
}

function clearError() {
  formError.classList.add('hidden');
  formError.textContent = '';
}

// ── Status badge ──────────────────────────────────────────────────────────────
const STATUS_LABELS = {
  idle:      'IDLE',
  running:   '● RUNNING',
  triggered: '✔ TRIGGERED',
  error:     '✖ ERROR',
};

function setStatus(status) {
  botStatus = status;
  statusBadge.className = `badge badge-${status}`;
  statusBadge.textContent = STATUS_LABELS[status] || status.toUpperCase();

  const isRunning = status === 'running';
  startBtn.disabled = isRunning;
  stopBtn.disabled  = !isRunning;
}

// ── Mode toggle ───────────────────────────────────────────────────────────────
function setMode(mode) {
  // Save existing mode keys before switching
  saveKeys(currentMode);

  currentMode = mode;
  modeInput.value = mode;

  btnTestnet.classList.toggle('active', mode === 'testnet');
  btnLive.classList.toggle('active',    mode === 'live');

  modeBadge.className  = `badge badge-${mode === 'live' ? 'live' : 'testnet'}`;
  modeBadge.textContent = mode === 'live' ? 'LIVE' : 'TESTNET';

  // Load new mode credentials
  loadSavedKeys(mode);

  // Clear previous verification result chip
  apiVerifyResult.className = 'api-verify-result hidden';
  apiVerifyResult.textContent = '';
}

btnTestnet.addEventListener('click', () => setMode('testnet'));
btnLive.addEventListener('click',    () => setMode('live'));

// ── Price check button ────────────────────────────────────────────────────────
checkPriceBtn.addEventListener('click', async () => {
  const sym = symbolInput.value.trim().toUpperCase();
  if (!sym) return;
  currentPriceHint.textContent = 'Fetching…';
  try {
    const res = await fetch(`/api/price?symbol=${sym}`);
    const data = await res.json();
    if (data.error) {
      currentPriceHint.textContent = '⚠ ' + data.error;
    } else {
      currentPrice = data.price;
      currentPriceHint.textContent = `Current price: ${fmt(data.price)} USDT`;
      statPrice.textContent = fmt(data.price);
    }
  } catch (e) {
    currentPriceHint.textContent = '⚠ Network error';
  }
});

// ── Log helpers ───────────────────────────────────────────────────────────────
function appendLog(level, message) {
  const empty = logBody.querySelector('.log-empty');
  if (empty) empty.remove();

  const line = document.createElement('div');
  line.className = `log-line ${level}`;
  line.innerHTML = `<span class="log-time">${now()}</span><span class="log-msg">${message}</span>`;
  logBody.appendChild(line);
  logBody.scrollTop = logBody.scrollHeight;
}

clearLogBtn.addEventListener('click', () => {
  logBody.innerHTML = '<div class="log-empty">Log cleared.</div>';
});

// ── Chart updater ─────────────────────────────────────────────────────────────
function pushPrice(price) {
  currentPrice = price;
  const timeLabel = now();
  priceHistory.push({ time: timeLabel, price });

  if (priceHistory.length > MAX_PRICE_POINTS) priceHistory.shift();

  chart.data.labels = priceHistory.map(p => p.time);
  chart.data.datasets[0].data = priceHistory.map(p => p.price);

  if (targetPrice > 0) {
    chart.data.datasets[1].data = priceHistory.map(() => targetPrice);
    targetIndicator.style.display = 'flex';
    targetIndicatorV.textContent = fmt(targetPrice);
  }

  chart.update('none');
  chartPlaceholder.style.display = 'none';

  // Update stat panel
  statPrice.textContent = fmt(price);

  if (targetPrice > 0) {
    const dist = targetPrice - price;
    const pct  = Math.max(0, Math.min(100, (price / targetPrice) * 100));
    const sign  = dist >= 0 ? '+' : '';
    statDistance.textContent = `${sign}${fmt(Math.abs(dist))} (${pct.toFixed(1)}%)`;
    statDistance.style.color = dist <= 0 ? 'var(--green)' : 'var(--text-primary)';
  }
}

// ── Form submit (start bot) ───────────────────────────────────────────────────
botForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  clearError();

  const symbol = symbolInput.value.trim().toUpperCase();
  const targetType = targetTypeSelect.value;
  const tp     = parseFloat(targetPriceInput.value);
  const quantityType = quantityTypeSelect.value;
  const qty    = parseFloat(quantityInput.value);
  const dropPct = parseFloat(dropPercentageInput.value) || 0;
  const n8nUrl  = n8nWebhookUrlInput.value.trim();
  const autoConvert = autoConvertSelect.value === 'true';
  const autoRestart = autoRestartSelect.value === 'true';
  const isTestnet = currentMode === 'testnet';
  const key    = apiKeyInput.value.trim();
  const secret = apiSecretInput.value.trim();

  if (!symbol)       return showError('Please enter a coin symbol (e.g. BTCUSDT).');
  if (isNaN(tp) || tp <= 0) return showError('Enter a valid target price or percentage > 0.');
  if (isNaN(qty) || qty <= 0) return showError('Enter a valid quantity > 0.');
  if (dropPct < 0)   return showError('Drop threshold % must be >= 0.');

  // Warn if target price is below current price
  if (targetType === 'price' && currentPrice > 0 && tp <= currentPrice) {
    const confirmLowTarget = confirm(
      `⚠️ WARNING: Target price ($${tp}) is LESS THAN current price ($${fmt(currentPrice)}).\n\nStarting the bot will trigger a MARKET SELL immediately.\n\nDo you want to proceed?`
    );
    if (!confirmLowTarget) return;
  }

  // Warn for live mode
  if (!isTestnet) {
    const confirmed = confirm(
      `⚠️ LIVE MODE WARNING\n\nYou are about to start the bot in LIVE mode.\nThis will trade REAL funds on your Binance account.\n\nSymbol: ${symbol}\nTarget: ${tp}\nAmount: ${qty}\n\nContinue?`
    );
    if (!confirmed) return;
  }

  startBtn.disabled = true;
  startBtn.textContent = 'Starting…';

  try {
    const res = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol,
        target_type: targetType,
        target_price: tp,
        quantity_type: quantityType,
        quantity: qty,
        drop_percentage: dropPct,
        n8n_webhook_url: n8nUrl,
        auto_convert: autoConvert,
        auto_restart_on_trigger: autoRestart,
        testnet: isTestnet,
        api_key: key,
        api_secret: secret,
      }),
    });

    const data = await res.json();

    if (!res.ok || data.error) {
      showError(data.error || 'Failed to start bot.');
      startBtn.disabled = false;
      startBtn.innerHTML = '<span class="btn-icon">▶</span> Start Bot';
      return;
    }

    // Save active keys
    saveKeys(currentMode);

    // Update UI state
    targetPrice   = tp;
    configSymbol  = symbol;
    priceHistory  = [];

    chartSymbolLabel.textContent = symbol;
    statTarget.textContent  = fmt(tp);
    statAmount.textContent  = quantityType === 'usdt' ? `$${fmt(qty, 2)} USDT` : `${qty} ${symbol}`;

    startBtn.innerHTML = '<span class="btn-icon">▶</span> Start Bot';
    setStatus('running');

  } catch (err) {
    showError('Network error: ' + err.message);
    startBtn.disabled = false;
    startBtn.innerHTML = '<span class="btn-icon">▶</span> Start Bot';
  }
});

// ── Stop button ───────────────────────────────────────────────────────────────
stopBtn.addEventListener('click', async () => {
  await fetch('/api/stop', { method: 'POST' });
  setStatus('idle');
});

// ── Triggered overlay ─────────────────────────────────────────────────────────
function showTriggered() {
  overlayDesc.textContent =
    `🎯 Profit target reached for ${configSymbol}! A MARKET SELL order was executed to close your position. ` +
    `Trading has stopped — the bot will NOT place any further trades until you start it again.`;
  triggeredOverlay.style.display = 'flex';
}

overlayCloseBtn.addEventListener('click', () => {
  triggeredOverlay.style.display = 'none';
});

// ── Socket.IO event handlers ───────────────────────────────────────────────────
socket.on('connect', () => {
  appendLog('info', '🔌 Connected to dashboard server.');
});

socket.on('disconnect', () => {
  appendLog('warning', '⚠ Disconnected from server.');
});

socket.on('price_update', ({ symbol, price, target }) => {
  targetPrice = target;
  pushPrice(price);
});

socket.on('price_drop_alert', (payload) => {
  if (payload.event === 'AUTO_CONVERT_SUCCESS') {
    appendLog('success', `🔄 AUTO-CONVERT COMPLETE! Sold ${payload.symbol} -> Bought ${payload.bought_quantity} ${payload.converted_to_symbol} (+${payload.top_gainer_4h_gain_pct}% 4H Gainer)!`);
  } else {
    appendLog('warning', `🚨 PRICE DROP ALERT: ${payload.symbol} dropped ${payload.actual_drop_percentage}% to $${fmt(payload.current_price)}.`);
  }
});

socket.on('log_entry', ({ level, message }) => {
  appendLog(level, message);
});

socket.on('bot_status', ({ status, config }) => {
  setStatus(status);

  if (config && Object.keys(config).length) {
    if (config.symbol)          { symbolInput.value = config.symbol; chartSymbolLabel.textContent = config.symbol; configSymbol = config.symbol; }
    if (config.target_type)     { targetTypeSelect.value = config.target_type; targetTypeSelect.dispatchEvent(new Event('change')); }
    if (config.target_type === 'percentage' && config.target_percentage) {
      targetPriceInput.value = config.target_percentage;
    } else if (config.target_price) {
      targetPriceInput.value = config.target_price;
    }
    if (config.quantity_type)   { quantityTypeSelect.value = config.quantity_type; quantityTypeSelect.dispatchEvent(new Event('change')); }
    if (config.usdt_amount && config.quantity_type === 'usdt') {
      quantityInput.value = config.usdt_amount;
    } else if (config.quantity) {
      quantityInput.value = config.quantity;
    }

    if (config.target_price)    { targetPrice = config.target_price; statTarget.textContent = fmt(config.target_price); }
    if (config.usdt_amount && config.quantity_type === 'usdt') {
      statAmount.textContent = `$${fmt(config.usdt_amount, 2)} USDT`;
    } else if (config.quantity) {
      statAmount.textContent = `${config.quantity} ${config.symbol}`;
    }
    if (config.drop_percentage) { dropPercentageInput.value = config.drop_percentage; }
    if (config.n8n_webhook_url) { n8nWebhookUrlInput.value = config.n8n_webhook_url; }
    if (config.auto_convert !== undefined) { autoConvertSelect.value = config.auto_convert ? 'true' : 'false'; }
    if (config.auto_restart_on_trigger !== undefined) { autoRestartSelect.value = config.auto_restart_on_trigger ? 'true' : 'false'; }
    if (config.testnet !== undefined) setMode(config.testnet ? 'testnet' : 'live');
  }

  if (status === 'triggered') {
    showTriggered();
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────
setMode('testnet');
setStatus('idle');

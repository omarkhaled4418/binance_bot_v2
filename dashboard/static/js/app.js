/* ═══════════════════════════════════════════════════════════════════
   Binance Sell Bot – Frontend Logic with Client-Side Credentials & Spot Balances
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
const refreshBalBtn    = document.getElementById('refresh-bal-btn');
const coinBalancePill  = document.getElementById('coin-balance-pill');
const coinBalanceText  = document.getElementById('coin-balance-text');
const btnUseMax        = document.getElementById('btn-use-max');
const btnQuickBuy      = document.getElementById('btn-quick-buy');
const targetTypeSelect = document.getElementById('target-type');
const targetLabel      = document.getElementById('target-label');
const targetHint       = document.getElementById('target-hint');
const targetPriceInput = document.getElementById('target-price');
const quantityTypeSelect = document.getElementById('quantity-type');
const quantityLabel      = document.getElementById('quantity-label');
const quantityHint       = document.getElementById('quantity-hint');
const quantityInput    = document.getElementById('quantity');
const usdtWalletHint   = document.getElementById('usdt-wallet-hint');
const dropPercentageInput = document.getElementById('drop-percentage');
const n8nWebhookUrlInput  = document.getElementById('n8n-webhook-url');
const autoConvertSelect   = document.getElementById('auto-convert');
const autoRestartSelect   = document.getElementById('auto-restart-on-trigger');
const checkPriceBtn    = document.getElementById('check-price-btn');
const currentPriceHint = document.getElementById('current-price-hint');
const startBtn         = document.getElementById('start-btn');
const stopBtn          = document.getElementById('stop-btn');
const manualSellBtn    = document.getElementById('manual-sell-btn');
const formError        = document.getElementById('form-error');

// Stat & chart refs
const statPrice        = document.getElementById('stat-price');
const statTarget       = document.getElementById('stat-target');
const statDistance     = document.getElementById('stat-distance');
const statAmount       = document.getElementById('stat-amount');
const statHolding      = document.getElementById('stat-holding');
const statUsdtBalance  = document.getElementById('stat-usdt-balance');

const chartSymbolLabel = document.getElementById('chart-symbol');
const chartPlaceholder = document.getElementById('chart-placeholder');
const targetIndicator  = document.getElementById('target-indicator');
const targetIndicatorV = document.getElementById('target-indicator-value');

const logBody          = document.getElementById('log-body');
const clearLogBtn      = document.getElementById('clear-log-btn');

const triggeredOverlay = document.getElementById('triggered-overlay');
const overlayDesc      = document.getElementById('overlay-desc');
const overlayCloseBtn  = document.getElementById('overlay-close-btn');

// Spot Buy Modal refs
const buyModal         = document.getElementById('buy-modal');
const modalBuyClose    = document.getElementById('modal-buy-close');
const modalCancelBtn   = document.getElementById('modal-cancel-btn');
const modalBuyForm     = document.getElementById('modal-buy-form');
const modalBuyCoin     = document.getElementById('modal-buy-coin');
const modalPayCoin     = document.getElementById('modal-pay-coin');
const modalQuoteBalHint = document.getElementById('modal-quote-bal-hint');
const modalAmountLabel = document.getElementById('modal-amount-label');
const modalBuyAmount   = document.getElementById('modal-buy-amount');
const modalEstReceive  = document.getElementById('modal-est-receive');
const modalEstPrice    = document.getElementById('modal-est-price');
const modalBuyStatus   = document.getElementById('modal-buy-status');
const modalConfirmBuyBtn = document.getElementById('modal-confirm-buy-btn');
const btnModalMax      = document.getElementById('btn-modal-max');
const presetChips      = document.querySelectorAll('.btn-preset-chip[data-amount]');

// Convert All Coins Modal refs
const btnOpenConvertAll       = document.getElementById('btn-open-convert-all');
const convertAllModal         = document.getElementById('convert-all-modal');
const modalConvertAllClose    = document.getElementById('modal-convert-all-close');
const modalConvertAllCancelBtn = document.getElementById('modal-convert-all-cancel-btn');
const modalConvertAllForm     = document.getElementById('modal-convert-all-form');
const convertAllTargetAsset   = document.getElementById('convert-all-target-asset');
const convertAllAssetsList    = document.getElementById('convert-all-assets-list');
const convertAllConfirmCheck  = document.getElementById('convert-all-confirm-check');
const modalConvertAllStatus   = document.getElementById('modal-convert-all-status');
const modalConvertAllSubmitBtn = document.getElementById('modal-convert-all-submit-btn');

// ── State ─────────────────────────────────────────────────────────────────────
let currentMode   = 'testnet';  // 'testnet' | 'live'
let botStatus     = 'idle';     // 'idle' | 'running' | 'triggered' | 'error'
let priceHistory  = [];         // { time, price }[]
let targetPrice   = 0;
let currentPrice  = 0;
let configSymbol  = '';

// Wallet State Cache
let cachedBalances = {
  usdt_free: 0,
  coin_asset: '',
  coin_free: 0,
  coin_value_usdt: 0,
  all_balances: [],
};

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

  const savedWebhook = localStorage.getItem('n8n_webhook_url');
  if (savedWebhook && !n8nWebhookUrlInput.value) {
    n8nWebhookUrlInput.value = savedWebhook;
  }

  if (apiKeyInput.value && apiSecretInput.value) {
    fetchSpotBalances();
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

apiKeyInput.addEventListener('input', () => {
  saveKeys(currentMode);
  fetchSpotBalances();
});

apiSecretInput.addEventListener('input', () => {
  saveKeys(currentMode);
  fetchSpotBalances();
});

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
    resetBalanceDisplay();
    appendLog('info', `🗑️ Cleared saved credentials for ${currentMode.toUpperCase()} mode.`);
  }
});

function resetBalanceDisplay() {
  cachedBalances = { usdt_free: 0, coin_asset: '', coin_free: 0, coin_value_usdt: 0, all_balances: [] };
  if (usdtWalletHint) usdtWalletHint.textContent = 'USDT Wallet: —';
  if (statUsdtBalance) statUsdtBalance.textContent = '—';
  if (statHolding) statHolding.textContent = '—';
  if (coinBalancePill) coinBalancePill.classList.add('hidden');
}

// ── Real-Time Spot Wallet Balance Fetcher ──────────────────────────────────────
async function fetchSpotBalances(optSymbol = null) {
  const sym = (optSymbol || symbolInput.value).trim().toUpperCase();
  const key = apiKeyInput.value.trim();
  const secret = apiSecretInput.value.trim();
  const isTestnet = currentMode === 'testnet';

  try {
    const res = await fetch('/api/balance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: sym,
        api_key: key,
        api_secret: secret,
        testnet: isTestnet,
      }),
    });

    const data = await res.json();
    if (!res.ok || !data.ok) {
      if (usdtWalletHint) usdtWalletHint.textContent = 'USDT: (Requires Keys)';
      return;
    }

    cachedBalances = data;

    // Update USDT stats
    if (usdtWalletHint) {
      usdtWalletHint.textContent = `USDT Wallet: $${fmt(data.usdt_free, 2)}`;
    }
    if (statUsdtBalance) {
      statUsdtBalance.textContent = `$${fmt(data.usdt_free, 2)} USDT`;
    }

    // Update Coin balance if symbol is present
    if (sym && data.coin_asset) {
      if (coinBalancePill && coinBalanceText) {
        coinBalancePill.classList.remove('hidden');
        coinBalanceText.innerHTML = `Available: <strong>${fmt(data.coin_free)} ${data.coin_asset}</strong> (~$${fmt(data.coin_value_usdt, 2)})`;
      }
      if (statHolding) {
        statHolding.textContent = `${fmt(data.coin_free)} ${data.coin_asset}`;
      }
      if (btnQuickBuy) {
        btnQuickBuy.style.display = 'inline-block';
        btnQuickBuy.textContent = `🛒 Buy ${data.coin_asset}`;
      }
    } else {
      if (coinBalancePill) coinBalancePill.classList.add('hidden');
      if (statHolding) statHolding.textContent = '—';
    }

  } catch (err) {
    console.warn('Balance fetch error:', err);
  }
}

// Max 100% Button Handler
if (btnUseMax) {
  btnUseMax.addEventListener('click', () => {
    if (cachedBalances.coin_free <= 0) {
      alert(`You have 0 ${cachedBalances.coin_asset || 'coins'} available in your Spot Wallet to sell.`);
      return;
    }
    if (quantityTypeSelect.value === 'usdt') {
      const val = cachedBalances.coin_value_usdt > 0 ? cachedBalances.coin_value_usdt.toFixed(2) : (cachedBalances.coin_free * currentPrice).toFixed(2);
      quantityInput.value = val;
    } else {
      quantityInput.value = cachedBalances.coin_free;
    }
  });
}

// ── Spot Buy Modal Logic ──────────────────────────────────────────────────────
function getQuoteBalance(quoteAsset) {
  if (quoteAsset === 'USDT') return cachedBalances.usdt_free || 0;
  if (!cachedBalances.all_balances) return 0;
  const match = cachedBalances.all_balances.find(b => b.asset === quoteAsset);
  return match ? match.free : 0;
}

function updateQuoteBalHint() {
  const quote = modalPayCoin.value;
  const bal = getQuoteBalance(quote);
  modalQuoteBalHint.textContent = `Available: ${fmt(bal, 4)} ${quote}`;
  modalAmountLabel.textContent = `Amount to Spend (${quote})`;
}

async function updateBuyModalEstimate() {
  const buyCoin = modalBuyCoin.value.trim().toUpperCase();
  const payCoin = modalPayCoin.value.trim().toUpperCase();
  const amount = parseFloat(modalBuyAmount.value) || 0;

  if (!buyCoin || !payCoin) {
    modalEstReceive.textContent = '—';
    modalEstPrice.textContent = '—';
    return;
  }

  const pairSymbol = `${buyCoin}${payCoin}`;
  try {
    const res = await fetch(`/api/price?symbol=${pairSymbol}`);
    const data = await res.json();
    if (data.price && data.price > 0) {
      modalEstPrice.textContent = `1 ${buyCoin} = ${fmt(data.price, 6)} ${payCoin}`;
      if (amount > 0) {
        const estQty = amount / data.price;
        modalEstReceive.textContent = `≈ ${fmt(estQty, 4)} ${buyCoin}`;
      } else {
        modalEstReceive.textContent = `0.00 ${buyCoin}`;
      }
    } else {
      // Fallback: estimate via USDT
      modalEstPrice.textContent = 'Check pair on Binance';
      modalEstReceive.textContent = `Spend ${amount} ${payCoin}`;
    }
  } catch (err) {
    modalEstPrice.textContent = 'Price check error';
  }
}

function openBuyModal(defaultCoin = '') {
  const sym = defaultCoin || symbolInput.value.trim().toUpperCase();
  const base = sym.replace('USDT', '') || cachedBalances.coin_asset || 'BAR';
  modalBuyCoin.value = base;
  modalBuyAmount.value = '';
  modalBuyStatus.className = 'api-verify-result hidden';
  modalBuyStatus.textContent = '';

  updateQuoteBalHint();
  updateBuyModalEstimate();
  buyModal.style.display = 'flex';
}

function closeBuyModal() {
  buyModal.style.display = 'none';
}

if (btnQuickBuy) {
  btnQuickBuy.addEventListener('click', () => {
    openBuyModal();
  });
}

if (modalBuyClose) modalBuyClose.addEventListener('click', closeBuyModal);
if (modalCancelBtn) modalCancelBtn.addEventListener('click', closeBuyModal);

modalPayCoin.addEventListener('change', () => {
  updateQuoteBalHint();
  updateBuyModalEstimate();
});

modalBuyCoin.addEventListener('input', () => {
  updateBuyModalEstimate();
});

modalBuyAmount.addEventListener('input', () => {
  updateBuyModalEstimate();
});

presetChips.forEach(btn => {
  btn.addEventListener('click', () => {
    const val = btn.getAttribute('data-amount');
    modalBuyAmount.value = val;
    updateBuyModalEstimate();
  });
});

if (btnModalMax) {
  btnModalMax.addEventListener('click', () => {
    const quote = modalPayCoin.value;
    const maxBal = getQuoteBalance(quote);
    if (maxBal <= 0) {
      alert(`You have 0 ${quote} available in your Spot Wallet to spend.`);
      return;
    }
    modalBuyAmount.value = maxBal.toFixed(4);
    updateBuyModalEstimate();
  });
}

if (modalBuyForm) {
  modalBuyForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const buyCoin = modalBuyCoin.value.trim().toUpperCase();
    const payCoin = modalPayCoin.value.trim().toUpperCase();
    const amount = parseFloat(modalBuyAmount.value);
    const key = apiKeyInput.value.trim();
    const secret = apiSecretInput.value.trim();
    const isTestnet = currentMode === 'testnet';

    if (!buyCoin) {
      modalBuyStatus.className = 'api-verify-result error';
      modalBuyStatus.textContent = 'Please enter the coin to buy (e.g. BAR).';
      return;
    }
    if (isNaN(amount) || amount <= 0) {
      modalBuyStatus.className = 'api-verify-result error';
      modalBuyStatus.textContent = 'Please enter an amount > 0.';
      return;
    }

    modalConfirmBuyBtn.disabled = true;
    modalConfirmBuyBtn.textContent = 'Executing Buy…';
    modalBuyStatus.className = 'api-verify-result';
    modalBuyStatus.textContent = `⏳ Placing market buy for ${buyCoin} spending ${amount} ${payCoin}…`;

    try {
      const res = await fetch('/api/quick-buy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          buy_coin: buyCoin,
          pay_coin: payCoin,
          amount: amount,
          api_key: key,
          api_secret: secret,
          testnet: isTestnet,
        }),
      });

      const data = await res.json();
      if (!res.ok || !data.ok) {
        modalBuyStatus.className = 'api-verify-result error';
        modalBuyStatus.innerHTML = `<strong>❌ Buy Failed:</strong><br>${data.error || 'Check balance and trading pair.'}`;
      } else {
        modalBuyStatus.className = 'api-verify-result success';
        modalBuyStatus.innerHTML = `<strong>✅ Buy Successful!</strong><br>Bought ${buyCoin} | New Balance: <strong>${fmt(data.new_balance)} ${data.bought_asset}</strong>`;
        appendLog('success', `🛒 Spot Buy: Spent ${amount} ${payCoin} to buy ${data.symbol}! New ${buyCoin} balance: ${fmt(data.new_balance)}`);
        await fetchSpotBalances(symbolInput.value);
        setTimeout(closeBuyModal, 1500);
      }
    } catch (err) {
      modalBuyStatus.className = 'api-verify-result error';
      modalBuyStatus.textContent = '❌ Network error: ' + err.message;
    } finally {
      modalConfirmBuyBtn.disabled = false;
      modalConfirmBuyBtn.innerHTML = '<span class="btn-icon">🛒</span> Place Market Buy';
    }
  });
}

if (refreshBalBtn) {
  refreshBalBtn.addEventListener('click', () => {
    fetchSpotBalances();
    appendLog('info', '🔄 Spot Wallet balances refreshed.');
  });
}

// ── Convert All Coins Logic ──────────────────────────────────────────────────
async function populateConvertAllAssets() {
  convertAllAssetsList.innerHTML = '<span class="wallet-hint">Scanning Spot Wallet…</span>';
  const key = apiKeyInput.value.trim();
  const secret = apiSecretInput.value.trim();
  const isTestnet = currentMode === 'testnet';

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
    if (!res.ok || !data.ok || !data.balances || !data.balances.length) {
      convertAllAssetsList.innerHTML = '<span class="wallet-hint">No non-zero spot coin holdings found.</span>';
      return;
    }

    cachedBalances.all_balances = data.balances;
    const targetAsset = convertAllTargetAsset.value;
    const filtered = data.balances.filter(b => b.asset !== targetAsset && b.free > 0);

    if (!filtered.length) {
      convertAllAssetsList.innerHTML = `<span class="wallet-hint">No other coins found to convert to ${targetAsset}.</span>`;
      return;
    }

    convertAllAssetsList.innerHTML = filtered.map(b => `
      <div class="holding-item-row">
        <span><strong>${b.asset}</strong></span>
        <span class="font-mono">${fmt(b.free)}</span>
      </div>
    `).join('');

  } catch (err) {
    convertAllAssetsList.innerHTML = `<span class="wallet-hint">Error fetching holdings: ${err.message}</span>`;
  }
}

function openConvertAllModal() {
  convertAllModal.style.display = 'flex';
  convertAllConfirmCheck.checked = false;
  modalConvertAllStatus.className = 'api-verify-result hidden';
  modalConvertAllStatus.textContent = '';
  populateConvertAllAssets();
}

function closeConvertAllModal() {
  convertAllModal.style.display = 'none';
}

if (btnOpenConvertAll) btnOpenConvertAll.addEventListener('click', openConvertAllModal);
if (modalConvertAllClose) modalConvertAllClose.addEventListener('click', closeConvertAllModal);
if (modalConvertAllCancelBtn) modalConvertAllCancelBtn.addEventListener('click', closeConvertAllModal);

convertAllTargetAsset.addEventListener('change', populateConvertAllAssets);

if (modalConvertAllForm) {
  modalConvertAllForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!convertAllConfirmCheck.checked) {
      modalConvertAllStatus.className = 'api-verify-result error';
      modalConvertAllStatus.textContent = 'Please check the confirmation box to proceed.';
      return;
    }

    const target = convertAllTargetAsset.value;
    const key = apiKeyInput.value.trim();
    const secret = apiSecretInput.value.trim();
    const isTestnet = currentMode === 'testnet';

    modalConvertAllSubmitBtn.disabled = true;
    modalConvertAllSubmitBtn.innerHTML = '<span class="btn-icon">⏳</span> Converting All…';
    modalConvertAllStatus.className = 'api-verify-result';
    modalConvertAllStatus.textContent = `⏳ Liquidating all spot coins into ${target}…`;

    try {
      const res = await fetch('/api/convert-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_asset: target,
          testnet: isTestnet,
          api_key: key,
          api_secret: secret,
        }),
      });

      const data = await res.json();

      if (!res.ok || !data.ok) {
        modalConvertAllStatus.className = 'api-verify-result error';
        modalConvertAllStatus.innerHTML = `<strong>❌ Conversion Failed:</strong><br>${data.error || 'Failed to convert coins.'}`;
      } else {
        const soldList = (data.results || []).filter(r => r.status === 'sold');
        modalConvertAllStatus.className = 'api-verify-result success';
        modalConvertAllStatus.innerHTML = `
          <strong>🎉 Conversion Complete!</strong><br>
          • Converted ${soldList.length} assets into <strong>${target}</strong>.<br>
          • Final ${target} Balance: <strong>${fmt(data.final_balance)} ${target}</strong>
        `;
        appendLog('success', `🧹 CONVERT ALL SUCCESS: Liquidated ${soldList.length} assets into ${target}! Final Balance: ${fmt(data.final_balance)} ${target}`);
        await fetchSpotBalances(symbolInput.value);
        setTimeout(closeConvertAllModal, 2500);
      }
    } catch (err) {
      modalConvertAllStatus.className = 'api-verify-result error';
      modalConvertAllStatus.textContent = '❌ Network error: ' + err.message;
    } finally {
      modalConvertAllSubmitBtn.disabled = false;
      modalConvertAllSubmitBtn.innerHTML = '<span class="btn-icon">🧹</span> Convert All Coins Now';
    }
  });
}

// Verify Keys Button
verifyKeysBtn.addEventListener('click', async () => {
  const key = apiKeyInput.value.trim();
  const secret = apiSecretInput.value.trim();
  const isTestnet = currentMode === 'testnet';

  apiVerifyResult.className = 'api-verify-result';
  apiVerifyResult.textContent = '⏳ Verifying keys & fetching wallet…';

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
    
    const topHoldings = data.balances
      .map(b => `${b.asset}: ${fmt(b.free)}`)
      .slice(0, 5)
      .join(', ');

    apiVerifyResult.innerHTML = `
      <strong>✅ Connected Successfully (${data.mode})!</strong><br>
      • Status: ${tradingBadge}<br>
      • Free USDT: <strong>$${fmt(data.usdt_balance, 2)} USDT</strong><br>
      • Top Holdings: <small>${topHoldings || 'None'}</small>
    `;

    appendLog('success', `🔑 [${data.mode}] API Keys Verified! Free USDT Balance: $${fmt(data.usdt_balance, 2)}`);
    fetchSpotBalances();

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
  saveKeys(currentMode);

  currentMode = mode;
  modeInput.value = mode;

  btnTestnet.classList.toggle('active', mode === 'testnet');
  btnLive.classList.toggle('active',    mode === 'live');

  modeBadge.className  = `badge badge-${mode === 'live' ? 'live' : 'testnet'}`;
  modeBadge.textContent = mode === 'live' ? 'LIVE' : 'TESTNET';

  loadSavedKeys(mode);

  apiVerifyResult.className = 'api-verify-result hidden';
  apiVerifyResult.textContent = '';
  fetchSpotBalances();
}

btnTestnet.addEventListener('click', () => setMode('testnet'));
btnLive.addEventListener('click',    () => setMode('live'));

// ── Price & Balance check button ──────────────────────────────────────────────
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
    fetchSpotBalances(sym);
  } catch (e) {
    currentPriceHint.textContent = '⚠ Network error';
  }
});

symbolInput.addEventListener('blur', () => {
  if (symbolInput.value.trim()) {
    fetchSpotBalances(symbolInput.value.trim());
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
  fetchSpotBalances();
});

// ── Manual Market Sell Button ────────────────────────────────────────────────
if (manualSellBtn) {
  manualSellBtn.addEventListener('click', async () => {
    clearError();
    const symbol = symbolInput.value.trim().toUpperCase();
    const isTestnet = currentMode === 'testnet';
    const key = apiKeyInput.value.trim();
    const secret = apiSecretInput.value.trim();

    if (!symbol) {
      return showError('Please enter or select a coin symbol (e.g. PORTALUSDT or BARUSDT) to sell.');
    }

    const modeStr = isTestnet ? 'TESTNET' : '🔴 LIVE (REAL FUNDS)';
    const confirmed = confirm(
      `⚡ MANUAL MARKET SELL CONFIRMATION\n\nMode: ${modeStr}\nSymbol: ${symbol}\n\nAre you sure you want to execute an immediate MARKET SELL for your available holdings on Binance?`
    );
    if (!confirmed) return;

    manualSellBtn.disabled = true;
    manualSellBtn.innerHTML = '<span class="btn-icon">⚡</span> Selling…';

    try {
      const res = await fetch('/api/manual-sell', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: symbol,
          quantity: 0,
          testnet: isTestnet,
          api_key: key,
          api_secret: secret,
        }),
      });

      const data = await res.json();

      if (!res.ok || !data.ok) {
        showError(data.error || 'Manual market sell failed.');
        appendLog('error', `❌ Manual sell failed for ${symbol}: ${data.error || 'Unknown error'}`);
      } else {
        setStatus('idle');
        appendLog(
          'success',
          `⚡ MANUAL MARKET SELL SUCCESS: Sold ${fmt(data.sold_quantity)} ${data.sold_symbol} for $${fmt(data.usdt_proceeds, 2)} USDT!`
        );
        await fetchSpotBalances(symbol);
      }
    } catch (err) {
      showError('Network error executing manual sell: ' + err.message);
    } finally {
      manualSellBtn.disabled = false;
      manualSellBtn.innerHTML = '<span class="btn-icon">⚡</span> Sell Now';
    }
  });
}

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
  fetchSpotBalances();
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
    fetchSpotBalances(payload.converted_to_symbol);
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
    fetchSpotBalances();
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────
setMode('testnet');
setStatus('idle');

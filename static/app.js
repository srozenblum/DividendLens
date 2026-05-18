'use strict';

// ===== Module state =====

let chartInstance        = null;
let portfolioChartInst   = null;
let currentTicker        = null;
let currentName          = null;
let currentSector        = null;
let currentRec           = null;
let currentIndustry      = null;
let currentDivYield      = null;
let currentPer           = null;
let currentDividendTrend = null;
let currentView          = 'analyze';

// ===== Config =====

const METRICS = [
  { key: 'per',           label: 'P/E Ratio',    scoreKey: 'perScore',    fmt: v => v.toFixed(1) + 'x',  tooltip: 'The Price-to-Earnings ratio tells you how many years of current profits you\'re paying for the stock. A PER below 15 is generally considered cheap. Above 20 may mean the stock is expensive — unless the company is growing fast.' },
  { key: 'dividendYield', label: 'Div. Yield',    scoreKey: 'yieldScore',  fmt: v => v.toFixed(2) + '%', hasTrend: true, tooltip: 'Dividend yield shows how much the company pays you annually as a percentage of the current price. A yield between 3% and 6% is the sweet spot for dividend investors. Higher isn\'t always better — a very high yield can signal the dividend is at risk. The historical comparison shows whether the current yield is high or low relative to the past 3 years — a yield above its historical average may indicate the stock is cheaper than usual.' },
  { key: 'priceToBook',   label: 'Price / Book',  scoreKey: 'bookScore',   fmt: v => v.toFixed(2) + 'x', tooltip: 'Compares the stock price to the company\'s net asset value. Below 1 means you\'re buying the company for less than its assets are worth — potentially a bargain. Most useful for banks, utilities and companies with lots of physical assets.' },
  { key: 'debtToEbitda',  label: 'Debt / EBITDA', scoreKey: 'debtScore',   fmt: v => v.toFixed(2) + 'x', tooltip: 'Measures how many years of operating profit it would take to pay off all debt. Below 3 is healthy. Above 4 starts to be a concern. Very stable companies like utilities can handle higher levels.' },
  { key: 'payoutRatio',   label: 'Payout Ratio',  scoreKey: 'payoutScore', fmt: v => v.toFixed(1) + '%', tooltip: 'The percentage of earnings paid out as dividends. Between 40–60% is ideal — enough reward for shareholders while keeping money to grow. Above 80% may be unsustainable long-term.' },
];

const SCORE_CFG = {
  perScore: {
    buy:            { label: 'Undervalued',   cls: 's-green'  },
    neutral:        { label: 'Fair Value',    cls: 's-yellow' },
    expensive:      { label: 'Expensive',     cls: 's-red'    },
    unavailable:    { label: 'N/A',           cls: 's-gray'   },
    not_applicable: { label: 'Not Applicable', cls: 's-gray'  },
  },
  yieldScore: {
    buy:            { label: 'High Yield', cls: 's-green'  },
    neutral:        { label: 'Moderate',   cls: 's-yellow' },
    low:            { label: 'Low Yield',  cls: 's-yellow' },
    none:           { label: 'No Divs',    cls: 's-red'    },
    not_applicable: { label: 'Not Applicable', cls: 's-gray' },
  },
  bookScore: {
    buy:            { label: 'Undervalued',   cls: 's-green'  },
    fair:           { label: 'Fair Value',    cls: 's-yellow' },
    expensive:      { label: 'Overvalued',    cls: 's-red'    },
    unavailable:    { label: 'N/A',           cls: 's-gray'   },
    not_applicable: { label: 'Not Applicable', cls: 's-gray'  },
  },
  debtScore: {
    safe:           { label: 'Low Debt',  cls: 's-green'  },
    moderate:       { label: 'Moderate',  cls: 's-yellow' },
    high:           { label: 'High Debt', cls: 's-red'    },
    unavailable:    { label: 'N/A',       cls: 's-gray'   },
    not_applicable: { label: 'Not Applicable', cls: 's-gray' },
  },
  payoutScore: {
    healthy:        { label: 'Healthy',   cls: 's-green'  },
    high:           { label: 'High',      cls: 's-yellow' },
    very_high:      { label: 'Very High', cls: 's-red'    },
    low:            { label: 'Low',       cls: 's-yellow' },
    unavailable:    { label: 'N/A',       cls: 's-gray'   },
    not_applicable: { label: 'Not Applicable', cls: 's-gray' },
  },
};

const RECOMMENDATION_ORDER = {
  strong_buy:         1,
  buy:                2,
  neutral:            3,
  avoid_overvalued:   4,
  avoid_no_dividends: 5,
  insufficient_data:  6,
};

const REC_CFG = {
  strong_buy:         { icon: '◉', label: 'Recommendation', text: 'Strong buying opportunity',             cls: 'strong_buy'         },
  buy:                { icon: '◎', label: 'Recommendation', text: 'Favorable entry point',                 cls: 'buy'                },
  neutral:            { icon: '◌', label: 'Recommendation', text: 'Neutral — wait for better price',       cls: 'neutral'            },
  avoid_overvalued:   { icon: '✕', label: 'Recommendation', text: 'Pays dividends — not the right price',  cls: 'avoid_overvalued'   },
  avoid_no_dividends: { icon: '◯', label: 'Recommendation', text: 'Does not pay dividends',                cls: 'avoid_no_dividends' },
  insufficient_data:  { icon: '?', label: 'Recommendation', text: 'Insufficient data to evaluate',         cls: 'insufficient_data'  },
};

const TREND_CFG = {
  growing:           { icon: '📈', label: 'Growing dividend',  cls: 's-green'  },
  stable:            { icon: '→',  label: 'Stable dividend',   cls: 's-yellow' },
  declining:         { icon: '📉', label: 'Declining dividend', cls: 's-red'   },
  insufficient_data: { icon: '⚠',  label: 'Limited history',   cls: 's-gray'  },
};

const WL_TREND_CFG = {
  growing:           { icon: '↑', label: 'Growing',  color: '#22c55e' },
  stable:            { icon: '→', label: 'Stable',   color: '#6b7280' },
  declining:         { icon: '↓', label: 'Declining', color: '#ef4444' },
  insufficient_data: { icon: '?', label: 'Limited',  color: '#6b7280' },
};

const DIVIDEND_MINI_TREND = {
  growing:           { text: '↑ Growing',        color: '#22c55e' },
  stable:            { text: '→ Stable',          color: '#6b7280' },
  declining:         { text: '↓ Declining',       color: '#ef4444' },
  insufficient_data: { text: '? Limited history', color: '#6b7280' },
};

const REC_BADGE_CFG = {
  strong_buy:         { label: 'Strong Buy', cls: 'rp-strong-buy'         },
  buy:                { label: 'Buy',        cls: 'rp-buy'                },
  neutral:            { label: 'Neutral',    cls: 'rp-neutral'            },
  avoid_overvalued:   { label: 'Overvalued', cls: 'rp-avoid-overvalued'   },
  avoid_no_dividends: { label: 'No Divs',    cls: 'rp-avoid-no-dividends' },
  avoid:              { label: 'Avoid',      cls: 'rp-avoid'              },
  insufficient_data:  { label: 'No Data',    cls: 'rp-gray'               },
};

const SECTOR_ORDER = [
  'Water',
  'Food & Beverages',
  'Automobiles & Luxury',
  'Infrastructure & Highways',
  'Banks',
  'Construction',
  'Consumer Staples',
  'Retail & Distribution',
  'Utilities & Electric',
  'Oil & Gas',
  'Pharmaceuticals',
  'Biotech & Healthtech',
  'Insurance',
  'Holdings & Conglomerates',
  'Industrials',
  'Real Estate',
  'Chemicals',
  'Technology',
  'Telecommunications',
  'Media & Entertainment',
  'Other',
];


// ===== Settings =====

function getMinYield() {
  return parseFloat(localStorage.getItem('dlMinYield') || '4');
}

function getMaxPer() {
  return parseFloat(localStorage.getItem('dlMaxPer') || '15');
}

function getCurrencySymbol() {
  return localStorage.getItem('dlCurrency') || '€';
}

function getWithholdingTax() {
  return parseFloat(localStorage.getItem('dlWithholdingTax') || '19');
}

function onWithholdingTaxInput(val) {
  const v = Math.max(0, Math.min(50, parseInt(val, 10) || 0));
  localStorage.setItem('dlWithholdingTax', String(v));
  _renderDividendsFromCache();
  if (currentView === 'dividends') _renderDividendsTabContent();
}

function initSettings() {
  const theme = localStorage.getItem('dlTheme') || 'dark';
  applyTheme(theme, false);

  const currency = getCurrencySymbol();
  updateCurrencyBtns(currency);

  const taxInput = document.getElementById('withholding-tax-input');
  if (taxInput) taxInput.value = getWithholdingTax();

  const minYield = getMinYield();
  const maxPer = getMaxPer();
  const yieldSlider = document.getElementById('yield-slider');
  const perSlider   = document.getElementById('per-slider');
  if (yieldSlider) {
    yieldSlider.value = minYield;
    document.getElementById('yield-display').textContent = minYield.toFixed(1) + '%';
  }
  if (perSlider) {
    perSlider.value = maxPer;
    document.getElementById('per-display').textContent = maxPer + 'x';
  }
}

function toggleSettings() {
  const panel = document.getElementById('settings-panel');
  const btn   = document.getElementById('settings-btn');
  if (!panel) return;
  const isNowHidden = panel.classList.toggle('hidden');
  btn?.classList.toggle('active', !isNowHidden);
}

function closeSettings() {
  document.getElementById('settings-panel')?.classList.add('hidden');
  document.getElementById('settings-btn')?.classList.remove('active');
}

function applyTheme(theme, save = true) {
  document.body.classList.toggle('light-theme', theme === 'light');
  document.getElementById('theme-dark-btn')?.classList.toggle('active', theme === 'dark');
  document.getElementById('theme-light-btn')?.classList.toggle('active', theme === 'light');
  if (save) localStorage.setItem('dlTheme', theme);
}

function setTheme(theme) {
  applyTheme(theme);
}

function updateCurrencyBtns(sym) {
  document.getElementById('currency-eur-btn')?.classList.toggle('active', sym === '€');
  document.getElementById('currency-usd-btn')?.classList.toggle('active', sym === '$');
  document.getElementById('currency-gbp-btn')?.classList.toggle('active', sym === '£');
}

function setCurrency(sym) {
  localStorage.setItem('dlCurrency', sym);
  updateCurrencyBtns(sym);
  if (currentView === 'portfolio') renderPortfolio();
  if (currentView === 'dividends') _renderDividendsTabContent();
}

function onYieldSlider(val) {
  const v = parseFloat(val);
  document.getElementById('yield-display').textContent = v.toFixed(1) + '%';
  localStorage.setItem('dlMinYield', String(v));
}

function onPerSlider(val) {
  const v = parseFloat(val);
  document.getElementById('per-display').textContent = v + 'x';
  localStorage.setItem('dlMaxPer', String(v));
}

function resetThresholds() {
  const yieldSlider = document.getElementById('yield-slider');
  const perSlider   = document.getElementById('per-slider');
  if (yieldSlider) { yieldSlider.value = 4; document.getElementById('yield-display').textContent = '4.0%'; }
  if (perSlider)   { perSlider.value   = 15; document.getElementById('per-display').textContent  = '15x'; }
  localStorage.setItem('dlMinYield', '4');
  localStorage.setItem('dlMaxPer',   '15');
  if (currentTicker) analyzeStock(currentTicker);
}


// ===== Navigation =====

function switchView(view) {
  currentView = view;

  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.view === view);
  });
  document.querySelectorAll('.mobile-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.view === view);
  });
  document.querySelectorAll('.view').forEach(v => {
    v.classList.toggle('active', v.id === 'view-' + view);
  });

  updateNavSearch();

  if (view === 'watchlist') {
    renderWatchlistTable();
    renderWlTimestamp();
  }
  if (view === 'portfolio') renderPortfolio();
  if (view === 'dividends') renderDividendsView();
}

function updateNavSearch() {
  const area = document.getElementById('nav-search-area');
  if (!area) return;
  const show = currentView === 'analyze' && document.body.classList.contains('has-results');
  area.classList.toggle('visible', show);
}


// ===== App state (Analyze sub-states) =====

function enterResultsState() {
  document.body.classList.add('has-results');
  switchView('analyze');
  const navInput  = document.getElementById('nav-search-input');
  const homeInput = document.getElementById('search-input');
  if (navInput && homeInput) navInput.value = homeInput.value;
  updateNavSearch();
}

function goHome() {
  document.body.classList.remove('has-results');
  hideSugg();
  hideNavSugg();
  switchView('analyze');
}


// ===== Badge =====

function updateWlBadge() {
  const count = getWatchlist().length;
  const badge = document.getElementById('wl-badge');
  if (badge) badge.textContent = count > 0 ? String(count) : '';
}


// ===== Sector mapping =====

function mapSector(sector, industry, ticker) {
  const sec = (sector  || '').toLowerCase();
  const ind = (industry || '').toLowerCase();

  if ((ticker || '').toUpperCase() === 'RACE') return 'Automobiles & Luxury';

  if (sec.includes('utilities') && ind.includes('water')) return 'Water';
  if (/food|beverage|brewery|distillery|agricultural/.test(ind)) return 'Food & Beverages';
  if (/auto|vehicle|motor|luxury/.test(ind)) return 'Automobiles & Luxury';
  if (/airport|highway|port|railroad|infrastructure|engineering & construction/.test(ind)) return 'Infrastructure & Highways';
  if (sec.includes('industrials') && ind.includes('construction')) return 'Infrastructure & Highways';
  if (/bank|savings|mortgage|credit/.test(ind)) return 'Banks';
  if (ind.includes('construction')) return 'Construction';
  if (sec.includes('consumer defensive') && !/food|beverage/.test(ind)) return 'Consumer Staples';
  if (/household|personal|hygiene|cleaning|cosmetic/.test(ind)) return 'Consumer Staples';
  if (/retail|distribution|department store|apparel|specialty retail|discount/.test(ind)) return 'Retail & Distribution';
  if (sec.includes('utilities') && !ind.includes('water')) return 'Utilities & Electric';
  if (/electric|power|renewable|nuclear/.test(ind)) return 'Utilities & Electric';
  if (sec.includes('energy')) return 'Oil & Gas';
  if (/oil|gas|petroleum|refin|pipeline/.test(ind)) return 'Oil & Gas';
  if (/drug|pharmaceutical|generic|specialty chemical/.test(ind) && !/biotech|medical device/.test(ind)) return 'Pharmaceuticals';
  if (/biotech|medical device|health information|diagnostics|genomics|life sciences/.test(ind)) return 'Biotech & Healthtech';
  if (sec.includes('healthcare') && !/pharmaceutical|drug/.test(ind)) return 'Biotech & Healthtech';
  if (/insurance|reinsurance|surety/.test(ind)) return 'Insurance';
  if (/conglomerate|holding|asset management|diversified/.test(ind)) return 'Holdings & Conglomerates';
  if (sec.includes('industrials') || /machinery|aerospace|defense|electrical equipment|industrial/.test(ind)) return 'Industrials';
  if (sec.includes('real estate') || /reit|property/.test(ind)) return 'Real Estate';
  if (/chemical|specialty chemical|materials/.test(ind)) return 'Chemicals';
  if (sec.includes('technology') || /software|semiconductor|hardware|internet|cloud|cyber/.test(ind)) return 'Technology';
  if (sec.includes('communication services') && /telecom|wireless|broadband|cable|internet provider/.test(ind)) return 'Telecommunications';
  if (sec.includes('communication services') && /media|entertainment|broadcasting|publishing|music|gaming|film|television|sports/.test(ind)) return 'Media & Entertainment';

  return 'Other';
}


// ===== Watchlist storage =====

function getWatchlist() {
  try { return JSON.parse(localStorage.getItem('wl') || '[]'); }
  catch { return []; }
}

function saveWatchlist(wl) {
  localStorage.setItem('wl', JSON.stringify(wl));
}

function isInWatchlist(symbol) {
  return getWatchlist().some(i => i.symbol === symbol);
}

function addToWatchlist(symbol, name, sector, industry, recommendation, divYield, per, dividendTrend) {
  const wl  = getWatchlist();
  const idx = wl.findIndex(i => i.symbol === symbol);
  const entry = {
    symbol,
    name,
    sector: sector || '',
    industry: industry || '',
    recommendation: recommendation || '',
    divYield: divYield ?? null,
    per: per ?? null,
    dividendTrend: dividendTrend ?? null,
    notes: idx !== -1 ? (wl[idx].notes || '') : '',
  };
  if (idx === -1) wl.push(entry);
  else wl[idx] = entry;
  saveWatchlist(wl);
  if (currentView === 'watchlist') renderWatchlistTable();
  syncWlBtn();
  updateWlBadge();
}

function removeFromWatchlist(symbol) {
  saveWatchlist(getWatchlist().filter(i => i.symbol !== symbol));
  if (currentView === 'watchlist') renderWatchlistTable();
  syncWlBtn();
  updateWlBadge();
}

function toggleWatchlist() {
  if (!currentTicker) return;
  isInWatchlist(currentTicker)
    ? removeFromWatchlist(currentTicker)
    : addToWatchlist(
        currentTicker, currentName || currentTicker,
        currentSector, currentIndustry, currentRec,
        currentDivYield, currentPer, currentDividendTrend,
      );
}

function syncWlBtn() {
  const btn = document.getElementById('wl-btn');
  if (!btn || !currentTicker) return;
  const inList = isInWatchlist(currentTicker);
  btn.className   = 'wl-star-btn' + (inList ? ' in-list' : '');
  btn.textContent = inList ? '★ In Watchlist' : '☆ Watchlist';
  btn.title       = inList ? 'Remove from watchlist' : 'Add to watchlist';
}

// Legacy shim called by refresh flow
function renderWatchlist() {
  if (currentView === 'watchlist') renderWatchlistTable();
  updateWlBadge();
}


// ===== Watchlist Table =====

let wlSort = { col: null, dir: 1 };

function populateWlSectorFilter() {
  const select = document.getElementById('wl-filter-sector');
  if (!select || select.options.length > 1) return;
  for (const s of SECTOR_ORDER) {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s;
    select.appendChild(opt);
  }
}

function renderWatchlistTable() {
  const container = document.getElementById('watchlist-table-container');
  if (!container) return;

  const wl = getWatchlist();

  if (!wl.length) {
    container.innerHTML = '<p class="empty-state-view">Search for a company and add it to your watchlist to track it here.</p>';
    return;
  }

  const textFilter   = (document.getElementById('wl-filter-text')?.value || '').toLowerCase();
  const sectorFilter = document.getElementById('wl-filter-sector')?.value || '';
  const recFilter    = document.getElementById('wl-filter-rec')?.value || '';

  let filtered = wl.filter(item => {
    if (textFilter && !item.symbol.toLowerCase().includes(textFilter) && !(item.name || '').toLowerCase().includes(textFilter)) return false;
    if (sectorFilter && mapSector(item.sector, item.industry || '', item.symbol) !== sectorFilter) return false;
    if (recFilter && item.recommendation !== recFilter) return false;
    return true;
  });

  if (wlSort.col) {
    filtered.sort((a, b) => {
      let av, bv;
      if (wlSort.col === 'ticker')  { av = a.symbol;         bv = b.symbol;         }
      if (wlSort.col === 'rec')    { av = RECOMMENDATION_ORDER[a.recommendation] ?? 99; bv = RECOMMENDATION_ORDER[b.recommendation] ?? 99; }
      if (wlSort.col === 'sector') { av = mapSector(a.sector, a.industry || '', a.symbol); bv = mapSector(b.sector, b.industry || '', b.symbol); }
      if (wlSort.col === 'yield')  { av = a.divYield ?? -1; bv = b.divYield ?? -1; }
      if (wlSort.col === 'per')    { av = a.per ?? 99999;   bv = b.per ?? 99999;   }
      if (av < bv) return -wlSort.dir;
      if (av > bv) return  wlSort.dir;
      return 0;
    });
  }

  if (!filtered.length) {
    container.innerHTML = '<p class="empty-state-view">No results for this filter.</p>';
    return;
  }

  const si = col => {
    if (wlSort.col !== col) return '<span class="sort-indicator">↕</span>';
    return `<span class="sort-indicator active">${wlSort.dir === 1 ? '↑' : '↓'}</span>`;
  };

  const rows = filtered.map(item => {
    const rb     = REC_BADGE_CFG[item.recommendation];
    const sector = mapSector(item.sector, item.industry || '', item.symbol);
    const wt     = item.dividendTrend ? WL_TREND_CFG[item.dividendTrend] : null;
    return (
      `<tr class="table-row-clickable" onclick="analyzeStock('${esc(item.symbol)}')">` +
      `<td><span class="wl-ticker">${esc(item.symbol)}</span></td>` +
      `<td class="td-company">${esc(item.name || '')}</td>` +
      `<td>${esc(sector)}</td>` +
      `<td>${rb ? `<span class="rec-pill ${rb.cls}">${rb.label}</span>` : '—'}</td>` +
      `<td>${item.divYield != null ? item.divYield.toFixed(2) + '%' : '—'}</td>` +
      `<td>${item.per != null ? item.per.toFixed(1) + 'x' : '—'}</td>` +
      `<td>${wt ? `<span class="wl-trend-plain" style="color:${wt.color}">${wt.icon} ${wt.label}</span>` : '—'}</td>` +
      `<td data-note-sym="${esc(item.symbol)}">${notePreviewHTML(item.notes || '', item.symbol)}</td>` +
      `<td><div class="table-actions">` +
      `<button class="table-btn-analyze" onclick="event.stopPropagation();analyzeStock('${esc(item.symbol)}')">Analyze</button>` +
      `<button class="table-btn-remove" title="Remove" onclick="event.stopPropagation();removeFromWatchlist('${esc(item.symbol)}')">×</button>` +
      `</div></td>` +
      `</tr>`
    );
  }).join('');

  container.innerHTML =
    `<div class="table-wrap"><table class="data-table">` +
    `<thead><tr>` +
    `<th class="sortable" onclick="setWlSort('ticker')">Ticker ${si('ticker')}</th>` +
    `<th>Company</th>` +
    `<th class="sortable" onclick="setWlSort('sector')">Sector ${si('sector')}</th>` +
    `<th class="sortable" onclick="setWlSort('rec')" style="min-width:140px">Recommendation ${si('rec')}</th>` +
    `<th class="sortable" onclick="setWlSort('yield')">Div. Yield ${si('yield')}</th>` +
    `<th class="sortable" onclick="setWlSort('per')">PER ${si('per')}</th>` +
    `<th style="min-width:100px">Dividend Trend</th>` +
    `<th style="min-width:160px">Notes</th>` +
    `<th>Actions</th>` +
    `</tr></thead>` +
    `<tbody>${rows}</tbody>` +
    `</table></div>`;

  container.querySelectorAll('td[data-note-sym]').forEach(td => {
    td.addEventListener('click', e => e.stopPropagation());
  });
}

function setWlSort(col) {
  if (wlSort.col === col) wlSort.dir *= -1;
  else { wlSort.col = col; wlSort.dir = 1; }
  renderWatchlistTable();
}


// ===== Watchlist Notes =====

function notePreviewHTML(note, symbol) {
  if (!note) {
    return `<button class="note-btn-add" onclick="event.stopPropagation();openNoteEditor('${esc(symbol)}')">+</button>`;
  }
  const preview = note.length > 40 ? note.slice(0, 40) + '…' : note;
  return `<span class="note-preview" onclick="event.stopPropagation();openNoteEditor('${esc(symbol)}')">${esc(preview)}</span>` +
    `<span class="note-edit-icon" onclick="event.stopPropagation();openNoteEditor('${esc(symbol)}')">&#9999;</span>`;
}

function openNoteEditor(symbol) {
  const td = document.querySelector(`td[data-note-sym="${CSS.escape(symbol)}"]`);
  if (!td) return;
  const wl = getWatchlist();
  const item = wl.find(i => i.symbol === symbol);
  const currentNote = item?.notes || '';
  td.innerHTML =
    `<div class="note-editor-wrap">` +
    `<textarea class="note-textarea" id="note-ta-${esc(symbol)}" ` +
    `onclick="event.stopPropagation()" ` +
    `onkeydown="handleNoteKey(event,'${esc(symbol)}')">${esc(currentNote)}</textarea>` +
    `<div class="note-editor-actions">` +
    `<button class="note-cancel-btn" onclick="event.stopPropagation();cancelNoteEdit('${esc(symbol)}')">Cancel</button>` +
    `<button class="note-save-btn" onclick="event.stopPropagation();saveNote('${esc(symbol)}')">Save</button>` +
    `</div></div>`;
  const ta = document.getElementById(`note-ta-${symbol}`);
  if (ta) ta.focus();
}

function handleNoteKey(e, symbol) {
  if (e.key === 'Escape') { e.preventDefault(); cancelNoteEdit(symbol); }
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); saveNote(symbol); }
}

function saveNote(symbol) {
  const ta = document.getElementById(`note-ta-${symbol}`);
  if (!ta) return;
  const note = ta.value.trim();
  const wl = getWatchlist();
  const idx = wl.findIndex(i => i.symbol === symbol);
  if (idx !== -1) { wl[idx].notes = note; saveWatchlist(wl); }
  restoreNoteCell(symbol, note);
}

function cancelNoteEdit(symbol) {
  const wl = getWatchlist();
  const item = wl.find(i => i.symbol === symbol);
  restoreNoteCell(symbol, item?.notes || '');
}

function restoreNoteCell(symbol, note) {
  const td = document.querySelector(`td[data-note-sym="${CSS.escape(symbol)}"]`);
  if (!td) return;
  td.innerHTML = notePreviewHTML(note, symbol);
}

function editNoteFromAnalyze(symbol) {
  switchView('watchlist');
  requestAnimationFrame(() => {
    const td = document.querySelector(`td[data-note-sym="${CSS.escape(symbol)}"]`);
    if (td) td.scrollIntoView({ behavior: 'smooth', block: 'center' });
    openNoteEditor(symbol);
  });
}


// ===== Watchlist Refresh =====

function getWlTimestamp() {
  return localStorage.getItem('wl_updated') || null;
}

function saveWlTimestamp(ts) {
  localStorage.setItem('wl_updated', ts);
}

function renderWlTimestamp() {
  const el = document.getElementById('wl-timestamp-header');
  if (!el) return;
  const ts = getWlTimestamp();
  el.textContent = ts ? 'Last updated: ' + ts : '';
}

async function asyncPool(limit, items, fn) {
  const results  = [];
  const executing = [];
  for (const item of items) {
    const p = Promise.resolve().then(() => fn(item));
    results.push(p);
    if (limit <= items.length) {
      const e = p.then(() => executing.splice(executing.indexOf(e), 1));
      executing.push(e);
      if (executing.length >= limit) await Promise.race(executing);
    }
  }
  return Promise.all(results);
}

async function refreshWatchlist() {
  const btn = document.getElementById('wl-refresh-btn');
  if (btn) { btn.disabled = true; }

  const wl       = getWatchlist();
  const toRefresh = wl.filter(i => i.recommendation !== 'avoid_no_dividends');

  if (!toRefresh.length) {
    if (btn) { btn.disabled = false; btn.textContent = '↻ Refresh'; }
    return;
  }

  let completed = 0;
  const total   = wl.length;

  const updateBtn = () => {
    if (btn) btn.textContent = `↻ Refreshing... (${completed}/${total})`;
  };
  updateBtn();

  const refreshOne = async (item) => {
    try {
      const params = new URLSearchParams({ minYield: getMinYield(), maxPer: getMaxPer() });
      const res    = await fetch(`/api/analyze/${encodeURIComponent(item.symbol)}?${params}`);
      if (!res.ok) throw new Error('bad response');
      const data = await res.json();

      const watchlist = getWatchlist();
      const index = watchlist.findIndex(w => w.symbol === item.symbol);
      if (index !== -1) {
        watchlist[index] = {
          ...watchlist[index],
          recommendation: data.scores.overallRecommendation,
          divYield:       data.metrics.dividendYield,
          per:            data.metrics.per,
          dividendTrend:  data.dividendTrend,
          sector:         data.sector   || watchlist[index].sector,
          industry:       data.industry || watchlist[index].industry,
        };
        saveWatchlist(watchlist);
        if (currentView === 'watchlist') renderWatchlistTable();
      }
    } catch (_) {
      // keep existing data for this item
    } finally {
      completed++;
      updateBtn();
    }
  };

  await asyncPool(10, toRefresh, refreshOne);

  const d   = new Date();
  const now = d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
    + ', ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  saveWlTimestamp(now);
  renderWlTimestamp();
  if (btn) { btn.disabled = false; btn.textContent = '↻ Refresh'; }
}


// ===== Search =====

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

async function searchStocks(q) {
  if (!q.trim()) { hideSugg(); return; }
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    renderSugg(await res.json());
  } catch { hideSugg(); }
}

function renderSugg(results) {
  const el = document.getElementById('suggestions');
  if (!results.length) { hideSugg(); return; }
  el.innerHTML = results.map(r =>
    `<div class="suggestion-item" onclick="selectSugg('${esc(r.symbol)}')">` +
    `<span class="sug-ticker">${esc(r.symbol)}</span>` +
    `<span class="sug-name">${esc(r.name || '')}</span>` +
    `<span class="sug-exchange">${esc(r.exchangeLabel || r.exchange || '')}</span>` +
    `</div>`
  ).join('');
  el.classList.remove('hidden');
}

function hideSugg() {
  document.getElementById('suggestions').classList.add('hidden');
}

function selectSugg(symbol) {
  document.getElementById('search-input').value = symbol;
  hideSugg();
  analyzeStock(symbol);
}

// Nav search
async function searchNavStocks(q) {
  if (!q.trim()) { hideNavSugg(); return; }
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    renderNavSugg(await res.json());
  } catch { hideNavSugg(); }
}

function renderNavSugg(results) {
  const el = document.getElementById('nav-suggestions');
  if (!results.length) { hideNavSugg(); return; }
  el.innerHTML = results.map(r =>
    `<div class="suggestion-item" onclick="selectNavSugg('${esc(r.symbol)}')">` +
    `<span class="sug-ticker">${esc(r.symbol)}</span>` +
    `<span class="sug-name">${esc(r.name || '')}</span>` +
    `<span class="sug-exchange">${esc(r.exchangeLabel || r.exchange || '')}</span>` +
    `</div>`
  ).join('');
  el.classList.remove('hidden');
}

function hideNavSugg() {
  document.getElementById('nav-suggestions').classList.add('hidden');
}

function selectNavSugg(symbol) {
  document.getElementById('nav-search-input').value = symbol;
  hideNavSugg();
  analyzeStock(symbol);
}

// Modal search
let modalSelectedStock = null;

async function searchModalStocks(q) {
  if (!q.trim()) { hideModalSugg(); return; }
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    renderModalSugg(await res.json());
  } catch { hideModalSugg(); }
}

function renderModalSugg(results) {
  const el = document.getElementById('modal-suggestions');
  if (!results.length) { hideModalSugg(); return; }
  el.innerHTML = results.map(r =>
    `<div class="suggestion-item" onclick="selectModalSugg('${esc(r.symbol)}','${esc(r.name || '')}','${esc(r.sector || '')}','${esc(r.industry || '')}')">` +
    `<span class="sug-ticker">${esc(r.symbol)}</span>` +
    `<span class="sug-name">${esc(r.name || '')}</span>` +
    `<span class="sug-exchange">${esc(r.exchangeLabel || r.exchange || '')}</span>` +
    `</div>`
  ).join('');
  el.classList.remove('hidden');
}

function hideModalSugg() {
  const el = document.getElementById('modal-suggestions');
  if (el) el.classList.add('hidden');
}

function selectModalSugg(symbol, name, sector, industry) {
  modalSelectedStock = { symbol, companyName: name, sector, industry };
  document.getElementById('modal-search-input').value = `${symbol} — ${name}`;
  hideModalSugg();
}


// ===== Analysis =====

async function analyzeStock(ticker) {
  currentTicker = ticker.toUpperCase();
  enterResultsState();
  showLoading();
  try {
    const params = new URLSearchParams({ minYield: getMinYield(), maxPer: getMaxPer() });
    const res = await fetch(`/api/analyze/${encodeURIComponent(ticker)}?${params}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showError(err.detail || `Could not load data for "${ticker}".`);
      return;
    }
    const data = await res.json();
    currentName          = data.companyName;
    currentSector        = data.sector;
    currentIndustry      = data.industry;
    currentRec           = data.scores.overallRecommendation;
    currentDivYield      = data.metrics.dividendYield;
    currentPer           = data.metrics.per;
    currentDividendTrend = data.dividendTrend;
    renderResults(data);
    fetchAndRenderHistoricalYield(currentTicker);
  } catch {
    showError('Network error — please check your connection and try again.');
  }
}

async function fetchAndRenderHistoricalYield(ticker) {
  try {
    const res = await fetch(`/api/historical-yield?symbol=${encodeURIComponent(ticker)}`);
    if (!res.ok) return;
    const data = await res.json();
    if (currentTicker !== ticker) return; // stale response
    const el = document.getElementById('historical-yield-context');
    if (!el || data.context === 'unavailable') return;
    const avg = data.avgYield3y != null ? data.avgYield3y.toFixed(1) : '—';
    const map = {
      above_average: `<span class="hist-yield above">↑ Above 3yr avg (${avg}%)</span>`,
      below_average: `<span class="hist-yield below">↓ Below 3yr avg (${avg}%)</span>`,
      at_average:    `<span class="hist-yield at">≈ In line with 3yr avg (${avg}%)</span>`,
    };
    el.innerHTML = map[data.context] || '';
  } catch (_) {}
}

function showLoading() {
  document.getElementById('results-content').innerHTML =
    `<div class="loading"><div class="spinner"></div><div>Fetching data…</div></div>`;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showError(msg) {
  document.getElementById('results-content').innerHTML =
    `<div class="error-box">⚠ ${esc(msg)}</div>`;
}


// ===== Render Results =====

function buildRecSummary(scores) {
  const rec = scores.overallRecommendation;
  if (rec === 'avoid_no_dividends') return 'No dividends — not suited for this strategy';
  if (rec === 'insufficient_data')  return 'Insufficient data to evaluate';

  const parts = [];
  const perMap   = { buy: 'PER ✓', neutral: 'PER fair', expensive: 'PER expensive' };
  const yieldMap = { buy: 'Yield ✓', neutral: 'Yield moderate', low: 'Yield low', none: 'No yield' };
  const debtMap  = { safe: 'Debt safe', moderate: 'Debt moderate', high: 'Debt high' };
  if (perMap[scores.perScore])     parts.push(perMap[scores.perScore]);
  if (yieldMap[scores.yieldScore]) parts.push(yieldMap[scores.yieldScore]);
  if (debtMap[scores.debtScore])   parts.push(debtMap[scores.debtScore]);
  return parts.join('  ·  ') || '—';
}

function renderTrendBadge(trend) {
  const cfg = TREND_CFG[trend] || TREND_CFG.insufficient_data;
  return `<span class="score-badge trend-badge ${cfg.cls}">${cfg.icon} ${cfg.label}</span>`;
}

function renderResults(data) {
  const {
    companyName, ticker, currentPrice, currency, sector,
    metrics, dividendInfo, priceHistory, scores, dividendTrend,
  } = data;

  const priceStr  = currentPrice != null
    ? new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(currentPrice)
    : '—';
  const showTrend = dividendInfo.paysDividends && dividendTrend;

  const divTooltip = 'Dividend trend shows whether the company has been growing, maintaining or cutting its dividend over the last 3 years. The historical comparison shows if the current yield is high or low relative to its own past.';

  const metricsHTML = METRICS.map(({ key, label, scoreKey, fmt, tooltip }) => {
    const val  = metrics[key];
    const sv   = scores[scoreKey];
    const cfg  = (SCORE_CFG[scoreKey] || {})[sv] || { label: sv, cls: 's-gray' };
    const isNA = sv === 'not_applicable';
    const displayVal = isNA ? 'N/A' : (val != null ? fmt(val) : '—');
    const valCls     = (isNA || val == null) ? ' na' : '';

    if (key === 'dividendYield') {
      let trendHTML = '';
      if (showTrend) {
        const dt = DIVIDEND_MINI_TREND[dividendTrend] || DIVIDEND_MINI_TREND.insufficient_data;
        trendHTML = `<div class="div-trend-plain" style="color:${dt.color}">${dt.text}</div>`;
      }
      return (
        `<div class="yield-slot">` +
        `<div class="mini-card">` +
        `<span class="info-icon" data-tooltip="${esc(tooltip)}">ⓘ</span>` +
        `<div class="m-label">DIV. YIELD</div>` +
        `<div class="m-value${valCls}">${displayVal}</div>` +
        `<span class="score-badge ${cfg.cls}">${cfg.label}</span>` +
        `</div>` +
        `<div class="mini-card">` +
        `<span class="info-icon" data-tooltip="${esc(divTooltip)}">ⓘ</span>` +
        `<div class="m-label">DIVIDEND</div>` +
        trendHTML +
        `<div id="historical-yield-context"></div>` +
        `</div>` +
        `</div>`
      );
    }

    return (
      `<div class="metric-card">` +
      `<span class="info-icon" data-tooltip="${esc(tooltip)}">ⓘ</span>` +
      `<div class="m-label">${label}</div>` +
      `<div class="m-value${valCls}">${displayVal}</div>` +
      `<span class="score-badge ${cfg.cls}">${cfg.label}</span>` +
      `</div>`
    );
  }).join('');

  const rec          = REC_CFG[scores.overallRecommendation] || REC_CFG.insufficient_data;
  const recSummary   = buildRecSummary(scores);
  const inList       = isInWatchlist(ticker);
  const sectorNote   = scores.sectorNote;
  const sectorBanner = sectorNote
    ? `<div class="sector-note-banner">ℹ️ Sector note: ${esc(sectorNote)}</div>`
    : '';
  const wlItem   = getWatchlist().find(i => i.symbol === ticker);
  const noteHTML = (inList && wlItem?.notes)
    ? `<div class="analyze-note-block">` +
      `<span class="analyze-note-label">Your note:</span>` +
      `<span class="analyze-note-text">${esc(wlItem.notes)}</span>` +
      `<button class="analyze-note-edit" onclick="editNoteFromAnalyze('${esc(ticker)}')" title="Edit note">&#9999;</button>` +
      `</div>`
    : '';

  document.getElementById('results-content').innerHTML =
    `<div class="results-fade">` +

    `<div class="co-header">` +
    `<div>` +
    `<div class="co-name-row">` +
    `<h2 class="co-name">${esc(companyName)}</h2>` +
    `<button id="wl-btn" class="wl-star-btn ${inList ? 'in-list' : ''}" onclick="toggleWatchlist()" title="${inList ? 'Remove from watchlist' : 'Add to watchlist'}">` +
    (inList ? '★ In Watchlist' : '☆ Watchlist') +
    `</button>` +
    `</div>` +
    `<div class="co-meta">` +
    `<span class="ticker-badge">${esc(ticker)}</span>` +
    (sector ? `<span class="sector-tag">${esc(sector)}</span>` : '') +
    `</div></div>` +
    `<div class="price-block">` +
    `<div class="co-price">${esc(currency)} ${priceStr}</div>` +
    `<div class="div-badge ${dividendInfo.paysDividends ? 'pays' : 'no-div'}">` +
    (dividendInfo.paysDividends ? '✓ Pays dividends' : '✗ No dividends') +
    `</div></div></div>` +

    `<div class="rec-block ${rec.cls}">` +
    `<span class="rec-icon">${rec.icon}</span>` +
    `<div class="rec-main"><div class="rec-text">${rec.text}</div></div>` +
    `<div class="rec-summary">${esc(recSummary)}</div>` +
    `</div>` +

    sectorBanner +
    noteHTML +

    `<div class="metrics-grid">${metricsHTML}</div>` +

    `<div class="chart-card">` +
    `<div class="chart-title">12-Month Price History</div>` +
    `<canvas id="price-chart"></canvas>` +
    `<p class="chart-note">Price chart does not reflect dividends received. Total real return is significantly higher for dividend-paying companies.</p>` +
    `</div>` +

    `</div>`;

  renderChart(priceHistory);
  attachTooltipListeners();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}


// ===== Chart =====

function renderChart(history) {
  if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
  const canvas = document.getElementById('price-chart');
  if (!canvas || !history.length) return;

  const ctx  = canvas.getContext('2d');
  const grad = ctx.createLinearGradient(0, 0, 0, 210);
  grad.addColorStop(0, 'rgba(34,197,94,0.22)');
  grad.addColorStop(1, 'rgba(34,197,94,0)');

  const isLight    = document.body.classList.contains('light-theme');
  const labelColor = isLight ? '#0f172a' : '#475569';
  const gridColor  = isLight ? '#e2e8f0' : 'rgba(255,255,255,0.04)';
  const borderColor = isLight ? '#e2e8f0' : 'rgba(255,255,255,0.06)';

  chartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: history.map(p => p.date),
      datasets: [{
        data: history.map(p => p.close),
        borderColor: '#22c55e',
        borderWidth: 1.8,
        backgroundColor: grad,
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: '#22c55e',
        pointHoverBorderColor: '#0f1117',
        pointHoverBorderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1d27',
          borderColor: 'rgba(255,255,255,0.1)',
          borderWidth: 1,
          titleColor: '#64748b',
          bodyColor: '#e2e8f0',
          titleFont: { size: 11 },
          bodyFont: { size: 13, weight: '600' },
          padding: 10,
          callbacks: { label: ctx => ' ' + ctx.parsed.y.toFixed(2) },
        },
      },
      scales: {
        x: {
          grid:   { color: isLight ? '#f1f5f9' : 'rgba(255,255,255,0.04)' },
          border: { color: borderColor },
          ticks:  { color: labelColor, font: { size: 11 }, maxTicksLimit: 7 },
        },
        y: {
          grid:   { color: gridColor },
          border: { color: borderColor },
          ticks:  { color: labelColor, font: { size: 11 }, callback: v => v.toFixed(0) },
          position: 'right',
        },
      },
    },
  });
}


// ===== Portfolio Storage =====

function getPortfolio() {
  try { return JSON.parse(localStorage.getItem('portfolio') || '[]'); }
  catch { return []; }
}

function savePortfolio(portfolio) {
  localStorage.setItem('portfolio', JSON.stringify(portfolio));
}


// ===== Portfolio Sector Migration =====

const _RAW_YF_SECTORS = new Set([
  'Technology', 'Financial Services', 'Consumer Cyclical', 'Consumer Defensive',
  'Healthcare', 'Industrials', 'Basic Materials', 'Communication Services',
  'Energy', 'Real Estate', 'Utilities', 'Other',
]);

function migratePortfolioSectors() {
  const portfolio = getPortfolio();
  if (!portfolio.length) return;
  let changed = false;
  for (const p of portfolio) {
    if (!p.sector || _RAW_YF_SECTORS.has(p.sector)) {
      const corrected = mapSector(p.sector || '', p.industry || '', p.symbol);
      if (corrected !== p.sector) {
        p.sector = corrected;
        changed = true;
      }
    }
  }
  if (changed) savePortfolio(portfolio);
}


const formatDate = (dateStr) => {
  const date = new Date(dateStr + 'T12:00:00');
  return date.toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  });
};

// ===== Portfolio Render =====

let purchaseDateSortDir = -1; // -1 desc, 1 asc
let portfolioSearchQuery = '';
let portfolioSectorFilter = '';
let _dividendsCache    = null;
let _dividendsTabCache = null;
let divTabYearFilter   = 'all';
let divTabDateSortDir  = -1;
let divTabChartInst    = null;

function populatePfSectorFilter() {
  const select = document.getElementById('pf-filter-sector');
  if (!select) return;
  const portfolio = getPortfolio();
  const sectors = [...new Set(portfolio.map(p => p.sector).filter(Boolean))].sort();
  const current = select.value;
  select.innerHTML = '<option value="">All Sectors</option>' +
    sectors.map(s => `<option value="${esc(s)}"${s === current ? ' selected' : ''}>${esc(s)}</option>`).join('');
}

function onPortfolioSearch() {
  portfolioSearchQuery  = (document.getElementById('pf-filter-text')?.value || '').toLowerCase().trim();
  portfolioSectorFilter = document.getElementById('pf-filter-sector')?.value || '';
  const portfolio = getPortfolio();
  renderPortfolioCompanySummary(portfolio);
  renderPortfolioPurchasesTable(portfolio);
  _renderDividendsFromCache();
}

function _renderDividendsFromCache() {
  if (!_dividendsCache) return;
  const { results } = _dividendsCache;

  const sym    = getCurrencySymbol();
  const tax    = getWithholdingTax();
  const fmtAmt = v => sym + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const grandGross = Object.values(results).reduce((s, d) => s + (d.totalReceived || 0), 0);
  const grandNet   = grandGross * (1 - tax / 100);
  const cardEl = document.getElementById('dividend-total-card');
  if (cardEl) cardEl.textContent = fmtAmt(grandNet);
}

function renderPortfolio() {
  const portfolio = getPortfolio();
  renderPortfolioSummaryCards(portfolio);
  renderPortfolioSectorChart(portfolio);
  const searchWrap = document.getElementById('portfolio-filter-bar');
  if (searchWrap) searchWrap.classList.toggle('hidden', !portfolio.length);
  populatePfSectorFilter();
  renderPortfolioPurchasesTable(portfolio);
  renderPortfolioCompanySummary(portfolio);
  renderPortfolioDividendsReceived(portfolio);
}

function renderPortfolioSummaryCards(portfolio) {
  const container = document.getElementById('portfolio-summary-cards');
  if (!container) return;

  if (!portfolio.length) { container.innerHTML = ''; return; }

  const totalInvested  = portfolio.reduce((s, p) => s + p.amountEUR, 0);
  const companies      = new Set(portfolio.map(p => p.symbol)).size;
  const numPurchases   = portfolio.length;

  const companyTotals = {};
  for (const p of portfolio) {
    if (!companyTotals[p.symbol]) companyTotals[p.symbol] = { name: p.companyName, total: 0 };
    companyTotals[p.symbol].total += p.amountEUR;
  }
  const largest = Object.values(companyTotals).sort((a, b) => b.total - a.total)[0];

  const sym    = getCurrencySymbol();
  const fmtEur = v => sym + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const cards = [
    { label: 'Total Invested',              value: fmtEur(totalInvested),             id: null,                  accent: false },
    { label: 'Number of Companies',         value: String(companies),                 id: null,                  accent: false },
    { label: 'Number of Purchases',         value: String(numPurchases),              id: null,                  accent: false },
    { label: 'Largest Position',            value: largest ? largest.name : '—',     id: null,                  accent: false },
    { label: '💰 Total Dividends Received', value: '—',                              id: 'dividend-total-card', accent: true  },
  ];

  container.innerHTML = cards.map(c =>
    `<div class="summary-card${c.accent ? ' summary-card-accent' : ''}">` +
    `<div class="summary-card-label">${esc(c.label)}</div>` +
    `<div class="summary-card-value"${c.id ? ` id="${c.id}"` : ''}>${esc(c.value)}</div>` +
    `</div>`
  ).join('');
}

function renderPortfolioSectorChart(portfolio) {
  const card = document.getElementById('portfolio-sector-chart');
  if (!card) return;

  if (!portfolio.length) { card.style.display = 'none'; return; }
  card.style.display = 'block';

  const sectorTotals = {};
  for (const p of portfolio) {
    const sec = p.sector || 'Other';
    sectorTotals[sec] = (sectorTotals[sec] || 0) + p.amountEUR;
  }
  const total   = Object.values(sectorTotals).reduce((a, b) => a + b, 0);
  const sectors = Object.entries(sectorTotals).sort((a, b) => b[1] - a[1]);
  const labels  = sectors.map(([s]) => s);
  const values  = sectors.map(([, v]) => Math.round((v / total) * 1000) / 10);

  const canvas = document.getElementById('sector-chart');
  const chartHeight = Math.min(Math.max(sectors.length * 40, 80), 300);
  canvas.parentElement.style.height = chartHeight + 'px';

  if (portfolioChartInst) { portfolioChartInst.destroy(); portfolioChartInst = null; }

  const isLight    = document.body.classList.contains('light-theme');
  const labelColor = isLight ? '#0f172a' : '#9ca3af';
  const gridColor  = isLight ? '#e2e8f0' : '#1f2937';

  portfolioChartInst = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: '#22c55e', borderRadius: 4 }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ' ' + ctx.parsed.x.toFixed(1) + '%' } },
      },
      scales: {
        x: {
          max: 100,
          grid:  { color: isLight ? '#f1f5f9' : '#1f2937' },
          ticks: { color: labelColor, callback: v => v + '%' },
        },
        y: {
          grid:  { display: false },
          ticks: { color: labelColor, font: { size: 12 } },
        },
      },
    },
  });
}

function renderPortfolioPurchasesTable(portfolio) {
  const container = document.getElementById('portfolio-purchases-container');
  if (!container) return;

  if (!portfolio.length) {
    container.innerHTML = `<div class="empty-state-view">No purchases recorded yet. Click '＋ Add Purchase' to get started.</div>`;
    return;
  }

  let sorted = [...portfolio].sort((a, b) =>
    purchaseDateSortDir * (a.date < b.date ? 1 : a.date > b.date ? -1 : 0)
  );

  if (portfolioSearchQuery) {
    sorted = sorted.filter(p =>
      p.symbol.toLowerCase().includes(portfolioSearchQuery) ||
      (p.companyName || '').toLowerCase().includes(portfolioSearchQuery)
    );
  }
  if (portfolioSectorFilter) {
    sorted = sorted.filter(p => p.sector === portfolioSectorFilter);
  }

  const sortIcon = purchaseDateSortDir === -1 ? '↓' : '↑';
  const sym      = getCurrencySymbol();
  const fmtEur   = v => sym + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const headerHTML =
    `<div class="section-title-row">` +
    `<h3 class="section-title">Purchases</h3>` +
    `<button class="wl-refresh-btn" onclick="exportPurchasesCSV()">↓ Export Purchases</button>` +
    `</div>`;

  let bodyHTML;
  if (!sorted.length && (portfolioSearchQuery || portfolioSectorFilter)) {
    bodyHTML = `<p class="empty-state-view">No results for this filter.</p>`;
  } else {
    const rows = sorted.map(p =>
      `<tr>` +
      `<td>${esc(formatDate(p.date))}</td>` +
      `<td class="td-ticker-portfolio" onclick="analyzeStock('${esc(p.symbol)}')"><span class="wl-ticker">${esc(p.symbol)}<span class="ticker-goto-icon">↗</span></span></td>` +
      `<td class="td-company">${esc(p.companyName)}</td>` +
      `<td>${esc(p.sector)}</td>` +
      `<td>${fmtEur(p.amountEUR)}</td>` +
      `<td>${fmtEur(p.pricePerShare)}</td>` +
      `<td>${p.exactSharesProvided ? p.shares.toFixed(4) : `<span style="color:var(--text-muted)">~</span>${p.shares.toFixed(4)}`}</td>` +
      `<td><button class="table-btn-remove" title="Delete" onclick="event.stopPropagation();deletePurchase('${esc(p.id)}')">×</button></td>` +
      `</tr>`
    ).join('');

    bodyHTML =
      `<div class="table-wrap"><table class="data-table">` +
      `<thead><tr>` +
      `<th class="sortable" onclick="togglePurchaseDateSort()">Date <span class="sort-indicator active">${sortIcon}</span></th>` +
      `<th>Ticker</th><th>Company</th><th>Sector</th>` +
      `<th>Amount (${getCurrencySymbol()})</th><th>Price/Share</th><th>Shares</th><th>Actions</th>` +
      `</tr></thead>` +
      `<tbody>${rows}</tbody>` +
      `</table></div>`;
  }

  container.innerHTML = headerHTML + bodyHTML;
}

function togglePurchaseDateSort() {
  purchaseDateSortDir *= -1;
  renderPortfolioPurchasesTable(getPortfolio());
}

function deletePurchase(id) {
  if (!confirm('Delete this purchase?')) return;
  savePortfolio(getPortfolio().filter(p => p.id !== id));
  _dividendsTabCache = null;
  renderPortfolio();
}

function renderPortfolioCompanySummary(portfolio) {
  const container = document.getElementById('portfolio-company-container');
  if (!container) return;
  if (!portfolio.length) { container.innerHTML = ''; return; }

  const companies = {};
  for (const p of portfolio) {
    if (!companies[p.symbol]) {
      companies[p.symbol] = { symbol: p.symbol, companyName: p.companyName, sector: p.sector, totalAmount: 0, totalShares: 0, purchases: 0 };
    }
    companies[p.symbol].totalAmount += p.amountEUR;
    companies[p.symbol].totalShares += p.shares;
    companies[p.symbol].purchases   += 1;
  }

  let sorted = Object.values(companies).sort((a, b) => b.totalAmount - a.totalAmount);

  if (portfolioSearchQuery) {
    sorted = sorted.filter(c =>
      c.symbol.toLowerCase().includes(portfolioSearchQuery) ||
      (c.companyName || '').toLowerCase().includes(portfolioSearchQuery)
    );
  }
  if (portfolioSectorFilter) {
    sorted = sorted.filter(c => c.sector === portfolioSectorFilter);
  }

  const sym    = getCurrencySymbol();
  const fmtEur = v => sym + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const headerHTML =
    `<div class="section-title-row">` +
    `<h3 class="section-title">Summary by Company</h3>` +
    `<button class="wl-refresh-btn" onclick="exportSummaryCSV()">↓ Export Summary</button>` +
    `</div>`;

  if (!sorted.length) {
    container.innerHTML = headerHTML +
      `<p class="empty-state-view">No results for '${esc(portfolioSearchQuery)}'</p>`;
    return;
  }

  const rows = sorted.map(c => {
    const avg = c.totalAmount / c.totalShares;
    return (
      `<tr class="table-row-clickable" onclick="analyzeStock('${esc(c.symbol)}')">` +
      `<td class="td-ticker-portfolio"><span class="wl-ticker">${esc(c.symbol)}<span class="ticker-goto-icon">↗</span></span></td>` +
      `<td class="td-company">${esc(c.companyName)}</td>` +
      `<td>${esc(c.sector)}</td>` +
      `<td>${fmtEur(c.totalAmount)}</td>` +
      `<td>${c.purchases}</td>` +
      `<td>${fmtEur(avg)}</td>` +
      `<td>${c.totalShares.toFixed(2)}</td>` +
      `</tr>`
    );
  }).join('');

  container.innerHTML =
    headerHTML +
    `<div class="table-wrap"><table class="data-table">` +
    `<thead><tr>` +
    `<th>Ticker</th><th>Company</th><th>Sector</th>` +
    `<th>Total Invested (${getCurrencySymbol()})</th><th>Purchases</th><th>Avg. Price/Share</th><th>Total Shares</th>` +
    `</tr></thead>` +
    `<tbody>${rows}</tbody>` +
    `</table></div>`;
}


// ===== Portfolio Dividends Received =====

function _dividendsSectionShell() {
  return (
    `<div class="section-title-row">` +
    `<h3 class="section-title">Dividends Received</h3>` +
    `</div>` +
    `<p class="dividends-section-note">Based on shares held since first purchase date. Actual amounts may vary depending on exact purchase timing.</p>`
  );
}

function _dividendsSkeleton(count) {
  const rows = Array(Math.min(count, 6)).fill(0).map(() =>
    `<tr>` + Array(6).fill(`<td><div class="skeleton-cell"></div></td>`).join('') + `</tr>`
  ).join('');
  return (
    `<div class="table-wrap"><table class="data-table">` +
    `<thead><tr>` +
    `<th>Ticker</th><th>Company</th><th>Shares</th>` +
    `<th>Total Received</th><th>Last Payment</th><th>Payments Count</th>` +
    `</tr></thead>` +
    `<tbody>${rows}</tbody>` +
    `</table></div>`
  );
}

async function renderPortfolioDividendsReceived(portfolio) {
  const container = document.getElementById('portfolio-dividends-container');
  if (!container) return;

  _dividendsCache = null;

  if (!portfolio.length) return;

  // Build per-company data: earliest purchase date and total shares
  const companyMap = {};
  for (const p of portfolio) {
    if (!companyMap[p.symbol]) {
      companyMap[p.symbol] = { symbol: p.symbol, companyName: p.companyName, sector: p.sector || '', totalShares: 0, earliestDate: p.date };
    }
    companyMap[p.symbol].totalShares += p.shares;
    if (p.date < companyMap[p.symbol].earliestDate) companyMap[p.symbol].earliestDate = p.date;
  }
  const companyList = Object.values(companyMap);

  // Fetch dividends for all companies in parallel (max 5 concurrent)
  const results = {};
  await asyncPool(5, companyList, async (co) => {
    try {
      const params = new URLSearchParams({ symbol: co.symbol, from_date: co.earliestDate, shares: String(co.totalShares) });
      const res = await fetch(`/api/dividends-received?${params}`);
      if (!res.ok) throw new Error();
      results[co.symbol] = await res.json();
    } catch (_) {
      results[co.symbol] = { dividends: [], totalReceived: 0, currency: 'USD' };
    }
  });

  _dividendsCache = { companyList, results };
  _renderDividendsFromCache();
}


// ===== Dividends Tab =====

async function renderDividendsView() {
  const portfolio = getPortfolio();

  if (!portfolio.length) {
    document.getElementById('div-summary-cards').innerHTML = '';
    const chartEl = document.getElementById('div-annual-chart');
    if (chartEl) chartEl.style.display = 'none';
    document.getElementById('div-payments-container').innerHTML =
      '<p class="empty-state-view">No dividend payments recorded yet. Add purchases to your portfolio to start tracking dividends.</p>';
    return;
  }

  if (_dividendsTabCache) {
    _renderDividendsTabContent();
    return;
  }

  const container = document.getElementById('div-payments-container');
  if (container) {
    container.innerHTML = '<div class="loading"><div class="spinner"></div><div>Loading dividend data…</div></div>';
  }

  const companyMap = {};
  for (const p of portfolio) {
    if (!companyMap[p.symbol]) {
      companyMap[p.symbol] = { symbol: p.symbol, companyName: p.companyName, totalShares: 0, earliestDate: p.date };
    }
    companyMap[p.symbol].totalShares += p.shares;
    if (p.date < companyMap[p.symbol].earliestDate) companyMap[p.symbol].earliestDate = p.date;
  }
  const companyList = Object.values(companyMap);

  const results = {};
  await asyncPool(5, companyList, async (co) => {
    try {
      const params = new URLSearchParams({ symbol: co.symbol, from_date: co.earliestDate, shares: String(co.totalShares) });
      const res = await fetch(`/api/dividends-received?${params}`);
      if (!res.ok) throw new Error();
      results[co.symbol] = await res.json();
    } catch (_) {
      results[co.symbol] = { dividends: [], totalReceived: 0 };
    }
  });

  _dividendsTabCache = { companyList, results };
  _renderDividendsTabContent();
}

function onDivYearFilter(val) {
  divTabYearFilter = val;
  _renderDividendsTabContent();
}

function toggleDivTabDateSort() {
  divTabDateSortDir *= -1;
  _renderDividendsTabContent();
}

function _renderDividendsTabContent() {
  if (!_dividendsTabCache) return;
  const { companyList, results } = _dividendsTabCache;

  const tax    = getWithholdingTax();
  const sym    = getCurrencySymbol();
  const fmtAmt = v => sym + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // Flatten all payments across companies
  const allPayments = [];
  for (const co of companyList) {
    const data = results[co.symbol] || { dividends: [] };
    for (const pmt of (data.dividends || [])) {
      allPayments.push({
        date:        pmt.date,
        symbol:      co.symbol,
        companyName: co.companyName,
        gross:       pmt.totalAmount,
        net:         pmt.totalAmount * (1 - tax / 100),
      });
    }
  }

  // Available years (descending)
  const years = [...new Set(allPayments.map(p => p.date.slice(0, 4)))].sort((a, b) => b - a);

  // Populate year filter
  const select = document.getElementById('div-year-filter');
  if (select) {
    const current = divTabYearFilter;
    select.innerHTML = '<option value="all">All Time</option>' +
      years.map(y => `<option value="${y}"${y === current ? ' selected' : ''}>${y}</option>`).join('');
    if (current !== 'all' && !years.includes(current)) {
      divTabYearFilter = 'all';
      select.value = divTabYearFilter;
    }
  }

  // Filter payments for selected period
  const filtered = divTabYearFilter === 'all'
    ? allPayments
    : allPayments.filter(p => p.date.startsWith(divTabYearFilter));

  _renderDivSummaryCards(filtered, sym, fmtAmt);
  _renderDivAnnualChart(allPayments, sym, tax);
  _renderDivPaymentsTable(filtered, allPayments, sym, fmtAmt, tax);
}

function _renderDivSummaryCards(filtered, sym, fmtAmt) {
  const container = document.getElementById('div-summary-cards');
  if (!container) return;

  const totalGross = filtered.reduce((s, p) => s + p.gross, 0);
  const totalNet   = filtered.reduce((s, p) => s + p.net,   0);
  const taxPaid    = totalGross - totalNet;
  const count      = filtered.length;

  const cards = [
    { label: 'Total Received (net)', value: fmtAmt(totalNet),   accent: true  },
    { label: 'Total Gross',          value: fmtAmt(totalGross), accent: false },
    { label: 'Tax Paid',             value: fmtAmt(taxPaid),    accent: false },
    { label: 'Payments',             value: String(count),       accent: false },
  ];

  container.innerHTML = cards.map(c =>
    `<div class="summary-card${c.accent ? ' summary-card-accent' : ''}">` +
    `<div class="summary-card-label">${esc(c.label)}</div>` +
    `<div class="summary-card-value">${esc(c.value)}</div>` +
    `</div>`
  ).join('');
}

function _renderDivAnnualChart(allPayments, sym, tax) {
  const chartCard = document.getElementById('div-annual-chart');
  if (!chartCard) return;

  if (!allPayments.length) { chartCard.style.display = 'none'; return; }
  chartCard.style.display = 'block';

  const yearTotals = {};
  for (const p of allPayments) {
    const year = p.date.slice(0, 4);
    yearTotals[year] = (yearTotals[year] || 0) + p.net;
  }
  const years  = Object.keys(yearTotals).sort();
  const values = years.map(y => yearTotals[y]);

  const canvas = document.getElementById('div-annual-canvas');
  if (!canvas) return;

  if (divTabChartInst) { divTabChartInst.destroy(); divTabChartInst = null; }

  const isLight    = document.body.classList.contains('light-theme');
  const labelColor = isLight ? '#374151' : '#9ca3af';
  const gridColor  = isLight ? '#e2e8f0' : '#1f2937';

  const barLabelPlugin = {
    id: 'divBarLabels',
    afterDatasetsDraw(chart) {
      const { ctx } = chart;
      const meta = chart.getDatasetMeta(0);
      ctx.save();
      ctx.font = '600 11px Inter, system-ui, sans-serif';
      ctx.fillStyle = labelColor;
      ctx.textAlign = 'center';
      meta.data.forEach((bar, i) => {
        const val = chart.data.datasets[0].data[i];
        ctx.fillText(
          sym + val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
          bar.x, bar.y - 6
        );
      });
      ctx.restore();
    },
  };

  divTabChartInst = new Chart(canvas, {
    type: 'bar',
    data: {
      labels:   years,
      datasets: [{ data: values, backgroundColor: '#22c55e', borderRadius: 4 }],
    },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      layout: { padding: { top: 28 } },
      plugins: {
        legend:  { display: false },
        tooltip: { callbacks: { label: ctx => ' ' + sym + ctx.parsed.y.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: labelColor, font: { size: 12 } } },
        y: { grid: { color: gridColor }, ticks: { color: labelColor, callback: v => sym + v.toFixed(0) } },
      },
    },
    plugins: [barLabelPlugin],
  });
}

function _renderDivPaymentsTable(filtered, allPayments, sym, fmtAmt, tax) {
  const container = document.getElementById('div-payments-container');
  if (!container) return;

  if (!allPayments.length) {
    container.innerHTML =
      '<p class="empty-state-view">No dividend payments recorded yet. Add purchases to your portfolio to start tracking dividends.</p>';
    return;
  }

  const sorted = [...filtered].sort((a, b) =>
    divTabDateSortDir * (a.date < b.date ? 1 : a.date > b.date ? -1 : 0)
  );

  const sortIcon = divTabDateSortDir === -1 ? '↓' : '↑';

  const headerHTML =
    `<div class="section-title-row"><h3 class="section-title">Payments</h3></div>`;

  if (!sorted.length) {
    container.innerHTML = headerHTML +
      '<p class="empty-state-view">No payments in the selected period.</p>';
    return;
  }

  let rowsHTML = '';
  if (divTabYearFilter === 'all') {
    let currentYear = null;
    for (const pmt of sorted) {
      const year = pmt.date.slice(0, 4);
      if (year !== currentYear) {
        currentYear = year;
        rowsHTML += `<tr class="div-year-separator-row"><td colspan="6">${esc(year)}</td></tr>`;
      }
      rowsHTML += _divPaymentRowHTML(pmt, fmtAmt, tax);
    }
  } else {
    rowsHTML = sorted.map(pmt => _divPaymentRowHTML(pmt, fmtAmt, tax)).join('');
  }

  container.innerHTML =
    headerHTML +
    `<div class="table-wrap"><table class="data-table">` +
    `<thead><tr>` +
    `<th class="sortable" onclick="toggleDivTabDateSort()">Date <span class="sort-indicator active">${sortIcon}</span></th>` +
    `<th>Ticker</th><th>Company</th>` +
    `<th>Amount (gross)</th><th>Tax</th><th>Amount (net)</th>` +
    `</tr></thead>` +
    `<tbody>${rowsHTML}</tbody>` +
    `</table></div>`;
}

function _divPaymentRowHTML(pmt, fmtAmt, tax) {
  return (
    `<tr>` +
    `<td>${esc(formatDate(pmt.date))}</td>` +
    `<td class="td-ticker-portfolio" onclick="analyzeStock('${esc(pmt.symbol)}')">` +
    `<span class="wl-ticker">${esc(pmt.symbol)}<span class="ticker-goto-icon">↗</span></span></td>` +
    `<td class="td-company">${esc(pmt.companyName)}</td>` +
    `<td>${fmtAmt(pmt.gross)}</td>` +
    `<td>${tax}%</td>` +
    `<td>${fmtAmt(pmt.net)}</td>` +
    `</tr>`
  );
}


// ===== Portfolio Modal =====

function openAddPurchaseModal() {
  modalSelectedStock = null;
  document.getElementById('modal-search-input').value = '';
  hideModalSugg();
  document.getElementById('modal-date').value          = new Date().toISOString().split('T')[0];
  document.getElementById('modal-amount').value        = '';
  document.getElementById('modal-exact-shares').value  = '';
  document.getElementById('modal-error').classList.add('hidden');
  document.getElementById('modal-submit-btn').disabled    = false;
  document.getElementById('modal-submit-btn').textContent = 'Add Purchase';
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('purchase-modal').classList.remove('hidden');
  document.getElementById('modal-search-input').focus();
}

function closeAddPurchaseModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  document.getElementById('purchase-modal').classList.add('hidden');
}

async function submitAddPurchase() {
  const submitBtn = document.getElementById('modal-submit-btn');
  const errorEl   = document.getElementById('modal-error');
  errorEl.classList.add('hidden');

  if (!modalSelectedStock) {
    showModalError('Please search and select a company.');
    return;
  }
  const dateVal        = document.getElementById('modal-date').value;
  const amountVal      = parseFloat(document.getElementById('modal-amount').value);
  const exactSharesRaw = document.getElementById('modal-exact-shares').value.trim();
  const exactShares    = exactSharesRaw !== '' ? parseFloat(exactSharesRaw) : null;

  if (!dateVal) {
    showModalError('Please select a purchase date.');
    return;
  }
  if (!amountVal || amountVal <= 0) {
    showModalError('Please enter a valid amount greater than 0.');
    return;
  }
  if (exactShares !== null && (!exactShares || exactShares <= 0)) {
    showModalError('Exact shares must be greater than 0.');
    return;
  }

  submitBtn.disabled    = true;
  submitBtn.textContent = 'Adding…';

  try {
    const sym = modalSelectedStock.symbol;

    let rawSector   = modalSelectedStock.sector   || '';
    let rawIndustry = modalSelectedStock.industry || '';
    let purchaseDate = dateVal;
    let pricePerShare;
    let shares;
    let exactSharesProvided;

    if (exactShares !== null) {
      // User provided exact shares — back-calculate price, skip historical price fetch
      const analyzeRes = await fetch(`/api/analyze/${encodeURIComponent(sym)}`);
      if (analyzeRes.ok) {
        const analyzeData = await analyzeRes.json();
        rawSector   = analyzeData.sector   || rawSector;
        rawIndustry = analyzeData.industry || rawIndustry;
      }
      shares             = exactShares;
      pricePerShare      = amountVal / exactShares;
      exactSharesProvided = true;
    } else {
      const [priceRes, analyzeRes] = await Promise.all([
        fetch(`/api/historical-price?symbol=${encodeURIComponent(sym)}&date=${encodeURIComponent(dateVal)}`),
        fetch(`/api/analyze/${encodeURIComponent(sym)}`),
      ]);
      if (!priceRes.ok) throw new Error('Could not fetch price data for that date.');
      const priceData = await priceRes.json();
      if (!priceData.price || priceData.price <= 0) throw new Error('Invalid price received.');
      if (analyzeRes.ok) {
        const analyzeData = await analyzeRes.json();
        rawSector   = analyzeData.sector   || rawSector;
        rawIndustry = analyzeData.industry || rawIndustry;
      }
      purchaseDate        = priceData.date || dateVal;
      pricePerShare       = priceData.price;
      shares              = amountVal / priceData.price;
      exactSharesProvided = false;
    }

    const purchase = {
      id:                  String(Date.now()),
      symbol:              sym,
      companyName:         modalSelectedStock.companyName,
      sector:              mapSector(rawSector, rawIndustry, sym),
      industry:            rawIndustry,
      date:                purchaseDate,
      amountEUR:           amountVal,
      pricePerShare,
      shares,
      exactSharesProvided,
    };

    const portfolio = getPortfolio();
    portfolio.push(purchase);
    savePortfolio(portfolio);

    _dividendsTabCache = null;
    closeAddPurchaseModal();
    if (currentView === 'portfolio') renderPortfolio();
  } catch (e) {
    showModalError(e.message || 'Failed to add purchase. Please try again.');
  } finally {
    submitBtn.disabled    = false;
    submitBtn.textContent = 'Add Purchase';
  }
}

function showModalError(msg) {
  const el = document.getElementById('modal-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}


// ===== CSV Export =====

function exportCSV(filename, headers, rows) {
  const escape = v => {
    const s = String(v ?? '');
    return (s.includes(',') || s.includes('"') || s.includes('\n'))
      ? `"${s.replace(/"/g, '""')}"`
      : s;
  };
  const lines = [headers, ...rows].map(row => row.map(escape).join(','));
  const blob  = new Blob([lines.join('\n')], { type: 'text/csv' });
  const url   = URL.createObjectURL(blob);
  const a     = document.createElement('a');
  a.href      = url;
  a.download  = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function exportWatchlistCSV() {
  const wl = getWatchlist();
  if (!wl.length) return;
  const today   = new Date().toISOString().split('T')[0];
  const headers = ['Ticker', 'Company', 'Sector', 'Recommendation', 'Div. Yield (%)', 'PER', 'Dividend Trend', 'Notes'];
  const rows    = wl.map(item => {
    const sector = mapSector(item.sector, item.industry || '', item.symbol);
    const rec    = REC_BADGE_CFG[item.recommendation]?.label || item.recommendation || '';
    const trend  = item.dividendTrend ? (TREND_CFG[item.dividendTrend]?.label || item.dividendTrend) : '';
    return [
      item.symbol,
      item.name || '',
      sector,
      rec,
      item.divYield != null ? item.divYield.toFixed(2) : '',
      item.per      != null ? item.per.toFixed(1)      : '',
      trend,
      item.notes || '',
    ];
  });
  exportCSV(`dividend_lens_watchlist_${today}.csv`, headers, rows);
}

function exportPurchasesCSV() {
  const portfolio = getPortfolio();
  if (!portfolio.length) return;
  const today   = new Date().toISOString().split('T')[0];
  const headers = ['Date', 'Ticker', 'Company', 'Sector', 'Amount (EUR)', 'Price/Share', 'Shares'];
  const sorted  = [...portfolio].sort((a, b) =>
    purchaseDateSortDir * (a.date < b.date ? 1 : a.date > b.date ? -1 : 0)
  );
  const rows = sorted.map(p => [
    p.date,
    p.symbol,
    p.companyName,
    p.sector,
    p.amountEUR.toFixed(2),
    p.pricePerShare.toFixed(4),
    p.shares.toFixed(2),
  ]);
  exportCSV(`dividend_lens_purchases_${today}.csv`, headers, rows);
}

function exportSummaryCSV() {
  const portfolio = getPortfolio();
  if (!portfolio.length) return;
  const today     = new Date().toISOString().split('T')[0];
  const headers   = ['Ticker', 'Company', 'Sector', 'Total Invested (EUR)', 'Purchases', 'Avg Price/Share', 'Total Shares'];
  const companies = {};
  for (const p of portfolio) {
    if (!companies[p.symbol]) {
      companies[p.symbol] = { symbol: p.symbol, companyName: p.companyName, sector: p.sector, totalAmount: 0, totalShares: 0, purchases: 0 };
    }
    companies[p.symbol].totalAmount += p.amountEUR;
    companies[p.symbol].totalShares += p.shares;
    companies[p.symbol].purchases   += 1;
  }
  const sorted = Object.values(companies).sort((a, b) => b.totalAmount - a.totalAmount);
  const rows   = sorted.map(c => {
    const avg = c.totalAmount / c.totalShares;
    return [c.symbol, c.companyName, c.sector, c.totalAmount.toFixed(2), String(c.purchases), avg.toFixed(4), c.totalShares.toFixed(2)];
  });
  exportCSV(`dividend_lens_summary_${today}.csv`, headers, rows);
}


// ===== Tooltip =====

const globalTooltip = document.createElement('div');
globalTooltip.id = 'global-tooltip';
document.body.appendChild(globalTooltip);

function attachTooltipListeners() {
  document.querySelectorAll('.info-icon').forEach(icon => {
    icon.addEventListener('mouseenter', () => {
      globalTooltip.innerHTML = icon.dataset.tooltip;
      globalTooltip.style.opacity = '1';

      const ir  = icon.getBoundingClientRect();
      const tw  = globalTooltip.offsetWidth;
      const th  = globalTooltip.offsetHeight;
      const pad = 8;

      let top  = ir.top - th - pad;
      let left = ir.left - tw + ir.width;

      if (top < pad)                           top  = ir.bottom + pad;
      if (left < pad)                          left = pad;
      if (left + tw > window.innerWidth - pad) left = window.innerWidth - tw - pad;

      globalTooltip.style.top  = top  + 'px';
      globalTooltip.style.left = left + 'px';
    });
    icon.addEventListener('mouseleave', () => {
      globalTooltip.style.opacity = '0';
    });
  });
}


// ===== Utility =====

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}


// ===== Init =====

const debouncedSearch      = debounce(searchStocks,      400);
const debouncedNavSearch   = debounce(searchNavStocks,   400);
const debouncedModalSearch = debounce(searchModalStocks, 400);

document.getElementById('search-input').addEventListener('input', e => debouncedSearch(e.target.value));
document.getElementById('search-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') { const v = e.target.value.trim(); if (v) { hideSugg(); analyzeStock(v); } }
});

document.getElementById('nav-search-input').addEventListener('input', e => debouncedNavSearch(e.target.value));
document.getElementById('nav-search-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') { const v = e.target.value.trim(); if (v) { hideNavSugg(); analyzeStock(v); } }
});

document.getElementById('modal-search-input').addEventListener('input', e => {
  modalSelectedStock = null;
  debouncedModalSearch(e.target.value);
});
document.getElementById('modal-search-input').addEventListener('keydown', e => {
  if (e.key === 'Escape') closeAddPurchaseModal();
});

document.addEventListener('click', e => {
  if (!e.target.closest('.home-pill')         && !e.target.closest('#suggestions'))       hideSugg();
  if (!e.target.closest('.nav-pill-wrap')     && !e.target.closest('#nav-suggestions'))   hideNavSugg();
  if (!e.target.closest('.modal-search-wrap') && !e.target.closest('#modal-suggestions')) hideModalSugg();
  if (!e.target.closest('#settings-btn')      && !e.target.closest('#settings-panel'))    closeSettings();
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeAddPurchaseModal();
});

initSettings();
populateWlSectorFilter();
updateWlBadge();
migratePortfolioSectors();

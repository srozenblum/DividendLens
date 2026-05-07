# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the dev server (hot-reload)
uvicorn main:app --reload

# App is served at http://localhost:8000
```

## Architecture

Single-file FastAPI backend (`main.py`) that serves both the REST API and the static frontend from `static/`.

**Request flow:**
1. Browser loads `static/index.html`, which pulls in `style.css` and `app.js`
2. `app.js` calls `/api/search?q=` for ticker suggestions (debounced, 400 ms)
3. Selecting a result calls `/api/analyze/{ticker}`, which fetches all data from yfinance in one shot and returns a single JSON payload

**API endpoints:**
- `GET /api/search?q=` — wraps `yf.Search`, returns up to 6 `{symbol, name, exchange}` results
- `GET /api/analyze/{ticker}` — returns company info, 5 scored metrics, dividend info, and 52-week weekly price history

**Scoring (`score_stock` in `main.py`):**
Each of the 5 metrics (PER, yield, debt/EBITDA, P/B, payout) gets an individual score string. `overallRecommendation` is derived from `perScore` + `yieldScore` only, in this priority: `insufficient_data` → `avoid` → `strong_buy` → `buy` → `neutral`. Stable sectors (utilities, consumer staples, financial services, insurance) get a relaxed PER threshold (≤ 20 still counts as "neutral").

**Frontend (`static/`):**
- `index.html` — static shell; almost all content is injected by JS
- `style.css` — dark theme (#0f1117 bg, #1a1d27 cards); score colours: green `#22c55e` / yellow `#eab308` / red `#ef4444`
- `app.js` — no framework; `METRICS` array drives metric card rendering; `SCORE_CFG` maps score strings to display labels and CSS classes; Chart.js line chart is destroyed and recreated on each new analysis; watchlist persisted in `localStorage` under key `wl`

**Route ordering matters:** API routes must be declared before `app.mount("/", StaticFiles(...))` or FastAPI will never reach them.

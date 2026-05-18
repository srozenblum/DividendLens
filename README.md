# 📊 Dividend Lens

A clean, local tool for analyzing stocks through a dividend value investing lens — built for long-term investors who prefer simplicity over noise.

---

## What it does

Dividend Lens helps you decide whether a stock is worth buying **right now**, based on the fundamentals that matter most for dividend investing:

- **P/E Ratio** — is the price reasonable relative to earnings?
- **Dividend Yield** — how much will it pay you annually?
- **Debt / EBITDA** — can the company sustain its dividend?
- **Price / Book** — are you buying assets at a fair price?
- **Payout Ratio** — is the dividend healthy and sustainable?

Each stock gets a clear recommendation: STRONG BUY · BUY · NEUTRAL · OVERVALUED · NO DIVIDENDS

---

## Features

- 🔍 **Analyze** any stock by name or ticker
- ⭐ **Watchlist** with sector grouping, filters, sorting, notes and parallel auto-refresh
- 📊 **Portfolio tracker** with purchase history, weighted average price and sector allocation
- 💰 **Dividends tracker** with per-payment breakdown, tax calculation and annual chart
- 🌗 **Dark / light theme** and customizable buy thresholds
- 💾 **CSV export** for watchlist and portfolio data
- 📡 Data powered by Yahoo Finance via yfinance — no API key needed

---

## How to run

**Requirements:** Python 3.8+

Clone the repo:

    git clone https://github.com/srozenblum/DividendLens.git
    cd DividendLens

**Mac**
Double-click start.command

**Windows**
Double-click start.bat

Or manually on either platform:

    pip install -r requirements.txt
    uvicorn main:app --reload

Then open http://localhost:8000 in your browser.

---

## Tech stack

Python · FastAPI · yfinance · HTML / CSS / JavaScript

---

## Disclaimer

This tool is for informational purposes only and does not constitute financial advice. Always do your own research before making investment decisions.

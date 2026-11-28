from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional
import asyncio
import threading
import yfinance as yf
import math
import datetime
import json
import re
import statistics
from decimal import Decimal, ROUND_HALF_UP

from yahoo_cache import (
    YAHOO_CONCURRENCY,
    cached_cashflow,
    cached_dividend_date,
    cached_dividends,
    cached_info,
    cached_price_history,
    cached_statements,
    call_yahoo,
)

app = FastAPI()

# One request can refresh a whole watchlist. Above this, callers should page.
MAX_WATCHLIST_BATCH = 200


def safe_float(value):
    if value is None:
        return None
    try:
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


# Yield is printed to 2 decimals (4.00%) and P/E to 1 decimal (15.0x).
# Score those displayed figures. 3.9999 is shown as 4.00% and must meet a
# 4% minimum; 15.04 is shown as 15.0x and must meet a 15x cap.
YIELD_DISPLAY_DECIMALS = 2
PER_DISPLAY_DECIMALS = 1


def displayed_number(value, digits):
    """Round the way the page prints the figure (JavaScript Number.toFixed)."""
    number = safe_float(value)
    if number is None:
        return None
    quantum = Decimal(1).scaleb(-int(digits))
    rounded = Decimal.from_float(number).quantize(quantum, rounding=ROUND_HALF_UP)
    return float(rounded)


def get_sector_profile(sector: str, industry: str) -> str:
    sec = (sector or "").lower()
    ind = (industry or "").lower()
    if "real estate" in sec or "reit" in ind:
        return "reit"
    if any(k in ind for k in ["bank", "savings", "mortgage", "credit"]):
        return "bank"
    if "utilities" in sec:
        return "utility"
    if "energy" in sec or any(k in ind for k in ["oil", "gas", "petroleum"]):
        return "oil"
    if "technology" in sec:
        return "tech"
    # "Insurance - Diversified" is an operating insurer, not a holding company.
    # Matching the bare word "diversified" made P/E not applicable and capped
    # AXA (CS.PA) at BUY no matter how cheap it was.
    if _is_holding_industry(ind):
        return "holding"
    return "default"


def _is_holding_industry(ind: str) -> bool:
    if "conglomerate" in ind or "holding" in ind:
        return True
    return ind.strip() in {
        "diversified",
        "diversified financials",
        "diversified financial services",
    }


def resolved_per(info: dict):
    per = safe_float(info.get("trailingPE"))
    if per is None or per <= 0:
        per = safe_float(info.get("forwardPE"))
        if per is not None and per <= 0:
            per = None
    return per


def dividend_yield_percent(info: dict):
    """Forward yield as a percent (5.06 means 5.06%).

    This is dividendRate / price, with the existing dividendYield fallback.
    Recommendations use this figure. The trailing 12-month yield is
    display-only.
    """
    dividend_rate = safe_float(info.get("dividendRate")) or safe_float(info.get("lastDividendValue"))
    current_price = safe_float(info.get("currentPrice")) or safe_float(info.get("regularMarketPrice"))
    if dividend_rate and current_price and current_price > 0:
        return round((dividend_rate / current_price) * 100, 2)
    _dy_raw = safe_float(info.get("dividendYield", None))
    if _dy_raw is None or _dy_raw <= 0:
        return None
    if _dy_raw < 0.50:
        return round(_dy_raw * 100, 2)
    if _dy_raw > 30:
        return None
    return round(_dy_raw, 2)


def resolve_score_thresholds(min_yield=None, max_per=None, minYield=None, maxPer=None):
    """Accept the snake_case query names and the camelCase names the UI sends.

    FastAPI binds parameter names exactly, so minYield used to be ignored and
    every analysis was scored at the 4% / 15x defaults.
    """
    if min_yield is None:
        min_yield = 4.0 if minYield is None else minYield
    if max_per is None:
        max_per = 15.0 if maxPer is None else maxPer
    return float(min_yield), float(max_per)


# A cash payout above this percent warns. Exactly 100% is still covered.
FCF_PAYOUT_WARNING_PERCENT = 100.0


def _is_operating_insurer(industry: str) -> bool:
    """True for insurers whose cash flow is not a dividend-cover measure.

    Insurance brokers are left out: they run an operating business, so
    free cash flow still means something.
    """
    ind = (industry or "").lower()
    return "insurance" in ind and "broker" not in ind


def cash_payout_basis(sector: str, industry: str) -> str:
    """Which cash payout, if any, is meaningful for this company.

    "ffo" for REITs, "skipped" for banks and insurers, "fcf" otherwise.
    The bank profile already covers banks, savings, mortgage lenders and
    credit, matching get_sector_profile. Skipped ratios are not a warning.
    """
    profile = get_sector_profile(sector or "", industry or "")
    if profile == "bank":
        return "skipped"
    if profile == "reit":
        return "ffo"
    if _is_operating_insurer(industry):
        return "skipped"
    return "fcf"


def _flag(value) -> bool:
    """True only for a real boolean True. Missing and other types do not warn."""
    return value is True


def sustainability_warning(sector, industry, fcf_payout, fcf_deficit, dividend_cut) -> bool:
    """True when the dividend looks uncovered or was cut in recent years.

    Missing figures never warn. Banks and insurers ignore the cash payout.
    A payout of exactly 100% does not warn.
    """
    if _flag(dividend_cut):
        return True
    if cash_payout_basis(sector, industry) == "skipped":
        return False
    if _flag(fcf_deficit):
        return True
    payout = safe_float(fcf_payout)
    return payout is not None and payout > FCF_PAYOUT_WARNING_PERCENT


_SECTOR_NOTES = {
    "reit":    "REITs distribute most earnings as dividends. P/E ratio is not meaningful — focus on yield and P/B instead.",
    "bank":    "For banks, Price/Book is more meaningful than P/E. A P/B below 1 means you're buying assets at a discount.",
    "utility": "Utilities carry structural debt to fund infrastructure. Higher debt ratios are normal and generally not a concern.",
    "oil":     "Oil & Gas companies are cyclical — profits and dividends depend heavily on commodity prices. Best bought when oil prices are low, not high.",
    "tech":    "Technology companies often trade at higher P/E ratios. However, for a dividend strategy, prefer established tech companies with consistent payouts over high-growth names.",
    "holding": "Holdings invest in other companies. Standard ratios like P/E and P/B are less meaningful — focus on dividend track record and debt levels.",
}


def score_metrics(
    sector: str = "",
    industry: str = "",
    per=None,
    dividend_yield=None,
    debt_to_ebitda=None,
    price_to_book=None,
    payout_percent=None,
    min_yield: float = 4.0,
    max_per: float = 15.0,
    fcf_payout=None,
    fcf_deficit=False,
    dividend_cut=False,
) -> dict:
    """Score already-resolved metrics. payout_percent is on a 0–100 scale.

    The browser ports this function (static/scoring.js) so a watchlist row
    can be re-labeled from stored metrics when the yield or P/E slider moves,
    without calling Yahoo again.

    fcf_payout is dividends / free cash flow (or FFO for a REIT) as a
    percent. fcf_deficit means dividends were paid while that cash figure
    was not positive. dividend_cut means the regular dividend fell in the
    last five complete years. Either warning downgrades a Strong Buy to
    Buy and does nothing to any other label. Missing values do not warn.
    """
    profile = get_sector_profile(sector or "", industry or "")

    per = safe_float(per)
    if per is not None and per <= 0:
        per = None
    dividend_yield = safe_float(dividend_yield)
    debt_to_ebitda = safe_float(debt_to_ebitda)
    price_to_book = safe_float(price_to_book)
    payout_percent = safe_float(payout_percent)

    if profile in ("reit", "holding"):
        per_score = "not_applicable"
    elif per is None:
        per_score = "unavailable"
    elif profile == "bank":
        per_score = "buy" if per < 10 else ("neutral" if per <= 15 else "expensive")
    elif profile == "tech":
        per_score = "buy" if per < 20 else ("neutral" if per <= 30 else "expensive")
    elif profile == "utility":
        per_score = "buy" if per < 18 else ("neutral" if per <= 22 else "expensive")
    else:
        # Default and oil. A P/E at or below max_per is a buy. 15.04 is
        # shown as 15.0x, so it still meets a 15x cap.
        shown_per = displayed_number(per, PER_DISPLAY_DECIMALS)
        shown_cap = displayed_number(max_per, PER_DISPLAY_DECIMALS)
        per_score = "buy" if shown_per <= shown_cap else ("neutral" if shown_per <= 20 else "expensive")

    # dividend_yield is the forward yield. REIT "buy" stays strictly above 5
    # and ignores the slider. Every other profile is a buy at or above
    # min_yield (default 4), using the 2 decimals the yield card shows.
    # The trailing 12-month yield is display-only and does not change the
    # recommendation.
    if dividend_yield is None:
        yield_score = "none"
    elif profile == "reit":
        yield_score = "buy" if dividend_yield > 5 else ("neutral" if dividend_yield >= 3 else "low")
    else:
        shown_yield = displayed_number(dividend_yield, YIELD_DISPLAY_DECIMALS)
        shown_min = displayed_number(min_yield, YIELD_DISPLAY_DECIMALS)
        yield_score = "buy" if shown_yield >= shown_min else ("neutral" if shown_yield >= 2 else "low")

    if debt_to_ebitda is None:
        debt_score = "unavailable"
    elif profile == "utility":
        debt_score = "safe" if debt_to_ebitda < 4 else ("moderate" if debt_to_ebitda <= 5 else "high")
    else:
        debt_score = "safe" if debt_to_ebitda < 3 else ("moderate" if debt_to_ebitda <= 4 else "high")

    if profile == "holding":
        book_score = "not_applicable"
    elif price_to_book is None:
        book_score = "unavailable"
    elif profile == "bank":
        book_score = "buy" if price_to_book < 1 else ("fair" if price_to_book <= 1.5 else "expensive")
    elif profile == "reit":
        book_score = "buy" if price_to_book < 1.2 else ("fair" if price_to_book <= 2 else "expensive")
    else:
        book_score = "buy" if price_to_book < 1 else ("fair" if price_to_book <= 2 else "expensive")

    if profile == "holding":
        payout_score = "not_applicable"
    elif payout_percent is None:
        payout_score = "unavailable"
    elif payout_percent < 40:
        payout_score = "low"
    elif payout_percent <= 60:
        payout_score = "healthy"
    elif payout_percent <= 80:
        payout_score = "high"
    else:
        payout_score = "very_high"

    all_scores = [per_score, yield_score, debt_score, book_score, payout_score]
    unavailable_count = sum(1 for s in all_scores if s == "unavailable")

    if unavailable_count > 2:
        overall = "insufficient_data"
    elif yield_score == "none":
        overall = "avoid_no_dividends"
    elif per_score == "buy" and yield_score == "buy":
        overall = "strong_buy"
    elif (per_score == "buy" or yield_score == "buy") and per_score != "expensive":
        overall = "buy"
    elif per_score == "expensive" or yield_score == "low":
        overall = "avoid_overvalued"
    else:
        overall = "neutral"

    warning = sustainability_warning(sector, industry, fcf_payout, fcf_deficit, dividend_cut)
    if overall == "strong_buy" and warning:
        overall = "buy"

    return {
        "perScore":              per_score,
        "yieldScore":            yield_score,
        "debtScore":             debt_score,
        "bookScore":             book_score,
        "payoutScore":           payout_score,
        "overallRecommendation": overall,
        "sustainabilityWarning": warning,
        "sectorProfile":         profile,
        "sectorNote":            _SECTOR_NOTES.get(profile),
    }


def score_stock(
    info: dict,
    debt_to_ebitda,
    min_yield: float = 4.0,
    max_per: float = 15.0,
    fcf_payout=None,
    fcf_deficit=False,
    dividend_cut=False,
) -> dict:
    info = info or {}
    payout = safe_float(info.get("payoutRatio"))
    return score_metrics(
        sector=info.get("sector") or "",
        industry=info.get("industry") or "",
        per=resolved_per(info),
        dividend_yield=dividend_yield_percent(info),
        debt_to_ebitda=debt_to_ebitda,
        price_to_book=safe_float(info.get("priceToBook")),
        payout_percent=None if payout is None else payout * 100,
        min_yield=min_yield,
        max_per=max_per,
        fcf_payout=fcf_payout,
        fcf_deficit=fcf_deficit,
        dividend_cut=dividend_cut,
    )


def dividend_growth_trend(stock) -> str:
    try:
        divs = getattr(stock, "dividends", None)
        if divs is None:
            return "insufficient_data"
        try:
            if len(divs) == 0:
                return "insufficient_data"
        except TypeError:
            return "insufficient_data"

        as_of = datetime.date.today()
        rates = _rates_by_year(divs, as_of)
        latest = as_of.year - 1
        values = [rates[year] for year in range(latest - 4, latest + 1) if year in rates]
        if len(values) < 2:
            return "insufficient_data"
        values = values[-3:]

        if all(values[i] < values[i + 1] for i in range(len(values) - 1)):
            return "growing"

        max_v, min_v = max(values), min(values)
        if max_v > 0 and (max_v - min_v) / max_v < 0.10:
            return "stable"

        return "declining"
    except Exception:
        return "insufficient_data"


EXCHANGE_PRIORITY = [
    # Spanish
    "MCE", "BME", "MAD",
    # American
    "NMS", "NYQ", "NGM", "PCX", "ASE",
    # Major European
    "LSE", "PAR", "XETRA", "GER", "FRA", "AMS", "MIL", "STO",
    # Others
    "TOR", "ASX", "HKG", "TSE",
]

_EXCHANGE_LABEL = {
    "NMS": "NASDAQ", "NGM": "NASDAQ",
    "NYQ": "NYSE",   "PCX": "NYSE",
    "MCE": "BME (Madrid)", "BME": "BME (Madrid)", "MAD": "BME (Madrid)",
    "LSE": "London",
    "PAR": "Paris",
    "XETRA": "XETRA", "GER": "XETRA",
    "FRA": "Frankfurt",
    "MIL": "Milan",
    "AMS": "Amsterdam",
    "STO": "Stockholm",
}

_NAME_SUFFIXES = re.compile(
    r'\b(inc|plc|n\.?v\.?|s\.?a\.?|corp|ltd|ag|se|co|llc|lp|group)\b\.?$',
    re.IGNORECASE,
)

def _norm_name(name: str) -> str:
    name = name.lower().strip()
    name = _NAME_SUFFIXES.sub("", name).strip().rstrip(",")
    return name


@app.get("/api/search")
async def search_tickers(q: str):
    try:
        results = yf.Search(q)
        quotes = results.quotes or []

        # Build candidate list
        candidates = [
            {
                "symbol": r.get("symbol"),
                "name": r.get("shortname") or r.get("longname") or r.get("symbol"),
                "exchange": r.get("exchange", ""),
                "sector": r.get("sector", ""),
                "industry": r.get("industry", ""),
            }
            for r in quotes
            if r.get("symbol")
        ]

        # Deduplicate by normalised company name, keeping highest-priority exchange
        def _exch_rank(exch: str) -> int:
            try:
                return EXCHANGE_PRIORITY.index(exch)
            except ValueError:
                return len(EXCHANGE_PRIORITY)

        seen: dict[str, dict] = {}
        for c in candidates:
            key = _norm_name(c["name"] or "")
            if key not in seen or _exch_rank(c["exchange"]) < _exch_rank(seen[key]["exchange"]):
                seen[key] = c

        # Sort by exchange priority, then return up to 6
        deduped = sorted(seen.values(), key=lambda c: _exch_rank(c["exchange"]))[:6]

        return [
            {
                **c,
                "exchangeLabel": _EXCHANGE_LABEL.get(c["exchange"], c["exchange"]),
            }
            for c in deduped
        ]
    except Exception:
        return []


class _DividendSeries:
    """Small stand-in so dividend_growth_trend can read a series it did not fetch."""

    def __init__(self, dividends):
        self.dividends = dividends


def _debt_to_ebitda(info, symbol, fresh):
    """Same Debt/EBITDA rule as before: info first, statements only if that is missing."""
    total_debt = safe_float(info.get("totalDebt"))
    ebitda = safe_float(info.get("ebitda"))
    if total_debt is not None and ebitda and ebitda > 0:
        return total_debt / ebitda
    try:
        bs, fin = cached_statements(symbol, fresh=fresh)
        if bs is not None and not getattr(bs, "empty", True):
            for label in ["Total Debt", "Long Term Debt"]:
                if label in bs.index:
                    value = safe_float(bs.loc[label].iloc[0])
                    if value is not None:
                        total_debt = value
                        break
        if fin is not None and not getattr(fin, "empty", True):
            for label in ["EBITDA", "Ebitda"]:
                if label in fin.index:
                    value = safe_float(fin.loc[label].iloc[0])
                    if value is not None:
                        ebitda = value
                        break
        if total_debt is not None and ebitda and ebitda > 0:
            return total_debt / ebitda
    except Exception:
        return None
    return None


def _run_side_by_side(jobs):
    """Run callables on threads and return their values. A failure is None.

    One job stays on this thread. The cache and the Yahoo semaphore are
    already safe to share across threads.
    """
    if len(jobs) <= 1:
        out = {"dividends": None, "cashflow": None}
        if jobs:
            name, fn = jobs[0]
            try:
                out[name] = fn()
            except Exception:
                out[name] = None
        return out

    boxes = {}
    threads = []
    for name, fn in jobs:
        box = {}
        boxes[name] = box

        def run(fn=fn, box=box):
            try:
                box["value"] = fn()
            except Exception:
                box["error"] = True

        thread = threading.Thread(target=run)
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    out = {"dividends": None, "cashflow": None}
    for name, box in boxes.items():
        out[name] = None if box.get("error") else box.get("value")
    return out


def _load_dividend_inputs(symbol, fresh, fetch_cashflow):
    """Dividend history, plus the cash-flow statement when the sector uses it."""
    jobs = [("dividends", lambda: cached_dividends(symbol, fresh=fresh))]
    if fetch_cashflow:
        jobs.append(("cashflow", lambda: cached_cashflow(symbol, fresh=fresh)))
    return _run_side_by_side(jobs)


def _build_analysis(ticker: str, min_yield: float, max_per: float, fresh: bool = False, include_history: bool = True):
    """Shared scoring path for /api/analyze and the watchlist.

    The watchlist skips the price chart and the dividend calendar. Everything
    that feeds the recommendation, the two yields, and the dividend trend is
    the same data and the same functions either way.
    """
    try:
        symbol = str(ticker or "").strip()
        info = cached_info(symbol, fresh=fresh)
        if not info or not info.get("quoteType"):
            raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")

        price = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        if price is None:
            raise HTTPException(status_code=404, detail=f"No price data available for '{ticker}'.")

        debt_to_ebitda = _debt_to_ebitda(info, symbol, fresh)
        dividend_yield = dividend_yield_percent(info)
        pays_dividends = dividend_yield is not None and dividend_yield > 0

        last_dividend_date = None
        price_history = []
        if include_history:
            try:
                last_dividend_date = cached_dividend_date(symbol, fresh=fresh)
            except Exception:
                last_dividend_date = None
            try:
                price_history = cached_price_history(symbol, fresh=fresh)
            except Exception:
                price_history = []

        per_raw = resolved_per(info)
        payout = safe_float(info.get("payoutRatio"))
        ptb = safe_float(info.get("priceToBook"))
        payout_percent = None if payout is None else payout * 100
        sector = info.get("sector") or ""
        industry = info.get("industry") or ""
        # Dividends and the cash-flow statement are independent. Fetching
        # them together keeps the extra statement off the critical path.
        # Banks and insurers skip the statement entirely.
        basis = cash_payout_basis(sector, industry)
        loaded = _load_dividend_inputs(symbol, fresh, fetch_cashflow=basis != "skipped")
        divs = loaded.get("dividends")
        try:
            sustainability = assemble_sustainability(sector, industry, divs, loaded.get("cashflow"))
        except Exception:
            sustainability = empty_sustainability()
        scores = score_metrics(
            sector=sector,
            industry=industry,
            per=per_raw,
            dividend_yield=dividend_yield,
            debt_to_ebitda=debt_to_ebitda,
            price_to_book=ptb,
            payout_percent=payout_percent,
            min_yield=min_yield,
            max_per=max_per,
            fcf_payout=sustainability["fcfPayout"],
            fcf_deficit=sustainability["fcfDeficit"],
            dividend_cut=sustainability["dividendCutRecent"],
        )
        dividend_trend = dividend_growth_trend(_DividendSeries(divs))
        try:
            yield_summary = summarize_dividend_yields(divs, price, dividend_yield)
        except Exception:
            yield_summary = empty_yield_summary()

        full = {
            "companyName": info.get("longName") or info.get("shortName") or symbol.upper(),
            "ticker": symbol.upper(),
            "currentPrice": price,
            "currency": info.get("currency", "USD"),
            "exchange": info.get("exchange", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "metrics": {
                "per": round(per_raw, 2) if per_raw is not None else None,
                "dividendYield": dividend_yield,
                "trailingDividendYield": yield_summary["trailingDividendYield"],
                "yieldComparison": yield_summary["yieldComparison"],
                "payoutRatio": round(payout_percent, 2) if payout_percent is not None else None,
                "priceToBook": round(ptb, 2) if ptb is not None else None,
                "debtToEbitda": round(debt_to_ebitda, 2) if debt_to_ebitda is not None else None,
                "fcfPayout": sustainability["fcfPayout"],
                "fcfPayoutBasis": sustainability["fcfPayoutBasis"],
                "fcfDeficit": sustainability["fcfDeficit"],
                "yearsDividendPaid": sustainability["yearsDividendPaid"],
                "yearsDividendRaised": sustainability["yearsDividendRaised"],
                "dividendCagr5y": sustainability["dividendCagr5y"],
                "dividendCutRecent": sustainability["dividendCutRecent"],
            },
            # Exact inputs score_metrics used. The watchlist stores these so
            # labels can be recomputed when the sliders move. The cash payout
            # and the cut flag are part of that, or a refresh would forget
            # the sustainability warning the moment a slider moves.
            "scoringInputs": {
                "sector": info.get("sector") or "",
                "industry": info.get("industry") or "",
                "per": per_raw,
                "dividendYield": dividend_yield,
                "debtToEbitda": debt_to_ebitda,
                "priceToBook": ptb,
                "payoutRatio": payout_percent,
                "fcfPayout": sustainability["fcfPayout"],
                "fcfDeficit": sustainability["fcfDeficit"],
                "dividendCutRecent": sustainability["dividendCutRecent"],
            },
            "dividendInfo": {
                "paysDividends": pays_dividends,
                "dividendRate": safe_float(info.get("dividendRate")),
                "lastDividendDate": last_dividend_date,
            },
            "priceHistory": price_history,
            "scores": scores,
            "dividendTrend": dividend_trend,
        }
        if include_history:
            return full
        # Every field the watchlist stores and re-scores from when the sliders move.
        return {
            "companyName": full["companyName"],
            "ticker": full["ticker"],
            "sector": full["sector"],
            "industry": full["industry"],
            "metrics": full["metrics"],
            "scoringInputs": full["scoringInputs"],
            "scores": full["scores"],
            "dividendTrend": full["dividendTrend"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _watchlist_row(ticker: str, min_yield: float, max_per: float, fresh: bool = False):
    return _build_analysis(ticker, min_yield, max_per, fresh, include_history=False)


@app.get("/api/analyze/{ticker}")
async def analyze_ticker(
    ticker: str,
    min_yield: Optional[float] = None,
    max_per: Optional[float] = None,
    minYield: Optional[float] = None,
    maxPer: Optional[float] = None,
    fresh: bool = False,
):
    min_yield, max_per = resolve_score_thresholds(min_yield, max_per, minYield, maxPer)
    try:
        return await asyncio.to_thread(_build_analysis, ticker, min_yield, max_per, fresh, True)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/watchlist/{ticker}")
async def watchlist_ticker(
    ticker: str,
    min_yield: Optional[float] = None,
    max_per: Optional[float] = None,
    minYield: Optional[float] = None,
    maxPer: Optional[float] = None,
    fresh: bool = False,
):
    """One watchlist row: the inputs the live recommendation uses, both yields, trend, name and sector."""
    min_yield, max_per = resolve_score_thresholds(min_yield, max_per, minYield, maxPer)
    try:
        return await asyncio.to_thread(_watchlist_row, ticker, min_yield, max_per, fresh)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class WatchlistBatch(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    min_yield: Optional[float] = None
    max_per: Optional[float] = None
    minYield: Optional[float] = None
    maxPer: Optional[float] = None
    fresh: bool = False


def _unique_symbols(symbols) -> list:
    ordered = []
    seen = set()
    for raw in symbols or []:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.upper()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(text)
        if len(ordered) >= MAX_WATCHLIST_BATCH:
            break
    return ordered


def _error_text(exc) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail:
        return detail
    return str(exc)


async def iter_watchlist_rows(symbols, min_yield: float = 4.0, max_per: float = 15.0, fresh: bool = False):
    """Yield watchlist rows as each ticker finishes. Order is completion order."""
    cleaned = _unique_symbols(symbols)
    if not cleaned:
        return
    slot = asyncio.Semaphore(YAHOO_CONCURRENCY)
    queue = asyncio.Queue()

    async def worker(symbol):
        async with slot:
            try:
                data = await asyncio.to_thread(_watchlist_row, symbol, min_yield, max_per, fresh)
                await queue.put({"symbol": symbol, "ok": True, "data": data})
            except HTTPException as exc:
                await queue.put({"symbol": symbol, "ok": False, "error": _error_text(exc)})
            except Exception as exc:
                await queue.put({"symbol": symbol, "ok": False, "error": str(exc)})

    async def produce():
        try:
            await asyncio.gather(*(worker(symbol) for symbol in cleaned))
        finally:
            await queue.put(None)

    producer = asyncio.create_task(produce())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        producer.cancel()
        try:
            await producer
        except asyncio.CancelledError:
            pass


@app.post("/api/watchlist")
async def watchlist_batch(body: WatchlistBatch):
    """Refresh many tickers. Each line of the body is one JSON result, as it finishes."""

    min_yield, max_per = resolve_score_thresholds(
        body.min_yield, body.max_per, body.minYield, body.maxPer,
    )

    async def ndjson():
        async for item in iter_watchlist_rows(body.symbols, min_yield, max_per, body.fresh):
            yield json.dumps(item, separators=(",", ":")) + "\n"

    return StreamingResponse(
        ndjson(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _historical_price_sync(symbol: str, date: str):
    dt = datetime.datetime.strptime(date, "%Y-%m-%d")
    end = dt + datetime.timedelta(days=4)

    def load_history():
        return yf.Ticker(symbol).history(
            start=dt.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
        )

    hist = call_yahoo(load_history)
    if hist is not None and not hist.empty:
        price = round(float(hist["Close"].iloc[0]), 4)
        actual_date = hist.index[0].strftime("%Y-%m-%d")
    else:
        info = cached_info(symbol)
        price = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        actual_date = date
        if price is None:
            raise HTTPException(status_code=404, detail=f"No price data for '{symbol}'")
    info = cached_info(symbol)
    return {
        "symbol": symbol.upper(),
        "date": actual_date,
        "price": price,
        "currency": info.get("currency", "USD"),
    }


@app.get("/api/historical-price")
async def historical_price(symbol: str, date: str):
    try:
        return await asyncio.to_thread(_historical_price_sync, symbol, date)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _historical_yield_sync(symbol: str):
    try:
        info = cached_info(symbol)
        current_yield = dividend_yield_percent(info)

        def load_history():
            return yf.Ticker(symbol).history(period="3y", interval="1mo")

        hist = call_yahoo(load_history)
        if hist is None or hist.empty:
            return {"symbol": symbol.upper(), "avgYield3y": None, "currentYield": current_yield, "context": "unavailable"}

        divs = cached_dividends(symbol)
        current_year = datetime.datetime.now().year
        yearly_yields = []

        for year in range(current_year - 3, current_year):
            year_prices = hist[hist.index.map(lambda ts: ts.year) == year]["Close"]
            if year_prices.empty:
                continue
            avg_price = float(year_prices.mean())
            if avg_price <= 0:
                continue

            annual_div = 0.0
            if divs is not None and len(divs) > 0:
                annual_div = float(divs[divs.index.map(lambda ts: ts.year) == year].sum())

            if annual_div > 0:
                yearly_yields.append((annual_div / avg_price) * 100)

        if not yearly_yields:
            return {"symbol": symbol.upper(), "avgYield3y": None, "currentYield": current_yield, "context": "unavailable"}

        avg_yield_3y = round(sum(yearly_yields) / len(yearly_yields), 2)

        if current_yield is None:
            context = "unavailable"
        elif current_yield > avg_yield_3y * 1.10:
            context = "above_average"
        elif current_yield < avg_yield_3y * 0.90:
            context = "below_average"
        else:
            context = "at_average"

        return {
            "symbol":     symbol.upper(),
            "avgYield3y": avg_yield_3y,
            "currentYield": current_yield,
            "context":    context,
        }
    except Exception:
        return {"symbol": symbol.upper(), "avgYield3y": None, "currentYield": None, "context": "unavailable"}


@app.get("/api/historical-yield")
async def historical_yield_endpoint(symbol: str):
    return await asyncio.to_thread(_historical_yield_sync, symbol)


# Share-count dust below this is treated as zero (float noise, not a real lot).
_SHARE_EPS = 1e-6


def normalize_transactions(transactions) -> list:
    """Return (YYYY-MM-DD, signed shares) pairs. Buys are positive, sells negative.

    A missing side/type is a buy, so portfolio records saved before sales
    existed still work. Non-positive share counts are ignored.
    """
    normalized = []
    if not transactions:
        return normalized
    for item in transactions:
        if not isinstance(item, dict):
            continue
        date_str = str(item.get("date") or "").strip()[:10]
        try:
            datetime.datetime.strptime(date_str, "%Y-%m-%d")
            shares = float(item.get("shares") or 0)
        except (TypeError, ValueError):
            continue
        if shares <= 0:
            continue
        side = str(item.get("side") or item.get("type") or "buy").lower()
        signed = -shares if side in ("sell", "sale") else shares
        normalized.append((date_str, signed))
    return normalized


# A note is shown when either gap is exceeded: more than 1 percentage
# point, or more than 20% of the larger yield. Landing exactly on one
# threshold does not count for that threshold. A gap of exactly 1.0 point
# on a small yield can still qualify through the 20% rule.
YIELD_GAP_ABS_POINTS = 1.0
YIELD_GAP_REL = 0.20

# One payment is a possible special dividend when it is the only payment in
# the trailing window at least this many times the median of the others.
# A repeated higher amount is a raise, not a special.
SPECIAL_DIVIDEND_MULTIPLE = 2.0
TRAILING_WINDOW_DAYS = 365


def empty_yield_summary():
    return {
        "trailingDividendYield": None,
        "yieldComparison": {
            "material": False,
            "direction": None,
            "possibleSpecialDividend": False,
        },
    }


def _dividend_payments(divs):
    """(ex-date, amount) rows from a yfinance dividends series or a mapping.

    Non-positive and non-numeric amounts are skipped. The date is the
    exchange wall-clock ex-date, same rule as the dividend ledger.
    """
    if divs is None:
        return []
    try:
        if len(divs) == 0:
            return []
    except TypeError:
        return []
    items = divs.items() if hasattr(divs, "items") else divs
    payments = []
    for ts, amount in items:
        value = safe_float(amount)
        if value is None or value <= 0:
            continue
        try:
            ex_date = _ex_dividend_date(ts)
        except (TypeError, ValueError):
            continue
        payments.append((ex_date, value))
    return payments


def trailing_window_payments(divs, as_of=None, window_days=TRAILING_WINDOW_DAYS):
    """Payments with an ex-date in (as_of - window_days, as_of].

    A dividend dated exactly `window_days` earlier is outside the window.
    `as_of` defaults to today. This is the trailing 12 months as 365 days,
    not Yahoo's trailingAnnualDividendYield.
    """
    if isinstance(as_of, datetime.datetime):
        as_of = as_of.date()
    as_of = as_of or datetime.date.today()
    start = as_of - datetime.timedelta(days=window_days)
    selected = [
        (ex_date, amount)
        for ex_date, amount in _dividend_payments(divs)
        if start < ex_date <= as_of
    ]
    selected.sort(key=lambda item: item[0])
    return selected


def _same_dividend_amount(amount, other):
    """True when two payments are the same amount, allowing a 1% tick of noise."""
    scale = max(abs(other), abs(amount), 1e-9)
    return abs(amount - other) <= 0.01 * scale


def _amounts_without_dust(amounts):
    """Drop token payments that are tiny beside the regular dividend.

    A 0.005 adjustment next to ordinary payments pulls the baseline down
    and can make a normal larger instalment look like a special. With
    fewer than three payments the list is left as-is, so one regular
    payment plus one much larger one can still be a special.
    """
    if len(amounts) < 3:
        return amounts
    ordered = sorted(amounts)
    upper = ordered[len(ordered) // 2:]
    scale = statistics.median(upper)
    if scale <= 0:
        return amounts
    kept = [amount for amount in amounts if amount >= 0.15 * scale]
    return kept if len(kept) >= 2 else amounts


def possible_special_dividend(payments) -> bool:
    """True when a single trailing-window payment is unusually large.

    The largest amount has to be alone (a repeated new amount is a raise or
    the old rate in a cut) and at least SPECIAL_DIVIDEND_MULTIPLE times the
    median of the other payments. Two payments are enough: one regular and
    one much larger. Tiny payments are ignored when there is a clearer
    regular dividend beside them.
    """
    amounts = _amounts_without_dust([amount for _, amount in payments if amount > 0])
    if len(amounts) < 2:
        return False
    largest = max(amounts)
    peers = [amount for amount in amounts if _same_dividend_amount(amount, largest)]
    if len(peers) != 1:
        return False
    others = [amount for amount in amounts if not _same_dividend_amount(amount, largest)]
    if not others:
        return False
    baseline = statistics.median(others)
    if baseline <= 0:
        return False
    return largest >= SPECIAL_DIVIDEND_MULTIPLE * baseline


# A year-over-year change inside this band is flat. Split-adjusted
# dividends often differ by rounding, and that must not look like a cut
# or a raise. Exactly 1% is still flat.
DIVIDEND_FLAT_BAND = 0.01
# How many complete years back a cut still warns.
RECENT_DIVIDEND_CUT_YEARS = 5
DIVIDEND_CAGR_YEARS = 5

_DIVIDEND_PAID_LABELS = (
    "Common Stock Dividend Paid",
    "Cash Dividends Paid",
    "Common Stock Dividends Paid",
    "Dividends Paid",
)
_FCF_LABELS = ("Free Cash Flow",)
_OPERATING_CASH_LABELS = (
    "Operating Cash Flow",
    "Cash Flow From Continuing Operating Activities",
    "Total Cash From Operating Activities",
)
_CAPEX_LABELS = (
    "Capital Expenditure",
    "Capital Expenditure Reported",
    "Purchase Of PPE",
)
_NET_INCOME_LABELS = (
    "Net Income From Continuing Operations",
    "Net Income",
    "Net Income Common Stockholders",
)
_DEPRECIATION_LABELS = (
    "Depreciation And Amortization",
    "Depreciation Amortization Depletion",
    "Depreciation",
)


def empty_sustainability():
    return {
        "fcfPayout": None,
        "fcfPayoutBasis": None,
        "fcfDeficit": False,
        "yearsDividendPaid": None,
        "yearsDividendRaised": None,
        "dividendCagr5y": None,
        "dividendCutRecent": False,
    }


def _column_time(column):
    if hasattr(column, "to_pydatetime"):
        try:
            value = column.to_pydatetime()
            return value.replace(tzinfo=None)
        except Exception:
            pass
    if isinstance(column, datetime.datetime):
        return column.replace(tzinfo=None)
    if isinstance(column, datetime.date):
        return datetime.datetime.combine(column, datetime.time.min)
    try:
        return datetime.datetime.strptime(str(column)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return datetime.datetime.min


def _statement_columns(frame):
    try:
        columns = list(frame.columns)
    except Exception:
        return []
    return sorted(columns, key=_column_time, reverse=True)


def _statement_value(frame, labels, column):
    if frame is None or getattr(frame, "empty", True):
        return None
    index = getattr(frame, "index", ())
    for label in labels:
        if label not in index:
            continue
        try:
            raw = frame.loc[label, column]
        except Exception:
            continue
        # Duplicate row labels come back as a Series. Use the first number.
        if hasattr(raw, "iloc"):
            candidates = []
            try:
                candidates = [raw.iloc[i] for i in range(len(raw))]
            except Exception:
                candidates = []
        else:
            candidates = [raw]
        for item in candidates:
            value = safe_float(item)
            if value is not None:
                return value
    return None


def _dividends_paid(frame, column):
    value = _statement_value(frame, _DIVIDEND_PAID_LABELS, column)
    if value is None:
        return None
    return abs(value)


def _free_cash_flow(frame, column):
    direct = _statement_value(frame, _FCF_LABELS, column)
    if direct is not None:
        return direct
    operating = _statement_value(frame, _OPERATING_CASH_LABELS, column)
    capex = _statement_value(frame, _CAPEX_LABELS, column)
    if operating is None or capex is None:
        return None
    # Capex is usually a negative outflow. A positive figure is still a cost.
    return operating - abs(capex)


def _ffo_like(frame, column):
    """Simple REIT funds from operations: net income plus depreciation.

    Gains on property sales are not adjusted. On the cash-flow statement
    those lines do not have a reliable sign, and a wrong sign would create
    a false warning. When either input is missing the result is None.
    """
    net = _statement_value(frame, _NET_INCOME_LABELS, column)
    depreciation = _statement_value(frame, _DEPRECIATION_LABELS, column)
    if net is None or depreciation is None:
        return None
    return net + abs(depreciation)


def cash_payout_ratio(dividends_paid, cash_generated):
    """Return (percent or None, deficit).

    deficit is True when dividends were paid and the cash figure is not
    positive. Missing inputs are (None, False) and never raise.
    """
    dividends = safe_float(dividends_paid)
    cash = safe_float(cash_generated)
    if dividends is None or cash is None:
        return None, False
    dividends = abs(dividends)
    if dividends == 0:
        return 0.0, False
    if cash <= 0:
        return None, True
    return round((dividends / cash) * 100, 2), False


def cash_flow_payout(frame, basis):
    """Payout from the latest annual column that has both pieces.

    `basis` is "fcf" or "ffo". A negative cash figure is kept: it is a
    deficit, not a reason to fall back to an older healthy year.
    """
    result = {"fcfPayout": None, "fcfPayoutBasis": basis, "fcfDeficit": False}
    if basis not in ("fcf", "ffo"):
        result["fcfPayoutBasis"] = None
        return result
    if frame is None or getattr(frame, "empty", True):
        return result
    measure = _free_cash_flow if basis == "fcf" else _ffo_like
    for column in _statement_columns(frame):
        dividends = _dividends_paid(frame, column)
        if dividends is None:
            continue
        cash = measure(frame, column)
        if cash is None:
            continue
        payout, deficit = cash_payout_ratio(dividends, cash)
        result["fcfPayout"] = payout
        result["fcfDeficit"] = deficit
        return result
    return result


def _as_of_date(as_of):
    if as_of is None:
        return datetime.date.today()
    if isinstance(as_of, datetime.datetime):
        return as_of.date()
    if isinstance(as_of, datetime.date):
        return as_of
    return datetime.datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date()


# Gap (days) that best matches each payment frequency. Used to tell a
# monthly payer from a quarterly one, and to spot an extra payment that
# sits between two regular dates.
_FREQUENCY_PERIODS = ((12, 30), (4, 91), (2, 182), (1, 365))


def _infer_frequency(gaps):
    """How many regular payments a year, from the gaps between them.

    A special dividend splits one normal gap into two short ones. Those
    short gaps must not make a monthly payer look weekly or a quarterly
    payer look monthly. The closest normal step wins.
    """
    usable = [gap for gap in gaps if gap is not None and gap >= 0]
    if not usable:
        return 1
    median_gap = statistics.median(usable)
    best_freq = 1
    best_key = (-1.0, -10**9)
    for freq, period in _FREQUENCY_PERIODS:
        score = 0.0
        for gap in usable:
            if abs(gap - period) <= period * 0.40:
                score += 2
            elif period >= 60 and abs(gap - period / 2.0) <= period * 0.30:
                score += 1
        key = (score, -abs(period - median_gap))
        if key > best_key:
            best_key = key
            best_freq = freq
    return best_freq


def _period_days(frequency):
    for freq, period in _FREQUENCY_PERIODS:
        if freq == frequency:
            return period
    return 365


def _without_dust(payments):
    """Drop token amounts that are tiny beside the regular dividend.

    A 0.01 adjustment next to a 2.00 dividend must not become the
    year-end rate. With fewer than three payments the list is left
    alone, so one regular payment and one much larger one can still
    be told apart later.
    """
    if len(payments) < 3:
        return payments
    ordered = sorted(amount for _, amount in payments)
    upper = ordered[len(ordered) // 2:]
    scale = statistics.median(upper)
    if scale <= 0:
        return payments
    kept = [item for item in payments if item[1] >= 0.15 * scale]
    return kept if len(kept) >= 2 else payments


def _split_regular_payments(payments):
    """Return (regular payments, typical gap in days).

    An extra payment crammed against the regular date is a special,
    whether it is larger (a supplemental) or smaller (a stub). A repeated
    higher amount is a new regular dividend, not a special. A one-off
    payment at least twice the recent regular amount is a special when
    the next payment goes back to the old amount. Amounts are already
    split-adjusted.
    """
    payments = sorted(_without_dust(list(payments)), key=lambda item: item[0])
    if len(payments) < 2:
        return payments, 365
    gaps = [(payments[i][0] - payments[i - 1][0]).days for i in range(1, len(payments))]
    period = _period_days(_infer_frequency(gaps))
    short = 0.70 * period
    clusters = []
    cluster = [0]
    for index in range(1, len(payments)):
        gap = (payments[index][0] - payments[index - 1][0]).days
        if 0 <= gap < short:
            cluster.append(index)
        else:
            if len(cluster) > 1:
                clusters.append(cluster)
            cluster = [index]
    if len(cluster) > 1:
        clusters.append(cluster)

    in_cluster = {index for group in clusters for index in group}
    special = set()
    for group in clusters:
        before = [payments[index][1] for index in range(group[0]) if index not in special]
        # The recent regular amount, not the median of the whole history.
        # A dividend that has been raised for years would otherwise look
        # nothing like its old payments, and the supplemental would win.
        before = before[-6:]
        if not before:
            before = [payments[index][1] for index in range(len(payments)) if index not in in_cluster]
            before = before[:6]
        baseline = statistics.median(before) if before else statistics.median(payments[index][1] for index in group)
        matched = []
        for index in group:
            amount = payments[index][1]
            # 15% either way is still the regular dividend (a raise or a
            # small cut that happened to fall near another payment). A
            # supplemental like 0.30 beside a 0.25 monthly is outside this.
            if baseline > 0 and 0.85 * baseline <= amount <= 1.15 * baseline:
                matched.append(index)
        if matched:
            for index in group:
                if index not in matched:
                    special.add(index)
            continue
        # Nothing in the cluster looks like the regular dividend. Keep the
        # closest amount and treat the rest as specials.
        keeper = min(group, key=lambda index: abs(payments[index][1] - baseline))
        for index in group:
            if index != keeper:
                special.add(index)
    regular = [payments[index] for index in range(len(payments)) if index not in special]
    return _drop_reverting_spikes(regular), period


def _drop_reverting_spikes(regular):
    """Drop a single payment that is at least twice the recent rate and then reverts.

    The next payment has to come back, so a dividend that really doubles
    and stays there is a raise. The last payment in the history has no
    successor, so it is kept.
    """
    if len(regular) < 3:
        return regular
    drop = set()
    for index in range(len(regular)):
        amount = regular[index][1]
        previous = [regular[other][1] for other in range(max(0, index - 4), index) if other not in drop]
        if not previous:
            continue
        baseline = statistics.median(previous)
        if baseline <= 0 or amount < SPECIAL_DIVIDEND_MULTIPLE * baseline:
            continue
        nxt = None
        for other in range(index + 1, len(regular)):
            if other not in drop:
                nxt = regular[other][1]
                break
        if nxt is None:
            continue
        if nxt < SPECIAL_DIVIDEND_MULTIPLE * baseline and nxt <= baseline * 1.5:
            drop.add(index)
    return [item for index, item in enumerate(regular) if index not in drop]


def _local_frequency(regular, cutoff):
    """Payment frequency from the gaps just before `cutoff`."""
    dates = [ex_date for ex_date, _ in regular if ex_date <= cutoff]
    if len(dates) < 2:
        return 1
    gaps = [(dates[index] - dates[index - 1]).days for index in range(1, len(dates))]
    return _infer_frequency(gaps[-4:])


def _rate_at_year_end(regular, year):
    """Annualized regular dividend as of the end of `year`.

    One full cycle of regular payments on or before 31 Dec: the last 12
    for a monthly payer, the last 4 for a quarterly payer, and so on.
    When every payment in that cycle is the same amount, this is the
    year-end rate times the frequency. A December payment that is dated
    in January still sits in the cycle of the following year, and the
    year it left keeps a full cycle by reaching back one payment. It is
    not an 11-payment year and a 13-payment year.
    """
    cutoff = datetime.date(year, 12, 31)
    prior = [(ex_date, amount) for ex_date, amount in regular if ex_date <= cutoff]
    if not prior:
        return None
    frequency = _local_frequency(regular, cutoff)
    tail = prior[-frequency:]
    if len(tail) < frequency:
        return prior[-1][1] * frequency
    return sum(amount for _, amount in tail)


def _years_touched(payments, as_of, period_days):
    """Calendar years through the last complete year that count as paid.

    A payment dated in the year counts. So does a year the ex-date merely
    stepped across, when the gap from the previous payment to the next one
    is still a normal interval (an annual dividend moving from late
    December to early January). A gap of more than one and a half
    intervals is a year that was actually skipped.
    """
    latest = as_of.year - 1
    dated = sorted((ex_date, amount) for ex_date, amount in payments if amount > 0 and ex_date <= as_of)
    years = {ex_date.year for ex_date, _ in dated if ex_date.year <= latest}
    limit = max(period_days, 1) * 1.5
    for index in range(1, len(dated)):
        gap = (dated[index][0] - dated[index - 1][0]).days
        if gap > limit:
            continue
        year = dated[index - 1][0].year + 1
        while year < dated[index][0].year and year <= latest:
            years.add(year)
            year += 1
    return years


def _rates_by_year(divs, as_of):
    """Map each complete year that has a regular payment to its year-end rate."""
    as_of = _as_of_date(as_of)
    payments = [item for item in _dividend_payments(divs) if item[0] <= as_of]
    regular, _period = _split_regular_payments(payments)
    latest = as_of.year - 1
    rates = {}
    years = {ex_date.year for ex_date, _ in regular if ex_date.year <= latest}
    for year in years:
        rate = _rate_at_year_end(regular, year)
        if rate is not None and rate > 0:
            rates[year] = rate
    return rates


def _annual_dividends(divs, as_of):
    """Per complete year: cash paid (specials included) and the regular rate.

    `regular` is the year-end annualized rate, not the sum of the payments
    whose ex-dates happened to fall in that calendar year.
    """
    as_of = _as_of_date(as_of)
    payments = [item for item in _dividend_payments(divs) if item[0] <= as_of and item[0].year < as_of.year]
    paid = {}
    for ex_date, amount in payments:
        paid[ex_date.year] = paid.get(ex_date.year, 0.0) + amount
    rates = _rates_by_year(divs, as_of)
    annual = {}
    for year in set(paid) | set(rates):
        annual[year] = {
            "paid": paid.get(year, 0.0),
            "regular": rates.get(year, 0.0),
        }
    return annual


def _dividend_direction(current, previous):
    current = safe_float(current)
    previous = safe_float(previous)
    if current is None or previous is None or previous <= 0:
        return "unknown"
    ratio = current / previous
    if ratio > 1 + DIVIDEND_FLAT_BAND:
        return "raised"
    if ratio < 1 - DIVIDEND_FLAT_BAND:
        return "cut"
    return "flat"


def _unknown_dividend_history():
    return {
        "yearsDividendPaid": None,
        "yearsDividendRaised": None,
        "dividendCagr5y": None,
        "dividendCutRecent": False,
    }


def dividend_history_metrics(divs, as_of=None):
    """Consecutive years paid, consecutive years raised, and 5-year CAGR.

    Counts end at the last complete calendar year. `divs` of None means
    the history could not be read: every figure is n/a and nothing warns.
    An empty history is a real zero. Raises, cuts and the CAGR use the
    regular dividend at each year end (one full payment cycle), not the
    sum of the ex-dates that fell in the calendar year. A cut is a drop
    of more than 1% in one of the last five complete years, or a stop:
    the dividend was paid and then the latest complete years are empty.
    A hole with payments on both sides is not a cut, and years before
    the history starts are not cuts either.
    """
    if divs is None:
        return _unknown_dividend_history()
    try:
        as_of = _as_of_date(as_of)
        payments = [item for item in _dividend_payments(divs) if item[0] <= as_of]
        _regular, period = _split_regular_payments(payments)
        paid_set = _years_touched(payments, as_of, period)
        rates = _rates_by_year(divs, as_of)
    except Exception:
        return _unknown_dividend_history()

    latest = as_of.year - 1
    paid_years = 0
    year = latest
    while paid_years < 120 and year in paid_set:
        paid_years += 1
        year -= 1

    raised_years = 0
    year = latest
    while raised_years < 120:
        if year not in rates or (year - 1) not in rates:
            break
        if _dividend_direction(rates[year], rates[year - 1]) != "raised":
            break
        raised_years += 1
        year -= 1

    cut = False
    oldest = min(paid_set) if paid_set else None
    for offset in range(RECENT_DIVIDEND_CUT_YEARS):
        year = latest - offset
        if oldest is None or year < oldest:
            continue
        if year in rates and (year - 1) in rates:
            if _dividend_direction(rates[year], rates[year - 1]) == "cut":
                cut = True
                break
            continue
        # An empty year with payments on both sides can be a hole in the
        # history, so it is not a cut. A stop is an empty year at the end,
        # after a year that was paid.
        if year not in paid_set and (year - 1) in paid_set:
            later_paid = False
            for earlier in range(offset):
                if (latest - earlier) in paid_set:
                    later_paid = True
                    break
            if not later_paid:
                cut = True
                break

    cagr = None
    end = rates.get(latest)
    start = rates.get(latest - DIVIDEND_CAGR_YEARS)
    if end and start and start > 0 and end > 0:
        growth = (end / start) ** (1.0 / DIVIDEND_CAGR_YEARS) - 1.0
        cagr = round(growth * 100, 2)

    return {
        "yearsDividendPaid": paid_years,
        "yearsDividendRaised": raised_years,
        "dividendCagr5y": cagr,
        "dividendCutRecent": cut,
    }


def assemble_sustainability(sector, industry, divs, cashflow):
    """History metrics plus the sector-aware cash payout. Never raises."""
    block = empty_sustainability()
    try:
        block.update(dividend_history_metrics(divs))
    except Exception:
        pass
    try:
        basis = cash_payout_basis(sector, industry)
    except Exception:
        basis = "fcf"
    block["fcfPayoutBasis"] = basis
    if basis == "skipped":
        block["fcfPayout"] = None
        block["fcfDeficit"] = False
        return block
    try:
        parsed = cash_flow_payout(cashflow, basis)
    except Exception:
        return block
    block["fcfPayout"] = parsed.get("fcfPayout")
    block["fcfDeficit"] = parsed.get("fcfDeficit") is True
    if parsed.get("fcfPayoutBasis"):
        block["fcfPayoutBasis"] = parsed["fcfPayoutBasis"]
    return block


def yields_differ_materially(forward_yield, trailing_yield) -> bool:
    """True when the two yields are far enough apart to be worth a note.

    Either gap qualifies: more than YIELD_GAP_ABS_POINTS (1 percentage
    point), or more than YIELD_GAP_REL (20%) of the larger yield. Exactly
    1.0 point does not by itself qualify, and exactly 20% does not either,
    but a 1.0 point gap on a yield below 5% still qualifies on the relative
    rule. A missing yield never qualifies.
    """
    forward = safe_float(forward_yield)
    trailing = safe_float(trailing_yield)
    if forward is None or trailing is None:
        return False
    diff = abs(forward - trailing)
    larger = max(abs(forward), abs(trailing))
    if larger <= 0:
        return False
    return diff > YIELD_GAP_ABS_POINTS or (diff / larger) > YIELD_GAP_REL


def summarize_dividend_yields(divs, current_price, forward_yield, as_of=None) -> dict:
    """Trailing yield from dividend history, plus the gap versus forward.

    Trailing yield = sum of dividends with ex-dates in the last 365 days
    / current price * 100. None when that sum is empty or the price is
    missing. `forward_yield` is the figure already shown today
    (dividendRate / price). Scoring does not read this result.
    """
    summary = empty_yield_summary()
    payments = trailing_window_payments(divs, as_of=as_of)
    price = safe_float(current_price)
    if payments and price is not None and price > 0:
        total = sum(amount for _, amount in payments)
        summary["trailingDividendYield"] = round((total / price) * 100, 2)
    trailing = summary["trailingDividendYield"]
    forward = safe_float(forward_yield)
    material = yields_differ_materially(forward, trailing)
    direction = None
    if material:
        direction = "forward_higher" if forward > trailing else "trailing_higher"
    summary["yieldComparison"] = {
        "material": material,
        "direction": direction,
        "possibleSpecialDividend": possible_special_dividend(payments),
    }
    return summary


def _ex_dividend_date(ts):
    """Calendar date of a yfinance dividend timestamp.

    Ticker.dividends is indexed by the ex-dividend date (market open in the
    exchange timezone, e.g. 09:30 America/New_York). Use that wall-clock date,
    not a UTC conversion.
    """
    if isinstance(ts, datetime.datetime):
        return ts.date()
    if isinstance(ts, datetime.date):
        return ts
    if hasattr(ts, "date"):
        return ts.date()
    return datetime.datetime.strptime(str(ts)[:10], "%Y-%m-%d").date()


def shares_held_before_ex_date(transactions, ex_date) -> float:
    """Shares eligible for the dividend whose ex-dividend date is ex_date.

    You receive a dividend only if you held the shares before the ex-dividend
    date. A purchase on the ex-date does not qualify. A sale on the ex-date
    still does, because those shares were held at the start of that day.
    """
    ex_str = _ex_dividend_date(ex_date).isoformat()
    total = 0.0
    for date_str, signed in transactions:
        if date_str < ex_str:
            total += signed
    return total if total > _SHARE_EPS else 0.0


def calculate_dividends_received(divs, transactions) -> list:
    """Per-payment amounts using shares held before each ex-dividend date."""
    if divs is None or len(divs) == 0:
        return []
    items = divs.items() if hasattr(divs, "items") else divs
    result = []
    for ts, amount_per_share in items:
        held = shares_held_before_ex_date(transactions, ts)
        if held <= _SHARE_EPS:
            continue
        per_share = float(amount_per_share)
        ex_date = _ex_dividend_date(ts)
        result.append({
            "date": ex_date.strftime("%Y-%m-%d"),
            "amountPerShare": round(per_share, 4),
            "shares": round(held, 4),
            "totalAmount": round(per_share * held, 2),
        })
    return result


@app.get("/api/dividends-received")
async def dividends_received_endpoint(
    symbol: str,
    transactions: str = "",
    from_date: str = "",
    shares: float = 0,
):
    """Dividends actually received for one symbol.

    `transactions` is a JSON list of {date, shares, side} with side "buy" or
    "sell". Dates are ex-dividend dates from yfinance. The legacy
    `from_date` + `shares` query (a single buy) is still accepted.
    """
    try:
        parsed = []
        if transactions:
            loaded = json.loads(transactions)
            if isinstance(loaded, list):
                parsed = loaded
        elif from_date and shares > 0:
            parsed = [{"date": from_date, "shares": shares, "side": "buy"}]

        normalized = normalize_transactions(parsed)
        if not normalized:
            return {"symbol": symbol.upper(), "dividends": [], "totalReceived": 0.0, "currency": "USD"}

        def load_inputs():
            info = cached_info(symbol) or {}
            divs = cached_dividends(symbol)
            return info, divs

        info, divs = await asyncio.to_thread(load_inputs)
        currency = info.get("currency", "USD") if isinstance(info, dict) else "USD"
        result_divs = calculate_dividends_received(divs, normalized)
        total_received = round(sum(d["totalAmount"] for d in result_divs), 2)
        return {
            "symbol": symbol.upper(),
            "dividends": result_divs,
            "totalReceived": total_received,
            "currency": currency,
        }
    except Exception:
        return {"symbol": symbol.upper(), "dividends": [], "totalReceived": 0.0, "currency": "USD"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")

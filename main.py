from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from typing import Optional
import yfinance as yf
import math
import datetime
import json
import re
import statistics

app = FastAPI()


def safe_float(value):
    if value is None:
        return None
    try:
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


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
) -> dict:
    """Score already-resolved metrics. payout_percent is on a 0–100 scale.

    The browser ports this function (static/scoring.js) so a watchlist row
    can be re-labeled from stored metrics when the yield or P/E slider moves,
    without calling Yahoo again.
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
        per_score = "buy" if per < max_per else ("neutral" if per <= 20 else "expensive")

    # dividend_yield is the forward yield. REIT "buy" is y > 5; every other
    # profile uses min_yield (default 4). The trailing 12-month yield is
    # display-only and does not change the recommendation.
    if dividend_yield is None:
        yield_score = "none"
    elif profile == "reit":
        yield_score = "buy" if dividend_yield > 5 else ("neutral" if dividend_yield >= 3 else "low")
    else:
        yield_score = "buy" if dividend_yield > min_yield else ("neutral" if dividend_yield >= 2 else "low")

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

    return {
        "perScore":              per_score,
        "yieldScore":            yield_score,
        "debtScore":             debt_score,
        "bookScore":             book_score,
        "payoutScore":           payout_score,
        "overallRecommendation": overall,
        "sectorProfile":         profile,
        "sectorNote":            _SECTOR_NOTES.get(profile),
    }


def score_stock(info: dict, debt_to_ebitda, min_yield: float = 4.0, max_per: float = 15.0) -> dict:
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
    )


def dividend_growth_trend(stock) -> str:
    try:
        divs = stock.dividends
        if divs is None or len(divs) == 0:
            return "insufficient_data"

        current_year = datetime.datetime.now().year
        # Group by year using lambda to avoid timezone issues; exclude current partial year
        annual = divs.groupby(lambda ts: ts.year).sum()
        annual = annual[(annual.index >= current_year - 5) & (annual.index < current_year)]

        if len(annual) < 2:
            return "insufficient_data"

        values = annual.tail(3).tolist()

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


@app.get("/api/analyze/{ticker}")
async def analyze_ticker(
    ticker: str,
    min_yield: Optional[float] = None,
    max_per: Optional[float] = None,
    minYield: Optional[float] = None,
    maxPer: Optional[float] = None,
):
    min_yield, max_per = resolve_score_thresholds(min_yield, max_per, minYield, maxPer)
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or not info.get("quoteType"):
            raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")

        price = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        if price is None:
            raise HTTPException(status_code=404, detail=f"No price data available for '{ticker}'.")

        # Debt/EBITDA — try info dict first, fall back to financial statements
        debt_to_ebitda = None
        total_debt = safe_float(info.get("totalDebt"))
        ebitda = safe_float(info.get("ebitda"))
        if total_debt is not None and ebitda and ebitda > 0:
            debt_to_ebitda = total_debt / ebitda
        else:
            try:
                bs = stock.balance_sheet
                fin = stock.financials
                if bs is not None and not bs.empty:
                    for label in ["Total Debt", "Long Term Debt"]:
                        if label in bs.index:
                            v = safe_float(bs.loc[label].iloc[0])
                            if v is not None:
                                total_debt = v
                                break
                if fin is not None and not fin.empty:
                    for label in ["EBITDA", "Ebitda"]:
                        if label in fin.index:
                            v = safe_float(fin.loc[label].iloc[0])
                            if v is not None:
                                ebitda = v
                                break
                if total_debt is not None and ebitda and ebitda > 0:
                    debt_to_ebitda = total_debt / ebitda
            except Exception:
                pass

        dividend_yield = dividend_yield_percent(info)
        pays_dividends = dividend_yield is not None and dividend_yield > 0

        last_dividend_date = None
        try:
            cal = stock.calendar
            if isinstance(cal, dict):
                v = cal.get("Dividend Date")
                if v is not None:
                    last_dividend_date = str(v)
            elif hasattr(cal, "index") and "Dividend Date" in cal.index:
                last_dividend_date = str(cal.loc["Dividend Date"].iloc[0])
        except Exception:
            pass

        price_history = []
        try:
            hist = stock.history(period="1y", interval="1wk")
            if hist is not None and not hist.empty:
                for ts, row in hist.iterrows():
                    price_history.append({
                        "date": ts.strftime("%Y-%m-%d"),
                        "close": round(float(row["Close"]), 2),
                    })
        except Exception:
            pass

        per_raw = resolved_per(info)
        payout = safe_float(info.get("payoutRatio"))
        ptb = safe_float(info.get("priceToBook"))
        payout_percent = None if payout is None else payout * 100
        scores = score_metrics(
            sector=info.get("sector") or "",
            industry=info.get("industry") or "",
            per=per_raw,
            dividend_yield=dividend_yield,
            debt_to_ebitda=debt_to_ebitda,
            price_to_book=ptb,
            payout_percent=payout_percent,
            min_yield=min_yield,
            max_per=max_per,
        )
        dividend_trend = dividend_growth_trend(stock)
        try:
            yield_summary = summarize_dividend_yields(
                stock.dividends,
                price,
                dividend_yield,
            )
        except Exception:
            yield_summary = empty_yield_summary()

        return {
            "companyName": info.get("longName") or info.get("shortName") or ticker.upper(),
            "ticker": ticker.upper(),
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
            },
            # Exact inputs score_metrics used. The watchlist stores these so
            # labels can be recomputed when the sliders move.
            "scoringInputs": {
                "sector": info.get("sector") or "",
                "industry": info.get("industry") or "",
                "per": per_raw,
                "dividendYield": dividend_yield,
                "debtToEbitda": debt_to_ebitda,
                "priceToBook": ptb,
                "payoutRatio": payout_percent,
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/historical-price")
async def historical_price(symbol: str, date: str):
    try:
        stock = yf.Ticker(symbol)
        dt = datetime.datetime.strptime(date, "%Y-%m-%d")
        end = dt + datetime.timedelta(days=4)
        hist = stock.history(
            start=dt.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
        )
        if hist is not None and not hist.empty:
            price = round(float(hist["Close"].iloc[0]), 4)
            actual_date = hist.index[0].strftime("%Y-%m-%d")
        else:
            info = stock.info
            price = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
            actual_date = date
            if price is None:
                raise HTTPException(status_code=404, detail=f"No price data for '{symbol}'")
        info = stock.info
        return {
            "symbol": symbol.upper(),
            "date": actual_date,
            "price": price,
            "currency": info.get("currency", "USD"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/historical-yield")
async def historical_yield_endpoint(symbol: str):
    try:
        stock = yf.Ticker(symbol)
        info  = stock.info

        dividend_rate_hy = safe_float(info.get("dividendRate")) or safe_float(info.get("lastDividendValue"))
        current_price_hy = safe_float(info.get("currentPrice")) or safe_float(info.get("regularMarketPrice"))
        if dividend_rate_hy and current_price_hy and current_price_hy > 0:
            current_yield = round((dividend_rate_hy / current_price_hy) * 100, 2)
        else:
            current_yield_raw = safe_float(info.get("dividendYield", None))
            if current_yield_raw is None or current_yield_raw <= 0:
                current_yield = None
            elif current_yield_raw < 0.50:
                current_yield = round(current_yield_raw * 100, 2)
            elif current_yield_raw > 30:
                current_yield = None
            else:
                current_yield = round(current_yield_raw, 2)

        hist = stock.history(period="3y", interval="1mo")
        if hist is None or hist.empty:
            return {"symbol": symbol.upper(), "avgYield3y": None, "currentYield": current_yield, "context": "unavailable"}

        divs = stock.dividends
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

        stock = yf.Ticker(symbol)
        info = stock.info or {}
        currency = info.get("currency", "USD") if isinstance(info, dict) else "USD"
        result_divs = calculate_dividends_received(stock.dividends, normalized)
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

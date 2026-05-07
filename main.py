from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
import yfinance as yf
import math
import datetime
import re

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
    sec = sector.lower()
    ind = industry.lower()
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
    if any(k in ind for k in ["conglomerate", "holding", "diversified"]):
        return "holding"
    return "default"


_SECTOR_NOTES = {
    "reit":    "REITs distribute most earnings as dividends. P/E ratio is not meaningful — focus on yield and P/B instead.",
    "bank":    "For banks, Price/Book is more meaningful than P/E. A P/B below 1 means you're buying assets at a discount.",
    "utility": "Utilities carry structural debt to fund infrastructure. Higher debt ratios are normal and generally not a concern.",
    "oil":     "Oil & Gas companies are cyclical — profits and dividends depend heavily on commodity prices. Best bought when oil prices are low, not high.",
    "tech":    "Technology companies often trade at higher P/E ratios. However, for a dividend strategy, prefer established tech companies with consistent payouts over high-growth names.",
    "holding": "Holdings invest in other companies. Standard ratios like P/E and P/B are less meaningful — focus on dividend track record and debt levels.",
}


def score_stock(info: dict, debt_to_ebitda, min_yield: float = 4.0, max_per: float = 15.0) -> dict:
    sector   = info.get("sector")   or ""
    industry = info.get("industry") or ""
    profile  = get_sector_profile(sector, industry)

    per = safe_float(info.get("trailingPE"))
    if per is None or per <= 0:
        per = safe_float(info.get("forwardPE"))
        if per is not None and per <= 0:
            per = None

    # PER scoring
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

    # Yield scoring
    dividend_rate = safe_float(info.get("dividendRate")) or safe_float(info.get("lastDividendValue"))
    current_price = safe_float(info.get("currentPrice")) or safe_float(info.get("regularMarketPrice"))
    if dividend_rate and current_price and current_price > 0:
        dividend_yield = round((dividend_rate / current_price) * 100, 2)
    else:
        _dy_raw = safe_float(info.get("dividendYield", None))
        if _dy_raw is None or _dy_raw <= 0:
            dividend_yield = None
        elif _dy_raw < 0.50:
            dividend_yield = round(_dy_raw * 100, 2)
        elif _dy_raw > 30:
            dividend_yield = None
        else:
            dividend_yield = round(_dy_raw, 2)
    if dividend_yield is None:
        yield_score = "none"
    else:
        y = dividend_yield
        if profile == "reit":
            yield_score = "buy" if y > 5 else ("neutral" if y >= 3 else "low")
        else:
            yield_score = "buy" if y > min_yield else ("neutral" if y >= 2 else "low")

    # Debt scoring
    if debt_to_ebitda is None:
        debt_score = "unavailable"
    elif profile == "utility":
        debt_score = "safe" if debt_to_ebitda < 4 else ("moderate" if debt_to_ebitda <= 5 else "high")
    else:
        debt_score = "safe" if debt_to_ebitda < 3 else ("moderate" if debt_to_ebitda <= 4 else "high")

    # Book scoring
    ptb = safe_float(info.get("priceToBook"))
    if profile == "holding":
        book_score = "not_applicable"
    elif ptb is None:
        book_score = "unavailable"
    elif profile == "bank":
        book_score = "buy" if ptb < 1 else ("fair" if ptb <= 1.5 else "expensive")
    elif profile == "reit":
        book_score = "buy" if ptb < 1.2 else ("fair" if ptb <= 2 else "expensive")
    else:
        book_score = "buy" if ptb < 1 else ("fair" if ptb <= 2 else "expensive")

    # Payout scoring
    payout = safe_float(info.get("payoutRatio"))
    if profile == "holding":
        payout_score = "not_applicable"
    elif payout is None:
        payout_score = "unavailable"
    else:
        p = payout * 100
        if p < 40:
            payout_score = "low"
        elif p <= 60:
            payout_score = "healthy"
        elif p <= 80:
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
async def analyze_ticker(ticker: str, min_yield: float = 4.0, max_per: float = 15.0):
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

        dividend_rate = safe_float(info.get("dividendRate")) or safe_float(info.get("lastDividendValue"))
        current_price_val = safe_float(info.get("currentPrice")) or safe_float(info.get("regularMarketPrice"))
        if dividend_rate and current_price_val and current_price_val > 0:
            dividend_yield = round((dividend_rate / current_price_val) * 100, 2)
        else:
            _dy_raw = safe_float(info.get("dividendYield", None))
            if _dy_raw is None or _dy_raw <= 0:
                dividend_yield = None
            elif _dy_raw < 0.50:
                dividend_yield = round(_dy_raw * 100, 2)
            elif _dy_raw > 30:
                dividend_yield = None
            else:
                dividend_yield = round(_dy_raw, 2)
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

        per_raw = safe_float(info.get("trailingPE"))
        if per_raw is None or per_raw <= 0:
            per_raw = safe_float(info.get("forwardPE"))
            if per_raw is not None and per_raw <= 0:
                per_raw = None

        payout = safe_float(info.get("payoutRatio"))
        ptb = safe_float(info.get("priceToBook"))
        scores = score_stock(info, debt_to_ebitda, min_yield, max_per)
        dividend_trend = dividend_growth_trend(stock)

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
                "payoutRatio": round(payout * 100, 2) if payout is not None else None,
                "priceToBook": round(ptb, 2) if ptb is not None else None,
                "debtToEbitda": round(debt_to_ebitda, 2) if debt_to_ebitda is not None else None,
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


@app.get("/api/dividends-received")
async def dividends_received_endpoint(symbol: str, from_date: str, shares: float):
    try:
        stock = yf.Ticker(symbol)
        info = stock.info
        currency = info.get("currency", "USD")

        divs = stock.dividends
        if divs is None or len(divs) == 0:
            return {"symbol": symbol.upper(), "dividends": [], "totalReceived": 0.0, "currency": currency}

        from_date_obj = datetime.datetime.strptime(from_date, "%Y-%m-%d").date()

        result_divs = []
        for ts, amount_per_share in divs.items():
            if ts.date() >= from_date_obj:
                total = float(amount_per_share) * shares
                result_divs.append({
                    "date": ts.strftime("%Y-%m-%d"),
                    "amountPerShare": round(float(amount_per_share), 4),
                    "totalAmount": round(total, 2),
                })

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

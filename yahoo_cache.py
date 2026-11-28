"""In-memory cache for Yahoo Finance responses.

Quote fields (price, yield, ratios) are reused for a short interval.
Dividend history and financial statements change slowly, so they stay
cached much longer. The cache is process-local, bounded, and safe to
call from the worker threads that run blocking yfinance calls.
"""
import random
import threading
import time
from collections import OrderedDict

import yfinance as yf
from yfinance.exceptions import YFRateLimitError


# Quote data moves during the session. Statements and dividend history do not.
INFO_TTL_SECONDS = 20 * 60
DIVIDEND_TTL_SECONDS = 18 * 60 * 60
STATEMENT_TTL_SECONDS = 18 * 60 * 60
HISTORY_TTL_SECONDS = 20 * 60
CALENDAR_TTL_SECONDS = 12 * 60 * 60

# A full watchlist plus a few open analyses. Oldest entries are dropped first.
CACHE_MAX_ENTRIES = 512

# yfinance calls block, so this caps how many run at once.
YAHOO_CONCURRENCY = 8
YAHOO_ATTEMPTS = 3


class _Miss:
    """Sentinel for a cache miss. Stored values may themselves be None."""


CACHE_MISS = _Miss()


class _SkipCache(Exception):
    """A successful fetch that should be returned but not stored."""

    def __init__(self, value):
        self.value = value


class TTLCache:
    """Thread-safe LRU cache. Each entry expires after its own TTL.

    `clock` is injectable so tests can expire entries without sleeping.
    A time of exactly `stored_at + ttl` is already expired.
    """

    def __init__(self, max_entries, clock=None):
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = int(max_entries)
        self._clock = clock or time.monotonic
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        now = self._clock()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return CACHE_MISS
            expires_at, value = item
            if expires_at <= now:
                del self._items[key]
                return CACHE_MISS
            self._items.move_to_end(key)
            return value

    def set(self, key, value, ttl):
        now = self._clock()
        with self._lock:
            if key in self._items:
                del self._items[key]
            self._items[key] = (now + ttl, value)
            self._evict_locked(now)

    def delete(self, key):
        with self._lock:
            self._items.pop(key, None)

    def clear(self):
        with self._lock:
            self._items.clear()

    def __len__(self):
        with self._lock:
            return len(self._items)

    def _evict_locked(self, now):
        expired = [key for key, (expires_at, _) in self._items.items() if expires_at <= now]
        for key in expired:
            del self._items[key]
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)


MARKET_CACHE = TTLCache(CACHE_MAX_ENTRIES)

_YAHOO = threading.BoundedSemaphore(YAHOO_CONCURRENCY)
_flight_lock = threading.Lock()
_flights = {}


class _Flight:
    def __init__(self):
        self.event = threading.Event()
        self.value = CACHE_MISS
        self.error = None


def clear_market_cache():
    """Drop cached Yahoo data and any in-flight markers. Used by tests."""
    MARKET_CACHE.clear()
    with _flight_lock:
        _flights.clear()


def _symbol_key(symbol) -> str:
    return str(symbol or "").strip().upper()


def _is_transient(exc) -> bool:
    if isinstance(exc, YFRateLimitError):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    name = type(exc).__name__.lower()
    if "timeout" in name or "connection" in name or name in {
        "chunkedencodingerror",
        "remotedisconnected",
        "protocolerror",
    }:
        return True
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    if status in {429, 500, 502, 503, 504}:
        return True
    text = str(exc).lower()
    return "too many requests" in text or "rate limit" in text


def _backoff(attempt):
    # 0.5s, 1s, 2s, plus a little jitter so parallel retries do not line up.
    delay = min(4.0, 0.5 * (2 ** attempt))
    time.sleep(delay + random.uniform(0, 0.25))


def _retry(loader):
    last_error = None
    for attempt in range(YAHOO_ATTEMPTS):
        try:
            return loader()
        except _SkipCache:
            raise
        except Exception as exc:
            last_error = exc
            if attempt == YAHOO_ATTEMPTS - 1 or not _is_transient(exc):
                raise
            _backoff(attempt)
    raise last_error


def cached_load(key, ttl, loader, fresh=False):
    """Return the cached value for `key`, or compute it once and store it.

    Concurrent callers for the same key share one fetch. `fresh=True` ignores
    a stored value and replaces it. Failures are not cached.
    """
    if not fresh:
        hit = MARKET_CACHE.get(key)
        if hit is not CACHE_MISS:
            return hit

    with _flight_lock:
        flight = _flights.get(key)
        if flight is None:
            flight = _Flight()
            _flights[key] = flight
            leader = True
        else:
            leader = False

    if not leader:
        if not flight.event.wait(120):
            raise TimeoutError("timed out waiting for Yahoo data")
        if flight.error is not None:
            raise flight.error
        return flight.value

    try:
        if not fresh:
            hit = MARKET_CACHE.get(key)
            if hit is not CACHE_MISS:
                flight.value = hit
                return hit
        with _YAHOO:
            if not fresh:
                hit = MARKET_CACHE.get(key)
                if hit is not CACHE_MISS:
                    flight.value = hit
                    return hit
            value = _retry(loader)
        MARKET_CACHE.set(key, value, ttl)
        flight.value = value
        return value
    except Exception as exc:
        flight.error = exc
        raise
    finally:
        with _flight_lock:
            if _flights.get(key) is flight:
                _flights.pop(key, None)
        flight.event.set()


def call_yahoo(loader):
    """Run one blocking Yahoo call under the shared concurrency cap, with retries."""
    with _YAHOO:
        return _retry(loader)


def cached_info(symbol, fresh=False) -> dict:
    key = ("info", _symbol_key(symbol))

    def load():
        info = yf.Ticker(symbol).info
        if not isinstance(info, dict):
            info = {}
        # An empty payload is usually a missing ticker, sometimes a rate-limit
        # stub. Either way it must not stick in the cache for the whole TTL.
        if not info.get("quoteType"):
            raise _SkipCache(info)
        return info

    try:
        return cached_load(key, INFO_TTL_SECONDS, load, fresh=fresh)
    except _SkipCache as exc:
        return exc.value


def cached_dividends(symbol, fresh=False):
    key = ("div", _symbol_key(symbol))

    def load():
        return yf.Ticker(symbol).dividends

    return cached_load(key, DIVIDEND_TTL_SECONDS, load, fresh=fresh)


def cached_statements(symbol, fresh=False):
    """Balance sheet and income statement, used only for the Debt/EBITDA fallback."""
    key = ("stmt", _symbol_key(symbol))

    def load():
        stock = yf.Ticker(symbol)
        return stock.balance_sheet, stock.financials

    return cached_load(key, STATEMENT_TTL_SECONDS, load, fresh=fresh)


def cached_price_history(symbol, fresh=False):
    """One year of weekly closes, in the shape the price chart already expects."""
    key = ("hist", _symbol_key(symbol))

    def load():
        hist = yf.Ticker(symbol).history(period="1y", interval="1wk")
        rows = []
        if hist is not None and not getattr(hist, "empty", True):
            for ts, row in hist.iterrows():
                rows.append({
                    "date": ts.strftime("%Y-%m-%d"),
                    "close": round(float(row["Close"]), 2),
                })
        return rows

    return cached_load(key, HISTORY_TTL_SECONDS, load, fresh=fresh)


def cached_dividend_date(symbol, fresh=False):
    key = ("cal", _symbol_key(symbol))

    def load():
        calendar = yf.Ticker(symbol).calendar
        if isinstance(calendar, dict):
            value = calendar.get("Dividend Date")
            return None if value is None else str(value)
        if hasattr(calendar, "index") and "Dividend Date" in calendar.index:
            return str(calendar.loc["Dividend Date"].iloc[0])
        return None

    return cached_load(key, CALENDAR_TTL_SECONDS, load, fresh=fresh)

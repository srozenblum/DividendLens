"""Light watchlist payload, without calling Yahoo.

Run: python tests/test_watchlist_endpoint.py
"""
import asyncio
import datetime
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import yahoo_cache


INFO = {
    "quoteType": "EQUITY",
    "longName": "Verizon Communications Inc.",
    "shortName": "Verizon",
    "currentPrice": 40.0,
    "regularMarketPrice": 40.0,
    "currency": "USD",
    "exchange": "NYQ",
    "sector": "Communication Services",
    "industry": "Telecom Services",
    "trailingPE": 10.0,
    "dividendRate": 2.4,
    "payoutRatio": 0.55,
    "priceToBook": 1.4,
    "totalDebt": 100.0,
    "ebitda": 50.0,
}

WATCHLIST_KEYS = {
    "companyName",
    "ticker",
    "sector",
    "industry",
    "metrics",
    "scoringInputs",
    "scores",
    "dividendTrend",
}
SCORE_INPUT_KEYS = {
    "sector",
    "industry",
    "per",
    "dividendYield",
    "debtToEbitda",
    "priceToBook",
    "payoutRatio",
    "fcfPayout",
    "fcfDeficit",
    "dividendCutRecent",
}
METRIC_KEYS = {
    "per",
    "dividendYield",
    "trailingDividendYield",
    "yieldComparison",
    "payoutRatio",
    "priceToBook",
    "debtToEbitda",
    "fcfPayout",
    "fcfPayoutBasis",
    "fcfDeficit",
    "yearsDividendPaid",
    "yearsDividendRaised",
    "dividendCagr5y",
    "dividendCutRecent",
}
ANALYZE_KEYS = WATCHLIST_KEYS | {
    "currentPrice",
    "currency",
    "exchange",
    "dividendInfo",
    "priceHistory",
}


def _dividends():
    today = datetime.date.today()
    year = today.year
    index = []
    values = []
    for offset, amount in ((3, 0.40), (2, 0.50), (1, 0.60)):
        for month in (3, 6, 9, 12):
            index.append(pd.Timestamp(datetime.date(year - offset, month, 15)))
            values.append(amount)
    index.append(pd.Timestamp(today - datetime.timedelta(days=20)))
    values.append(0.60)
    return pd.Series(values, index=index)


DIVS = _dividends()


def _cashflow_frame():
    # Latest year: dividends 80 on free cash flow of 200, a 40% payout.
    return pd.DataFrame(
        [[200.0, 180.0], [-80.0, -70.0]],
        index=["Free Cash Flow", "Common Stock Dividend Paid"],
        columns=pd.to_datetime(["2024-12-31", "2023-12-31"]),
    )


class Recorder:
    def __init__(self):
        self.calls = []
        self.lock = __import__("threading").Lock()

    def add(self, name):
        with self.lock:
            self.calls.append(name)

    def names(self):
        with self.lock:
            return list(self.calls)


def _install(recorder, info, balance_sheet=None, financials=None):
    class FakeTicker:
        def __init__(self, symbol):
            recorder.add("init")

        @property
        def info(self):
            recorder.add("info")
            return dict(info)

        @property
        def dividends(self):
            recorder.add("dividends")
            return DIVS.copy()

        @property
        def calendar(self):
            recorder.add("calendar")
            return {"Dividend Date": "2026-11-01"}

        @property
        def balance_sheet(self):
            recorder.add("balance_sheet")
            return balance_sheet

        @property
        def financials(self):
            recorder.add("financials")
            return financials

        def history(self, **kwargs):
            recorder.add("history:" + str(kwargs.get("period")) + ":" + str(kwargs.get("interval")))
            index = pd.to_datetime(["2026-01-05", "2026-01-12", "2026-01-19"])
            return pd.DataFrame({"Close": [39.0, 40.5, 41.25]}, index=index)

        @property
        def cashflow(self):
            recorder.add("cashflow")
            return _cashflow_frame()

    main.yf.Ticker = FakeTicker
    yahoo_cache.yf.Ticker = FakeTicker


def _restore(original):
    main.yf.Ticker = original
    yahoo_cache.yf.Ticker = original
    yahoo_cache.clear_market_cache()


def test_watchlist_shape_matches_scoring_and_skips_the_chart():
    recorder = Recorder()
    original = main.yf.Ticker
    _install(recorder, INFO)
    try:
        row = asyncio.run(main.watchlist_ticker("vz", min_yield=4, max_per=15))
        assert set(row) == WATCHLIST_KEYS
        assert "priceHistory" not in row
        assert "dividendInfo" not in row
        assert row["ticker"] == "VZ"
        assert row["companyName"] == "Verizon Communications Inc."
        assert row["sector"] == "Communication Services"
        assert row["industry"] == "Telecom Services"
        assert set(row["metrics"]) == METRIC_KEYS
        assert row["metrics"]["per"] == 10.0
        assert row["metrics"]["dividendYield"] == 6.0
        assert row["metrics"]["debtToEbitda"] == 2.0
        assert row["metrics"]["payoutRatio"] == 55.0
        assert row["metrics"]["priceToBook"] == 1.4
        assert set(row["scoringInputs"]) == SCORE_INPUT_KEYS
        assert row["scoringInputs"]["per"] == 10.0
        assert row["scoringInputs"]["dividendYield"] == 6.0
        assert row["scoringInputs"]["debtToEbitda"] == 2.0
        assert row["scoringInputs"]["priceToBook"] == 1.4
        assert round(row["scoringInputs"]["payoutRatio"], 2) == 55.0
        assert row["scoringInputs"]["sector"] == "Communication Services"
        assert row["scoringInputs"]["industry"] == "Telecom Services"

        expected_scores = main.score_stock(INFO, 100.0 / 50.0, 4, 15)
        expected_summary = main.summarize_dividend_yields(DIVS, 40.0, 6.0)
        assert row["scores"] == expected_scores
        assert row["scores"]["overallRecommendation"] == "strong_buy"
        assert row["metrics"]["trailingDividendYield"] == expected_summary["trailingDividendYield"]
        assert row["metrics"]["yieldComparison"] == expected_summary["yieldComparison"]
        assert row["dividendTrend"] == main.dividend_growth_trend(main._DividendSeries(DIVS))
        history = main.dividend_history_metrics(DIVS)
        assert row["metrics"]["fcfPayout"] == 40.0
        assert row["metrics"]["fcfPayoutBasis"] == "fcf"
        assert row["metrics"]["fcfDeficit"] is False
        assert row["metrics"]["dividendCutRecent"] is False
        assert row["metrics"]["yearsDividendPaid"] == history["yearsDividendPaid"]
        assert row["metrics"]["yearsDividendRaised"] == history["yearsDividendRaised"]
        assert row["metrics"]["dividendCagr5y"] == history["dividendCagr5y"]
        assert row["scoringInputs"]["fcfPayout"] == 40.0
        assert row["scoringInputs"]["fcfDeficit"] is False
        assert row["scoringInputs"]["dividendCutRecent"] is False
        assert row["scores"]["sustainabilityWarning"] is False

        called = recorder.names()
        assert "info" in called
        assert "dividends" in called
        assert "cashflow" in called
        assert "calendar" not in called
        assert "balance_sheet" not in called
        assert "financials" not in called
        assert not any(name.startswith("history:") for name in called)

        before = len(recorder.names())
        again = asyncio.run(main.watchlist_ticker("VZ", min_yield=4, max_per=15))
        assert again["scores"] == row["scores"]
        assert again["metrics"] == row["metrics"]
        assert len(recorder.names()) == before

        fresh = asyncio.run(main.watchlist_ticker("vz", fresh=True))
        assert fresh["metrics"]["dividendYield"] == 6.0
        assert len(recorder.names()) > before
    finally:
        _restore(original)


def test_analyze_keeps_its_shape_and_the_same_scores():
    recorder = Recorder()
    original = main.yf.Ticker
    _install(recorder, INFO)
    yahoo_cache.clear_market_cache()
    try:
        row = asyncio.run(main.watchlist_ticker("vz"))
        full = asyncio.run(main.analyze_ticker("vz", 4, 15))
        assert set(full) == ANALYZE_KEYS
        assert set(full["metrics"]) == METRIC_KEYS
        assert set(full["dividendInfo"]) == {"paysDividends", "dividendRate", "lastDividendDate"}
        assert full["scores"] == row["scores"]
        assert full["metrics"] == row["metrics"]
        assert full["scoringInputs"] == row["scoringInputs"]
        assert full["dividendTrend"] == row["dividendTrend"]
        assert full["companyName"] == row["companyName"]
        assert full["currentPrice"] == 40.0
        assert full["currency"] == "USD"
        assert full["priceHistory"] == [
            {"date": "2026-01-05", "close": 39.0},
            {"date": "2026-01-12", "close": 40.5},
            {"date": "2026-01-19", "close": 41.25},
        ]
        assert full["dividendInfo"]["paysDividends"] is True
        assert full["dividendInfo"]["lastDividendDate"] == "2026-11-01"
        assert "history:1y:1wk" in recorder.names()
        assert "calendar" in recorder.names()
    finally:
        _restore(original)


def test_missing_ticker_is_a_404_and_statements_fill_debt():
    original = main.yf.Ticker
    try:
        recorder = Recorder()

        class Missing:
            def __init__(self, symbol):
                recorder.add("init")

            @property
            def info(self):
                recorder.add("info")
                return {}

        main.yf.Ticker = Missing
        yahoo_cache.yf.Ticker = Missing
        yahoo_cache.clear_market_cache()
        try:
            asyncio.run(main.watchlist_ticker("NOPE"))
            raise AssertionError("missing ticker must 404")
        except main.HTTPException as exc:
            assert exc.status_code == 404

        thin = dict(INFO)
        thin.pop("totalDebt")
        thin.pop("ebitda")
        balance = pd.DataFrame([80.0], index=["Total Debt"], columns=["2024-12-31"])
        income = pd.DataFrame([20.0], index=["EBITDA"], columns=["2024-12-31"])
        recorder = Recorder()
        _install(recorder, thin, balance, income)
        row = asyncio.run(main.watchlist_ticker("debt.co", min_yield=4, max_per=15))
        assert row["metrics"]["debtToEbitda"] == 4.0
        assert "balance_sheet" in recorder.names()
        assert "financials" in recorder.names()
        expected = main.score_stock(thin, 4.0, 4, 15)
        assert row["scores"] == expected

        before = len(recorder.names())
        cached = asyncio.run(main.watchlist_ticker("DEBT.CO"))
        assert cached["metrics"]["debtToEbitda"] == 4.0
        assert len(recorder.names()) == before
    finally:
        _restore(original)


def test_batch_streams_each_symbol_and_reports_a_miss():
    recorder = Recorder()
    original = main.yf.Ticker
    _install(recorder, INFO)
    try:
        async def collect():
            rows = []
            async for item in main.iter_watchlist_rows(["vz", "vz", " ", "NOPE"], min_yield=4, max_per=15):
                rows.append(item)
            return rows

        # NOPE uses the same fake, which always returns Verizon. Swap in a
        # ticker that is empty only for that symbol.
        class Mixed:
            def __init__(self, symbol):
                self.symbol = symbol
                recorder.add("init:" + symbol)

            @property
            def info(self):
                recorder.add("info:" + self.symbol)
                if str(self.symbol).upper() == "NOPE":
                    return {}
                return dict(INFO)

            @property
            def dividends(self):
                recorder.add("dividends:" + self.symbol)
                return DIVS.copy()

            def history(self, **kwargs):
                recorder.add("history")
                raise AssertionError("batch watchlist must not download the price chart")

            @property
            def cashflow(self):
                recorder.add("cashflow:" + self.symbol)
                return _cashflow_frame()

            @property
            def calendar(self):
                recorder.add("calendar")
                raise AssertionError("batch watchlist must not download the calendar")

        main.yf.Ticker = Mixed
        yahoo_cache.yf.Ticker = Mixed
        yahoo_cache.clear_market_cache()
        rows = asyncio.run(collect())
        by_symbol = {row["symbol"]: row for row in rows}
        assert set(by_symbol) == {"vz", "NOPE"}
        assert by_symbol["vz"]["ok"] is True
        assert set(by_symbol["vz"]["data"]) == WATCHLIST_KEYS
        assert by_symbol["vz"]["data"]["ticker"] == "VZ"
        assert by_symbol["vz"]["data"]["metrics"]["dividendYield"] == 6.0
        assert set(by_symbol["vz"]["data"]["scoringInputs"]) == SCORE_INPUT_KEYS
        assert by_symbol["NOPE"]["ok"] is False
        assert "not found" in by_symbol["NOPE"]["error"].lower()
        assert "history" not in recorder.names()
        assert "calendar" not in recorder.names()
    finally:
        _restore(original)


if __name__ == "__main__":
    test_watchlist_shape_matches_scoring_and_skips_the_chart()
    test_analyze_keeps_its_shape_and_the_same_scores()
    test_missing_ticker_is_a_404_and_statements_fill_debt()
    test_batch_streams_each_symbol_and_reports_a_miss()
    print("All watchlist endpoint tests passed.")

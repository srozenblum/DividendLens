"""Dividend sustainability: cash payout, streaks, CAGR, and scoring parity.

Run: python tests/test_sustainability.py

Cash-flow math and dividend history are covered here, including the edges
that must not crash or invent a penalty. The warning rule itself is also
in tests/test_scoring.py, which checks Python and static/scoring.js agree.
"""
import asyncio
import datetime
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import yahoo_cache

ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime.date(2026, 6, 15)


def _series(payments):
    index = []
    values = []
    for ex_date, amount in payments:
        index.append(pd.Timestamp(ex_date))
        values.append(amount)
    return pd.Series(values, index=index)


def _quarters(year, amount, months=(3, 6, 9, 12)):
    return [(datetime.date(year, month, 15), amount) for month in months]


def _frame(rows, columns):
    return pd.DataFrame(list(rows.values()), index=list(rows.keys()), columns=columns)


def test_fcf_payout_uses_the_latest_common_dividend():
    columns = pd.to_datetime(["2023-12-31", "2024-12-31"])
    frame = _frame({
        "Free Cash Flow": [100.0, 200.0],
        "Cash Dividends Paid": [-90.0, -80.0],
        "Common Stock Dividend Paid": [-40.0, -50.0],
    }, columns)
    parsed = main.cash_flow_payout(frame, "fcf")
    # 2024 is the latest column. Common dividends win over the cash line,
    # which can include preferred stock.
    assert parsed == {"fcfPayout": 25.0, "fcfPayoutBasis": "fcf", "fcfDeficit": False}


def test_fcf_falls_back_when_the_latest_column_is_incomplete():
    columns = ["2024-12-31", "2023-12-31"]
    frame = _frame({
        "Free Cash Flow": [float("nan"), 180.0],
        "Common Stock Dividend Paid": [float("nan"), -36.0],
        "Operating Cash Flow": [100.0, 200.0],
        "Capital Expenditure": [-40.0, -20.0],
    }, columns)
    parsed = main.cash_flow_payout(frame, "fcf")
    assert parsed["fcfPayout"] == 20.0
    assert parsed["fcfDeficit"] is False


def test_fcf_is_rebuilt_from_operating_cash_and_capex():
    columns = ["2024-12-31"]
    negative_capex = _frame({
        "Operating Cash Flow": [100.0],
        "Capital Expenditure": [-30.0],
        "Common Stock Dividend Paid": [-35.0],
    }, columns)
    positive_capex = _frame({
        "Operating Cash Flow": [100.0],
        "Purchase Of PPE": [30.0],
        "Cash Dividends Paid": [-35.0],
    }, columns)
    assert main.cash_flow_payout(negative_capex, "fcf")["fcfPayout"] == 50.0
    assert main.cash_flow_payout(positive_capex, "fcf")["fcfPayout"] == 50.0


def test_negative_free_cash_flow_is_a_deficit_not_an_older_year():
    columns = pd.to_datetime(["2024-12-31", "2023-12-31"])
    frame = _frame({
        "Free Cash Flow": [-10.0, 100.0],
        "Common Stock Dividend Paid": [-5.0, -20.0],
    }, columns)
    parsed = main.cash_flow_payout(frame, "fcf")
    assert parsed["fcfPayout"] is None
    assert parsed["fcfDeficit"] is True


def test_missing_cash_flow_is_not_a_penalty():
    assert main.cash_flow_payout(None, "fcf") == {
        "fcfPayout": None, "fcfPayoutBasis": "fcf", "fcfDeficit": False,
    }
    assert main.cash_flow_payout(pd.DataFrame(), "ffo")["fcfDeficit"] is False
    assert main.cash_payout_ratio(None, 10) == (None, False)
    assert main.cash_payout_ratio(0, -5) == (0.0, False)
    assert main.cash_payout_ratio(5, 0) == (None, True)
    junk = _frame({"Free Cash Flow": ["n/a"], "Common Stock Dividend Paid": ["n/a"]}, ["2024-12-31"])
    parsed = main.cash_flow_payout(junk, "fcf")
    assert parsed["fcfPayout"] is None
    assert parsed["fcfDeficit"] is False


def test_duplicate_dividend_row_uses_the_first_number():
    frame = pd.DataFrame(
        [[200.0], [float("nan")], [-40.0]],
        index=["Free Cash Flow", "Common Stock Dividend Paid", "Common Stock Dividend Paid"],
        columns=pd.to_datetime(["2024-12-31"]),
    )
    assert main.cash_flow_payout(frame, "fcf")["fcfPayout"] == 20.0


def test_reit_uses_ffo_and_ignores_negative_free_cash_flow():
    columns = ["2024-12-31"]
    frame = _frame({
        "Free Cash Flow": [-500.0],
        "Net Income From Continuing Operations": [100.0],
        "Depreciation And Amortization": [50.0],
        "Common Stock Dividend Paid": [-30.0],
        "Gain Loss On Sale Of PPE": [-999.0],
    }, columns)
    parsed = main.cash_flow_payout(frame, "ffo")
    # 30 / (100 + 50). The gain line is intentionally ignored.
    assert parsed == {"fcfPayout": 20.0, "fcfPayoutBasis": "ffo", "fcfDeficit": False}

    uncovered = _frame({
        "Net Income From Continuing Operations": [-80.0],
        "Depreciation And Amortization": [10.0],
        "Common Stock Dividend Paid": [-5.0],
    }, columns)
    assert main.cash_flow_payout(uncovered, "ffo")["fcfDeficit"] is True

    missing = _frame({
        "Free Cash Flow": [80.0],
        "Net Income From Continuing Operations": [40.0],
        "Common Stock Dividend Paid": [-10.0],
    }, columns)
    assert main.cash_flow_payout(missing, "ffo")["fcfPayout"] is None
    assert main.cash_flow_payout(missing, "ffo")["fcfDeficit"] is False


def test_dividend_streaks_ignore_the_current_year_and_specials():
    payments = []
    per_quarter = {2020: 0.25, 2021: 0.30, 2022: 0.35, 2023: 0.40, 2024: 0.45, 2025: 0.50}
    for year, amount in per_quarter.items():
        payments.extend(_quarters(year, amount))
    # A still-open year, even a lower one, must not change the streak.
    payments.extend(_quarters(2026, 0.05, months=(3, 6)))
    # One special in 2023. The regular year stays 1.60, so 2024 is not a cut.
    payments.append((datetime.date(2023, 11, 20), 3.0))

    metrics = main.dividend_history_metrics(_series(payments), as_of=AS_OF)
    assert metrics["yearsDividendPaid"] == 6
    assert metrics["yearsDividendRaised"] == 5
    assert metrics["dividendCutRecent"] is False
    assert metrics["dividendCagr5y"] == 14.87

    # Without dropping the special, 2023 would be 4.60 and 2024 (1.80) a cut.
    raw = main._annual_dividends(_series(payments), AS_OF)
    assert round(raw[2023]["paid"], 2) == 4.6
    assert round(raw[2023]["regular"], 2) == 1.6


def test_flat_band_splits_and_suspension():
    # Exactly 1% either way is flat. Just past 1% down is a cut.
    flat_up = _series([
        (datetime.date(2024, 6, 1), 1.00),
        (datetime.date(2025, 6, 1), 1.01),
    ])
    up = main.dividend_history_metrics(flat_up, as_of=AS_OF)
    assert up["yearsDividendRaised"] == 0
    assert up["dividendCutRecent"] is False

    flat_down = _series([
        (datetime.date(2024, 6, 1), 1.00),
        (datetime.date(2025, 6, 1), 0.99),
    ])
    assert main.dividend_history_metrics(flat_down, as_of=AS_OF)["dividendCutRecent"] is False

    cut = _series([
        (datetime.date(2024, 6, 1), 1.00),
        (datetime.date(2025, 6, 1), 0.98),
    ])
    assert main.dividend_history_metrics(cut, as_of=AS_OF)["dividendCutRecent"] is True

    # Split-adjusted amounts stay on one scale, so a split year is not a cut.
    # Four 0.50 payments are the same annual dividend as two 1.00 payments.
    adjusted = []
    for year in (2022, 2023):
        adjusted.extend(_quarters(year, 0.50))
    adjusted.extend([
        (datetime.date(2024, 6, 1), 1.00),
        (datetime.date(2024, 12, 1), 1.00),
        (datetime.date(2025, 6, 1), 1.00),
        (datetime.date(2025, 12, 1), 1.00),
    ])
    split = main.dividend_history_metrics(_series(adjusted), as_of=AS_OF)
    assert split["yearsDividendPaid"] == 4
    assert split["yearsDividendRaised"] == 0
    assert split["dividendCutRecent"] is False

    # A token payment must not turn the real dividend into a special.
    dust = _series([
        (datetime.date(2024, 6, 1), 2.00),
        (datetime.date(2024, 12, 1), 0.01),
        (datetime.date(2025, 6, 1), 2.20),
    ])
    dust_metrics = main.dividend_history_metrics(dust, as_of=AS_OF)
    assert dust_metrics["yearsDividendRaised"] == 1
    assert dust_metrics["dividendCutRecent"] is False

    # A repeated large amount is a new regular dividend, not one special.
    # The following year stays at 2.00, so neither large payment reverts.
    repeated = []
    repeated.extend([
        (datetime.date(2024, 3, 15), 0.50),
        (datetime.date(2024, 6, 15), 0.50),
        (datetime.date(2024, 9, 15), 2.00),
        (datetime.date(2024, 12, 15), 2.00),
    ])
    repeated.extend(_quarters(2025, 2.00))
    repeated_rates = main._rates_by_year(_series(repeated), AS_OF)
    assert repeated_rates[2024] == 5.0

    # A step-up inside the year stays in the cycle. Nothing here is a special.
    gradual = _series([
        (datetime.date(2025, 3, 15), 0.40),
        (datetime.date(2025, 6, 15), 0.42),
        (datetime.date(2025, 9, 15), 0.44),
        (datetime.date(2025, 12, 15), 0.46),
    ])
    assert main._rates_by_year(gradual, AS_OF)[2025] == 1.72


def test_calendar_count_shift_is_not_a_cut():
    """11 payments one year and 13 the next is a slipped ex-date, not a cut.

    The December payment is dated 2 January. Summing the calendar year
    would show a drop of about one month and then a jump. The year-end
    cycle still has 12 regular payments, and the raise streak continues.
    The same shift for a quarterly payer (3 payments, then 5) is covered
    too.
    """
    payments = []
    for year in range(2018, 2026):
        amount = round(0.20 + 0.01 * (year - 2018), 2)
        months = range(1, 12) if year == 2024 else range(1, 13)
        for month in months:
            payments.append((datetime.date(year, month, 15), amount))
    payments.append((datetime.date(2025, 1, 2), 0.26))
    metrics = main.dividend_history_metrics(_series(payments), as_of=AS_OF)
    rates = main._rates_by_year(_series(payments), AS_OF)
    assert metrics["dividendCutRecent"] is False
    assert metrics["yearsDividendRaised"] == 7
    # 11 × 0.26 would be 2.86. A full cycle is about 12 × 0.26.
    assert rates[2024] > 3.0
    assert rates[2025] > rates[2024]
    assert abs(rates[2025] - 0.27 * 12) < 0.05

    quarterly = []
    for year in range(2018, 2026):
        amount = round(0.40 + 0.02 * (year - 2018), 2)
        months = (3, 6, 9) if year == 2024 else (3, 6, 9, 12)
        for month in months:
            quarterly.append((datetime.date(year, month, 15), amount))
    quarterly.append((datetime.date(2025, 1, 2), 0.52))
    q_metrics = main.dividend_history_metrics(_series(quarterly), as_of=AS_OF)
    q_rates = main._rates_by_year(_series(quarterly), AS_OF)
    assert q_metrics["dividendCutRecent"] is False
    assert q_metrics["yearsDividendRaised"] == 7
    # 3 × 0.52 would be 1.56. A full quarterly cycle is about 4 × 0.52.
    assert q_rates[2024] > 1.9
    assert q_rates[2025] > q_rates[2024]


def test_shapes_from_real_dividend_patterns():
    """Synthetic series shaped like names the screen has to get right.

    No market data is stored. The shapes are: a quarterly cut that sticks
    (the 2022 AT&T cut), a monthly dividend plus a smaller or larger
    supplemental (Main Street), an annual payer that raises most years
    (a European annual dividend), and a semiannual interim plus a larger
    final whose final payment slips into January.
    """
    quarterly = []
    for year in range(2019, 2026):
        amount = 0.52 if year < 2022 else 0.278
        months = (3, 6, 9, 12)
        for index, month in enumerate(months):
            if year == 2022 and index < 2:
                paid = 0.52
            else:
                paid = amount
            quarterly.append((datetime.date(year, month, 15), paid))
    cut = main.dividend_history_metrics(_series(quarterly), as_of=AS_OF)
    assert cut["dividendCutRecent"] is True
    assert cut["yearsDividendRaised"] == 0

    monthly = []
    for year in range(2018, 2026):
        regular = round(0.20 + 0.005 * (year - 2018), 3)
        for month in range(1, 13):
            monthly.append((datetime.date(year, month, 5), regular))
        extra = 0.08 if year < 2022 else round(regular + 0.05, 3)
        for month in (3, 6, 9, 12):
            monthly.append((datetime.date(year, month, 20), extra))
    supplemental = main.dividend_history_metrics(_series(monthly), as_of=AS_OF)
    assert supplemental["dividendCutRecent"] is False
    assert supplemental["yearsDividendRaised"] >= 5
    rates = main._rates_by_year(_series(monthly), AS_OF)
    # The year-end cycle is the monthly amount, not the monthly amount plus supplements.
    assert abs(rates[2025] - round(0.20 + 0.005 * 7, 3) * 12) < 0.15

    annual = []
    annual_amounts = {
        2018: 8.0, 2019: 9.0, 2020: 9.6, 2021: 9.6,
        2022: 10.8, 2023: 11.4, 2024: 13.8, 2025: 15.4,
    }
    for year, amount in annual_amounts.items():
        annual.append((datetime.date(year, 5, 9), amount))
    europe = main.dividend_history_metrics(_series(annual), as_of=AS_OF)
    assert europe["dividendCutRecent"] is False
    assert europe["yearsDividendPaid"] == 8
    assert europe["yearsDividendRaised"] == 4
    assert europe["dividendCagr5y"] is not None and europe["dividendCagr5y"] > 0

    # Interim in May, larger final in November. The 2024 final is dated
    # 3 January 2025, which used to look like a missing payment and a cut.
    semi = []
    for year, interim, final in (
        (2021, 0.70, 1.10),
        (2022, 0.75, 1.15),
        (2023, 0.80, 1.20),
        (2024, 0.85, None),
        (2025, 0.90, 1.35),
    ):
        semi.append((datetime.date(year, 5, 15), interim))
        if final is not None and year != 2024:
            semi.append((datetime.date(year, 11, 15), final))
    semi.append((datetime.date(2025, 1, 3), 1.25))
    slipped = main.dividend_history_metrics(_series(semi), as_of=AS_OF)
    slipped_rates = main._rates_by_year(_series(semi), AS_OF)
    assert slipped["dividendCutRecent"] is False
    assert slipped_rates[2024] > slipped_rates[2023]
    assert slipped_rates[2025] > slipped_rates[2024]


def test_gaps_cagr_and_missing_history():
    # 2023 is missing, so the paid streak stops at the last two years.
    gap_payments = []
    for year in (2022, 2024, 2025):
        gap_payments.extend(_quarters(year, 0.25))
    gap = main.dividend_history_metrics(_series(gap_payments), as_of=AS_OF)
    assert gap["yearsDividendPaid"] == 2
    assert gap["dividendCutRecent"] is False

    # Paid through 2023, then nothing. That is a cut, not missing data.
    stopped = []
    for year in range(2020, 2024):
        stopped.append((datetime.date(year, 6, 1), 1.0))
    stopped_metrics = main.dividend_history_metrics(_series(stopped), as_of=AS_OF)
    assert stopped_metrics["yearsDividendPaid"] == 0
    assert stopped_metrics["dividendCutRecent"] is True

    # A cut in 2019 is outside the five complete years ending 2025.
    old_cut = []
    amounts = {
        2018: 2.00, 2019: 1.00, 2020: 1.10, 2021: 1.20,
        2022: 1.30, 2023: 1.40, 2024: 1.50, 2025: 1.60,
    }
    for year, amount in amounts.items():
        old_cut.append((datetime.date(year, 6, 1), amount))
    old = main.dividend_history_metrics(_series(old_cut), as_of=AS_OF)
    assert old["dividendCutRecent"] is False
    assert old["yearsDividendRaised"] == 6

    # A cut whose later year is still inside the five-year window does warn.
    recent = []
    recent_amounts = {2020: 2.00, 2021: 1.00, 2022: 1.10, 2023: 1.20, 2024: 1.30, 2025: 1.40}
    for year, amount in recent_amounts.items():
        recent.append((datetime.date(year, 6, 1), amount))
    recent_metrics = main.dividend_history_metrics(_series(recent), as_of=AS_OF)
    assert recent_metrics["dividendCutRecent"] is True
    assert recent_metrics["yearsDividendRaised"] == 4

    # 1.00 to 0.50 over five years.
    ends = [
        (datetime.date(2020, 6, 1), 2.00),
        (datetime.date(2025, 6, 1), 1.00),
    ]
    cagr = main.dividend_history_metrics(_series(ends), as_of=AS_OF)
    assert cagr["dividendCagr5y"] == -12.94
    # The years in between were never observed, so this is not called a cut.
    assert cagr["dividendCutRecent"] is False

    assert main.dividend_history_metrics(None)["yearsDividendPaid"] is None
    assert main.dividend_history_metrics(None)["dividendCutRecent"] is False
    empty = main.dividend_history_metrics(_series([]), as_of=AS_OF)
    assert empty["yearsDividendPaid"] == 0
    assert empty["yearsDividendRaised"] == 0
    assert empty["dividendCagr5y"] is None
    assert empty["dividendCutRecent"] is False

    class Boom:
        def __len__(self):
            return 1

        def items(self):
            raise RuntimeError("unreadable")

    broken = main.dividend_history_metrics(Boom(), as_of=AS_OF)
    assert broken["yearsDividendPaid"] is None
    assert broken["dividendCutRecent"] is False

    # 31 Dec in the exchange timezone stays in that year.
    tz = pd.Series(
        [1.0],
        index=pd.DatetimeIndex([pd.Timestamp("2025-12-31 18:00", tz="America/New_York")]),
    )
    zoned = main.dividend_history_metrics(tz, as_of=AS_OF)
    assert zoned["yearsDividendPaid"] == 1


def test_sector_basis_and_assemble_never_penalizes_a_gap():
    assert main.cash_payout_basis("Real Estate", "REIT - Mortgage") == "ffo"
    assert main.cash_payout_basis("Financial Services", "Banks - Regional") == "skipped"
    assert main.cash_payout_basis("Financial Services", "Insurance - Life") == "skipped"
    assert main.cash_payout_basis("Financial Services", "Insurance Brokers") == "fcf"
    assert main.cash_payout_basis("Technology", "Software") == "fcf"

    insurer = main.assemble_sustainability(
        "Financial Services", "Insurance - Diversified", None, None,
    )
    assert insurer["fcfPayoutBasis"] == "skipped"
    assert insurer["fcfPayout"] is None
    assert insurer["fcfDeficit"] is False
    assert insurer["dividendCutRecent"] is False
    assert insurer["yearsDividendPaid"] is None

    frame = _frame({
        "Free Cash Flow": [-5.0],
        "Common Stock Dividend Paid": [-1.0],
    }, ["2024-12-31"])
    # Even a scary statement is ignored for a bank.
    bank = main.assemble_sustainability("Financial Services", "Banks - Diversified", None, frame)
    assert bank["fcfPayoutBasis"] == "skipped"
    assert bank["fcfDeficit"] is False

    ordinary = main.assemble_sustainability("Utilities", "Utilities - Regulated Electric", None, frame)
    assert ordinary["fcfDeficit"] is True
    assert ordinary["yearsDividendPaid"] is None


def test_basis_matches_javascript():
    cases = [
        ("Real Estate", "REIT - Retail", "ffo"),
        ("Real Estate", "REIT - Mortgage", "ffo"),
        ("Financial Services", "Banks - Regional", "skipped"),
        ("Financial Services", "Banks - Diversified", "skipped"),
        ("Financial Services", "Credit Services", "skipped"),
        ("Financial Services", "Insurance - Life", "skipped"),
        ("Financial Services", "Insurance - Diversified", "skipped"),
        ("Financial Services", "Insurance - Reinsurance", "skipped"),
        ("Financial Services", "Reinsurance", "skipped"),
        ("Financial Services", "Insurance Brokers", "fcf"),
        ("Technology", "Software - Infrastructure", "fcf"),
        ("Utilities", "Utilities - Regulated Electric", "fcf"),
        ("Energy", "Oil & Gas Integrated", "fcf"),
        ("", "", "fcf"),
    ]
    script = r"""
const fs = require("fs");
const { cashPayoutBasis } = require("./static/scoring.js");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map((c) => cashPayoutBasis(c[0], c[1]))));
"""
    proc = subprocess.run(
        ["node", "-e", script],
        input=json.dumps([[sector, industry] for sector, industry, _ in cases]),
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    js = json.loads(proc.stdout)
    for (sector, industry, expected), got in zip(cases, js):
        py = main.cash_payout_basis(sector, industry)
        assert py == expected == got, (sector, industry, py, got)


class _Recorder:
    def __init__(self):
        self.calls = []
        self.lock = __import__("threading").Lock()

    def add(self, name):
        with self.lock:
            self.calls.append(name)


def _install(recorder, info, cashflow, dividends):
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
            return dividends

        @property
        def cashflow(self):
            recorder.add("cashflow")
            if isinstance(cashflow, Exception):
                raise cashflow
            return cashflow

        @property
        def balance_sheet(self):
            recorder.add("balance_sheet")
            return None

        @property
        def financials(self):
            recorder.add("financials")
            return None

        def history(self, **kwargs):
            recorder.add("history")
            return None

    main.yf.Ticker = FakeTicker
    yahoo_cache.yf.Ticker = FakeTicker


def _info(**overrides):
    base = {
        "quoteType": "EQUITY",
        "longName": "Sample Co",
        "currentPrice": 40.0,
        "currency": "USD",
        "exchange": "NYQ",
        "sector": "Communication Services",
        "industry": "Telecom Services",
        "trailingPE": 12.0,
        "dividendRate": 2.0,
        "payoutRatio": 0.5,
        "priceToBook": 1.5,
        "totalDebt": 100.0,
        "ebitda": 50.0,
    }
    base.update(overrides)
    return base


def test_watchlist_skips_cashflow_for_banks_and_survives_a_bad_statement():
    original = main.yf.Ticker
    yahoo_cache.clear_market_cache()
    try:
        recorder = _Recorder()
        _install(recorder, _info(
            sector="Financial Services",
            industry="Banks - Regional",
            longName="Bank Co",
        ), RuntimeError("cash flow should not be fetched"), None)
        row = asyncio.run(main.watchlist_ticker("BANK", min_yield=4, max_per=15))
        assert "cashflow" not in recorder.calls
        assert row["metrics"]["fcfPayoutBasis"] == "skipped"
        assert row["metrics"]["fcfPayout"] is None
        assert row["scores"]["sustainabilityWarning"] is False

        yahoo_cache.clear_market_cache()
        recorder = _Recorder()
        frame = _frame({
            "Free Cash Flow": [-20.0],
            "Net Income From Continuing Operations": [100.0],
            "Depreciation And Amortization": [40.0],
            "Common Stock Dividend Paid": [-28.0],
        }, ["2024-12-31"])
        payments = []
        for year, amount in ((2023, 0.4), (2024, 0.5), (2025, 0.6)):
            payments.extend(_quarters(year, amount))
        _install(recorder, _info(
            sector="Real Estate",
            industry="REIT - Retail",
            longName="Sample REIT",
        ), frame, _series(payments))
        reit = asyncio.run(main.watchlist_ticker("O", min_yield=4, max_per=15))
        assert "cashflow" in recorder.calls
        assert reit["metrics"]["fcfPayoutBasis"] == "ffo"
        assert reit["metrics"]["fcfPayout"] == 20.0
        assert reit["metrics"]["fcfDeficit"] is False
        assert reit["scores"]["sustainabilityWarning"] is False
        before = len(recorder.calls)
        again = asyncio.run(main.watchlist_ticker("O"))
        assert again["metrics"]["fcfPayout"] == 20.0
        assert len(recorder.calls) == before

        yahoo_cache.clear_market_cache()
        recorder = _Recorder()
        _install(
            recorder,
            _info(longName="Broken Cash Flow"),
            RuntimeError("yahoo failed"),
            _series(_quarters(2025, 0.4)),
        )
        broken = asyncio.run(main.watchlist_ticker("BROKEN", min_yield=4, max_per=15))
        assert broken["metrics"]["fcfPayout"] is None
        assert broken["metrics"]["fcfDeficit"] is False
        assert broken["scores"]["sustainabilityWarning"] is False
        assert broken["metrics"]["yearsDividendPaid"] == main.dividend_history_metrics(
            _series(_quarters(2025, 0.4))
        )["yearsDividendPaid"]
    finally:
        main.yf.Ticker = original
        yahoo_cache.yf.Ticker = original
        yahoo_cache.clear_market_cache()


if __name__ == "__main__":
    test_fcf_payout_uses_the_latest_common_dividend()
    test_fcf_falls_back_when_the_latest_column_is_incomplete()
    test_fcf_is_rebuilt_from_operating_cash_and_capex()
    test_negative_free_cash_flow_is_a_deficit_not_an_older_year()
    test_missing_cash_flow_is_not_a_penalty()
    test_duplicate_dividend_row_uses_the_first_number()
    test_reit_uses_ffo_and_ignores_negative_free_cash_flow()
    test_dividend_streaks_ignore_the_current_year_and_specials()
    test_flat_band_splits_and_suspension()
    test_calendar_count_shift_is_not_a_cut()
    test_shapes_from_real_dividend_patterns()
    test_gaps_cagr_and_missing_history()
    test_sector_basis_and_assemble_never_penalizes_a_gap()
    test_basis_matches_javascript()
    test_watchlist_skips_cashflow_for_banks_and_survives_a_bad_statement()
    print("All sustainability tests passed.")

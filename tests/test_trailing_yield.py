"""Trailing 12-month dividend yield from ex-dividend history.

The forward yield is the existing figure (latest dividend annualised / price).
The trailing yield is the sum of dividends whose ex-date falls in the last
365 days, divided by the current price. Yahoo's trailingAnnualDividendYield
is not used.

A gap is worth a note when the two differ by more than 1 percentage point
or by more than 20% of the larger yield. Exactly 1.0 point does not qualify
on its own, and exactly 20% does not either, but a 1-point gap on a yield
below 5% still qualifies because it is more than 20% of the larger yield.
A single payment at least twice the median of the others is a possible
special dividend; a repeated higher amount is not.

Run: python tests/test_trailing_yield.py
"""
import datetime
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


AS_OF = datetime.date(2026, 11, 27)


def _summary(divs, price, forward):
    return main.summarize_dividend_yields(divs, price, forward, as_of=AS_OF)


def test_thresholds_are_documented():
    assert main.YIELD_GAP_ABS_POINTS == 1.0
    assert main.YIELD_GAP_REL == 0.20
    assert main.SPECIAL_DIVIDEND_MULTIPLE == 2.0
    assert main.TRAILING_WINDOW_DAYS == 365


def test_trailing_yield_raise():
    """Quarterly dividend raised mid-window. The new amount is paid twice,
    so it is a raise, not a special. A large payment exactly 365 days
    earlier (21:00 New York, which is the next day in UTC) stays out.
    """
    divs = pd.Series(
        [10.00, 0.50, 0.50, 0.75, 0.75],
        index=[
            pd.Timestamp("2025-11-27 21:00:00", tz="America/New_York"),
            pd.Timestamp("2025-12-01 09:30:00", tz="America/New_York"),
            pd.Timestamp("2026-03-01 09:30:00", tz="America/New_York"),
            pd.Timestamp("2026-06-01 09:30:00", tz="America/New_York"),
            pd.Timestamp("2026-09-01 09:30:00", tz="America/New_York"),
        ],
    )
    # Latest payment 0.75 annualised (x4) / price 40 = 7.50% forward.
    # Trailing sum 0.50+0.50+0.75+0.75 = 2.50 / 40 = 6.25%.
    summary = _summary(divs, 40, 7.50)
    assert summary["trailingDividendYield"] == 6.25
    gap = summary["yieldComparison"]
    assert gap["material"] is True
    assert gap["direction"] == "forward_higher"
    assert gap["possibleSpecialDividend"] is False


def test_repeated_higher_dividend_is_not_a_special():
    """Doubling the dividend and paying it twice is a raise, not a special."""
    divs = {
        datetime.datetime(2025, 12, 1): 0.50,
        datetime.datetime(2026, 3, 1): 0.50,
        datetime.datetime(2026, 6, 1): 1.00,
        datetime.datetime(2026, 9, 1): 1.00,
    }
    summary = _summary(divs, 50, 8.00)
    assert summary["trailingDividendYield"] == 6.00
    assert summary["yieldComparison"]["direction"] == "forward_higher"
    assert summary["yieldComparison"]["possibleSpecialDividend"] is False


def test_trailing_yield_cut():
    divs = {
        datetime.datetime(2025, 12, 1): 1.00,
        datetime.datetime(2026, 3, 1): 1.00,
        datetime.datetime(2026, 6, 1): 0.40,
        datetime.datetime(2026, 9, 1): 0.40,
    }
    # Forward uses the new 0.40 annualised: 1.60 / 40 = 4%.
    # Trailing sum 2.80 / 40 = 7%.
    summary = _summary(divs, 40, 4.00)
    assert summary["trailingDividendYield"] == 7.00
    gap = summary["yieldComparison"]
    assert gap["material"] is True
    assert gap["direction"] == "trailing_higher"
    assert gap["possibleSpecialDividend"] is False


def test_trailing_yield_special():
    divs = {
        datetime.datetime(2026, 2, 15): 0.40,
        datetime.datetime(2026, 5, 15): 0.40,
        datetime.datetime(2026, 8, 15): 0.40,
        datetime.datetime(2026, 9, 1): 2.00,
    }
    # Forward stays on the regular 0.40 annualised: 1.60 / 50 = 3.20%.
    # Trailing sum 3.20 / 50 = 6.40%. The 2.00 payment is the only outlier.
    summary = _summary(divs, 50, 3.20)
    assert summary["trailingDividendYield"] == 6.40
    gap = summary["yieldComparison"]
    assert gap["material"] is True
    assert gap["direction"] == "trailing_higher"
    assert gap["possibleSpecialDividend"] is True


def test_tiny_payment_does_not_look_like_a_special():
    """A token amount beside two ordinary instalments is not a special,
    and neither is the larger of those two when it is under 2x the other.
    """
    divs = {
        datetime.datetime(2026, 1, 12): 0.25,
        datetime.datetime(2026, 5, 21): 0.005,
        datetime.datetime(2026, 7, 6): 0.40,
    }
    summary = _summary(divs, 20, 3.25)
    assert summary["yieldComparison"]["possibleSpecialDividend"] is False

    two = {
        datetime.datetime(2026, 3, 1): 0.50,
        datetime.datetime(2026, 9, 1): 2.00,
    }
    summary = _summary(two, 40, 5.00)
    assert summary["yieldComparison"]["possibleSpecialDividend"] is True


def test_trailing_yield_no_payments():
    summary = _summary(None, 100, None)
    assert summary["trailingDividendYield"] is None
    assert summary["yieldComparison"]["material"] is False
    assert summary["yieldComparison"]["possibleSpecialDividend"] is False

    summary = _summary({}, 100, 3.0)
    assert summary["trailingDividendYield"] is None
    assert summary["yieldComparison"]["material"] is False

    # Exactly 365 days before as_of, plus an older payment: both outside.
    outside = {
        datetime.datetime(2025, 11, 27): 1.50,
        datetime.datetime(2020, 6, 1): 1.50,
    }
    summary = _summary(outside, 100, 4.0)
    assert summary["trailingDividendYield"] is None
    assert summary["yieldComparison"]["material"] is False


def test_day_after_boundary_is_inside_the_window():
    divs = {datetime.datetime(2025, 11, 28): 1.00}
    summary = _summary(divs, 100, None)
    assert summary["trailingDividendYield"] == 1.00


def test_gap_threshold_is_one_point_or_twenty_percent():
    # Trailing 5% (one 5.00 payment, price 100). A forward yield of 6% is
    # exactly 1.0 point away and only 16.7% relative, so neither rule fires.
    wide = {datetime.datetime(2026, 6, 1): 5.00}
    exact_point = _summary(wide, 100, 6.0)
    assert exact_point["trailingDividendYield"] == 5.00
    assert exact_point["yieldComparison"]["material"] is False

    over_point = _summary(wide, 100, 6.01)
    assert over_point["yieldComparison"]["material"] is True
    assert over_point["yieldComparison"]["direction"] == "forward_higher"

    # Trailing 2%. |2.00 - 1.60| / 2.00 = 20% exactly, absolute gap 0.40.
    narrow = {datetime.datetime(2026, 6, 1): 2.00}
    exact_relative = _summary(narrow, 100, 1.60)
    assert exact_relative["trailingDividendYield"] == 2.00
    assert exact_relative["yieldComparison"]["material"] is False

    # |2.00 - 1.59| / 2.00 = 20.5%, still under 1 point.
    over_relative = _summary(narrow, 100, 1.59)
    assert over_relative["yieldComparison"]["material"] is True
    assert over_relative["yieldComparison"]["direction"] == "trailing_higher"


if __name__ == "__main__":
    test_thresholds_are_documented()
    test_trailing_yield_raise()
    test_repeated_higher_dividend_is_not_a_special()
    test_trailing_yield_cut()
    test_trailing_yield_special()
    test_tiny_payment_does_not_look_like_a_special()
    test_trailing_yield_no_payments()
    test_day_after_boundary_is_inside_the_window()
    test_gap_threshold_is_one_point_or_twenty_percent()
    print("All trailing yield tests passed.")

"""Dividends received use shares held before each ex-dividend date.

Run: python tests/test_dividend_shares.py
"""
import asyncio
import datetime
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


def _by_date(rows):
    return {row["date"]: row for row in rows}


def _tx(date, shares, side="buy"):
    return {"date": date, "shares": shares, "side": side}


def test_second_purchase_does_not_inflate_earlier_payment():
    """Buy 10 in January, dividend in March, buy 10 more in May, dividend in June.
    March must use 10 shares and June 20. Selling everything in August keeps
    both payments and drops a later September dividend.
    """
    transactions = main.normalize_transactions([
        _tx("2024-01-15", 10),
        _tx("2024-05-15", 10),
        _tx("2024-08-01", 20, "sell"),
    ])
    divs = {
        datetime.datetime(2024, 3, 10): 1.00,
        datetime.datetime(2024, 6, 10): 1.50,
        datetime.datetime(2024, 9, 10): 1.50,
    }
    rows = _by_date(main.calculate_dividends_received(divs, transactions))

    assert list(rows) == ["2024-03-10", "2024-06-10"]
    assert rows["2024-03-10"]["shares"] == 10
    assert rows["2024-03-10"]["totalAmount"] == 10.00
    assert rows["2024-06-10"]["shares"] == 20
    assert rows["2024-06-10"]["totalAmount"] == 30.00
    assert "2024-09-10" not in rows
    assert round(sum(r["totalAmount"] for r in rows.values()), 2) == 40.00


def test_partial_sale_reduces_shares_only_after_the_sale():
    transactions = main.normalize_transactions([
        _tx("2024-01-15", 10),
        _tx("2024-04-01", 4, "sell"),
    ])
    divs = {
        datetime.datetime(2024, 3, 10): 0.50,
        datetime.datetime(2024, 6, 10): 0.50,
    }
    rows = _by_date(main.calculate_dividends_received(divs, transactions))
    assert rows["2024-03-10"]["shares"] == 10
    assert rows["2024-03-10"]["totalAmount"] == 5.00
    assert rows["2024-06-10"]["shares"] == 6
    assert rows["2024-06-10"]["totalAmount"] == 3.00


def test_buy_on_ex_date_does_not_qualify_sale_on_ex_date_still_does():
    ex = datetime.datetime(2024, 3, 10)
    bought_on_ex = main.normalize_transactions([_tx("2024-03-10", 10)])
    assert main.calculate_dividends_received({ex: 1.0}, bought_on_ex) == []

    sold_on_ex = main.normalize_transactions([
        _tx("2024-01-15", 10),
        _tx("2024-03-10", 10, "sell"),
    ])
    rows = main.calculate_dividends_received({ex: 1.0}, sold_on_ex)
    assert rows[0]["shares"] == 10
    assert rows[0]["totalAmount"] == 10.00


def test_yfinance_timestamp_uses_exchange_wall_date():
    """yfinance stamps dividends at 09:30 exchange time on the ex-date."""
    ts = pd.Timestamp("2024-05-10 09:30:00", tz="America/New_York")
    divs = pd.Series([0.25], index=[ts])
    held = main.normalize_transactions([
        _tx("2024-05-10", 10),   # same calendar day: not eligible
        _tx("2024-01-15", 10),
    ])
    rows = main.calculate_dividends_received(divs, held)
    assert rows[0]["date"] == "2024-05-10"
    assert rows[0]["shares"] == 10
    assert rows[0]["totalAmount"] == 2.50


def test_missing_side_is_a_buy_so_old_records_still_count():
    transactions = main.normalize_transactions([
        {"date": "2024-01-15", "shares": 8},
    ])
    rows = main.calculate_dividends_received(
        {datetime.datetime(2024, 3, 10): 2.0},
        transactions,
    )
    assert rows[0]["shares"] == 8
    assert rows[0]["totalAmount"] == 16.00


def test_legacy_query_is_a_single_buy():
    class FakeTicker:
        def __init__(self, symbol):
            self.info = {"currency": "USD"}
            self.dividends = {
                datetime.datetime(2024, 3, 10): 1.0,
                datetime.datetime(2024, 6, 10): 1.0,
            }

    original = main.yf.Ticker
    main.yf.Ticker = FakeTicker
    try:
        result = asyncio.run(main.dividends_received_endpoint(
            symbol="TEST",
            from_date="2024-01-15",
            shares=10,
        ))
    finally:
        main.yf.Ticker = original

    rows = _by_date(result["dividends"])
    assert result["totalReceived"] == 20.00
    assert rows["2024-03-10"]["shares"] == 10
    assert rows["2024-06-10"]["shares"] == 10


def test_endpoint_uses_full_buy_and_sell_history():
    class FakeTicker:
        def __init__(self, symbol):
            self.info = {"currency": "EUR"}
            self.dividends = {
                datetime.datetime(2024, 3, 10): 1.0,
                datetime.datetime(2024, 6, 10): 1.5,
                datetime.datetime(2024, 9, 10): 1.5,
            }

    payload = [
        _tx("2024-01-15", 10),
        _tx("2024-05-15", 10),
        _tx("2024-08-01", 20, "sell"),
    ]
    original = main.yf.Ticker
    main.yf.Ticker = FakeTicker
    try:
        result = asyncio.run(main.dividends_received_endpoint(
            symbol="aapl",
            transactions=json.dumps(payload),
        ))
    finally:
        main.yf.Ticker = original

    rows = _by_date(result["dividends"])
    assert result["symbol"] == "AAPL"
    assert result["currency"] == "EUR"
    assert rows["2024-03-10"]["shares"] == 10
    assert rows["2024-06-10"]["shares"] == 20
    assert "2024-09-10" not in rows
    assert result["totalReceived"] == 40.00


def _print_scenario():
    transactions = main.normalize_transactions([
        _tx("2024-01-15", 10),
        _tx("2024-05-15", 10),
        _tx("2024-08-01", 20, "sell"),
    ])
    divs = {
        datetime.datetime(2024, 3, 10): 1.00,
        datetime.datetime(2024, 6, 10): 1.50,
        datetime.datetime(2024, 9, 10): 1.50,
    }
    rows = main.calculate_dividends_received(divs, transactions)
    print("Scenario: buy 10 on 2024-01-15, dividend 2024-03-10 ($1.00),")
    print("          buy 10 on 2024-05-15, dividend 2024-06-10 ($1.50),")
    print("          sell 20 on 2024-08-01, dividend 2024-09-10 ($1.50) excluded")
    for row in rows:
        print(f"  {row['date']}  shares={row['shares']:.0f}  total={row['totalAmount']:.2f}")
    print(f"  total received={sum(r['totalAmount'] for r in rows):.2f}")


if __name__ == "__main__":
    test_second_purchase_does_not_inflate_earlier_payment()
    test_partial_sale_reduces_shares_only_after_the_sale()
    test_buy_on_ex_date_does_not_qualify_sale_on_ex_date_still_does()
    test_yfinance_timestamp_uses_exchange_wall_date()
    test_missing_side_is_a_buy_so_old_records_still_count()
    test_legacy_query_is_a_single_buy()
    test_endpoint_uses_full_buy_and_sell_history()
    _print_scenario()
    print("All dividend share tests passed.")

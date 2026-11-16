


"""Step 1b tests: the checks that decide whether the sheet may be loaded. No database needed."""
import pandas as pd

from monthly_pack.load_monthly import COLUMNS, validate


def good_rows() -> pd.DataFrame:
    row = {"VendorName": "ACME", "Brand": 1, "Description": "Test Vodka", "Size": "750mL",
           "YearMonth": pd.Timestamp("2024-01-01"), "SalesYear": 2024, "SalesMonth": 1,
           "MonthlyDemand": 10, "MonthlyRevenue": 99.9, "TradingDays": 5, "StoreCount": 2,
           "AvgDailyDemand": 2.0}
    return pd.DataFrame([row, {**row, "SalesMonth": 2, "YearMonth": pd.Timestamp("2024-02-01")}])


def test_good_sheet_has_no_problems():
    assert validate(good_rows()) == []


def test_missing_column_is_reported():
    assert validate(good_rows().drop(columns=["MonthlyRevenue"])) == ["missing columns: MonthlyRevenue"]


def test_empty_sheet_is_refused():
    assert validate(pd.DataFrame(columns=list(COLUMNS))) == ["the sheet has no rows"]


def test_bad_month_and_negative_revenue_are_both_reported():
    df = good_rows()
    df.loc[0, "SalesMonth"] = 13
    df.loc[1, "MonthlyRevenue"] = -5
    assert validate(df) == ["SalesMonth outside 1-12", "negative MonthlyRevenue"]
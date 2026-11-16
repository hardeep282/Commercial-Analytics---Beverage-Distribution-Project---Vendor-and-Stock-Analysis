


"""Step 1b - load the monthly demand sheet from the Excel workbook into SQL Server.

One-off (and safe to re-run): after this, the pack reads everything from one place.
It only creates or replaces dbo.monthly_demand. No other table or view is touched.

Usage:  python -m monthly_pack.load_monthly
"""
from __future__ import annotations

import sys

import pandas as pd
from sqlalchemy import Date, Float, Integer, String, text

from monthly_pack import db

WORKBOOK = "Excel Analysis/Vendor_Summary.xlsx"
SHEET = "output_monthly_demand"
TABLE = "monthly_demand"

# Column name -> SQL type. Also the list of columns the sheet must have.
COLUMNS = {
    "VendorName": String(200),
    "Brand": Integer(),
    "Description": String(200),
    "Size": String(50),
    "YearMonth": Date(),
    "SalesYear": Integer(),
    "SalesMonth": Integer(),
    "MonthlyDemand": Integer(),
    "MonthlyRevenue": Float(),
    "TradingDays": Integer(),
    "StoreCount": Integer(),
    "AvgDailyDemand": Float(),
}


def validate(df: pd.DataFrame) -> list[str]:
    """Problems that should stop the load. An empty list means the sheet is fit to load."""
    problems = []
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        return [f"missing columns: {', '.join(missing)}"]
    if df.empty:
        return ["the sheet has no rows"]
    if df[["VendorName", "Brand", "YearMonth", "MonthlyRevenue"]].isna().any().any():
        problems.append("blank values in VendorName, Brand, YearMonth or MonthlyRevenue")
    if not df["SalesMonth"].between(1, 12).all():
        problems.append("SalesMonth outside 1-12")
    if (df["MonthlyRevenue"] < 0).any():
        problems.append("negative MonthlyRevenue")
    return problems


def load(workbook: str = WORKBOOK) -> None:
    df = pd.read_excel(workbook, sheet_name=SHEET)
    print(f"Read {len(df):,} rows from '{SHEET}' in {workbook}")

    problems = validate(df)
    if problems:
        print("NOT LOADED. Problems found:")
        for p in problems:
            print("  -", p)
        sys.exit(1)

    df = df[list(COLUMNS)].copy()
    df["YearMonth"] = pd.to_datetime(df["YearMonth"]).dt.date

    if db.best_driver() == db.LEGACY_DRIVER:
        print("NOT LOADED. Only the old 'SQL Server' ODBC driver is installed, and it cannot")
        print("create tables through SQLAlchemy. Install 'ODBC Driver 18 for SQL Server'")
        print("from Microsoft (free), then run this again.")
        sys.exit(1) 
        
    engine = db.get_engine()
    # 12 columns x 150 rows = 1,800 values per INSERT, under SQL Server's limit of 2,100.
    df.to_sql(TABLE, engine, schema="dbo", if_exists="replace", index=False,
              dtype=COLUMNS, chunksize=150, method="multi")

    with engine.connect() as conn:
        rows, revenue = conn.execute(
            text(f"SELECT COUNT(*), SUM(MonthlyRevenue) FROM dbo.{TABLE}")
        ).one()
    print(f"Wrote dbo.{TABLE}: {rows:,} rows, revenue ${revenue:,.0f}")
    if rows != len(df) or abs(revenue - df["MonthlyRevenue"].sum()) > 1:
        print("MISMATCH between the sheet and the table. Do not use the table.")
        sys.exit(1)
    print("Round-trip check passed: the table matches the sheet.")

    by_month = df.groupby("SalesMonth")["MonthlyRevenue"].sum()
    print("\nRevenue by month ($M):")
    print("  " + "  ".join(f"{m}:{v / 1e6:.1f}" for m, v in by_month.items()))
    print(f"\nMonths: {df['SalesMonth'].nunique()}   SKUs: {df['Brand'].nunique():,}"
          f"   vendor names: {df['VendorName'].nunique()}")


if __name__ == "__main__":
    load(sys.argv[1] if len(sys.argv) > 1 else WORKBOOK)


"""Step 1 - connect to SQL Server and read the views the pack needs.

Everything else in the pack gets its data through `read_view()`, so this is the only file
that knows where the database is. To point the pack at another server, set DB_URL in .env;
nothing else changes.
"""
from __future__ import annotations

import os
from urllib.parse import quote_plus

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()  # reads .env in the project folder, if there is one

# The same local database vendor_insights.py uses: SQL Server Express, Windows login.
DEFAULT_ODBC = (
    "DRIVER={SQL Server};"
    "SERVER=.\\SQLEXPRESS;"
    "DATABASE=Vendor_sales;"
    "Trusted_Connection=yes;"
)

# The only views the pack is allowed to read. A name that isn't here is refused, so no
# typo or stray input can ever be pasted into a SQL statement.
PACK_VIEWS = (
    "vw_ProfitLeakage",         # leakage per vendor: controllable vs excise
    "vw_VendorRevenueSummary",  # revenue, gross profit, blended margin per vendor
    "vw_VendorTiering",         # Tier 1/2/3 per vendor
    "vw_ParetoAnalysis",        # cumulative revenue share (the 80/20 view)
    "vw_LogisticsCostSummary",  # freight and excise as % of revenue
    "vw_PortfolioHealth",       # one row per SKU: loss-making, dead stock, etc.
)


def connection_url() -> str:
    """DB_URL from .env if set, otherwise the local SQL Server Express database."""
    return os.environ.get("DB_URL") or "mssql+pyodbc:///?odbc_connect=" + quote_plus(DEFAULT_ODBC)


def get_engine() -> Engine:
    """An engine is a reusable 'how to connect' object; it opens connections when needed."""
    return create_engine(connection_url())


def read_view(name: str, engine: Engine | None = None) -> pd.DataFrame:
    """Read one approved view into a DataFrame."""
    if name not in PACK_VIEWS:
        raise ValueError(f"{name!r} is not one of the pack's views: {', '.join(PACK_VIEWS)}")
    engine = engine or get_engine()
    return pd.read_sql(text(f"SELECT * FROM dbo.{name}"), engine)


def inventory(engine: Engine) -> pd.DataFrame:
    """Every table and view in the database, with its row count."""
    objects = pd.read_sql(
        text(
            "SELECT o.name AS name, o.type_desc AS kind "
            "FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id "
            "WHERE s.name = 'dbo' AND o.type IN ('U', 'V') ORDER BY o.type_desc, o.name"
        ),
        engine,
    )
    counts = []
    with engine.connect() as conn:
        for name in objects["name"]:
            counts.append(conn.execute(text(f"SELECT COUNT(*) FROM dbo.[{name}]")).scalar())
    objects["rows"] = counts
    return objects


if __name__ == "__main__":
    engine = get_engine()
    inv = inventory(engine)
    print(f"Connected. dbo has {len(inv)} tables and views:\n")
    print(inv.to_string(index=False))

    print("\nViews the pack needs:")
    for view in PACK_VIEWS:
        print(f"  {'found  ' if view in set(inv['name']) else 'MISSING'}  {view}")

    monthly = [n for n in inv["name"] if "month" in n.lower()]
    print("\nMonthly data in SQL Server:", ", ".join(monthly) if monthly else "none found")

    df = read_view("vw_ProfitLeakage", engine)
    print(f"\nvw_ProfitLeakage: {len(df)} vendors, total revenue ${df['TotalRevenue'].sum():,.0f}")
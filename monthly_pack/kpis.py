

"""Step 3 - the KPIs for the pack, "as of" a chosen month of 2024.

Two kinds of number, kept apart on purpose:
  monthly trend          revenue and units by month. Uses only months up to the chosen one,
                         so the pack for March knows nothing about April.
  full-year profitability margin, leakage, SKU health, concentration. The cost data exists
                         only as whole-year totals, so these are the same in every month's
                         pack and are always labelled "full year 2024".

Usage:  python -m monthly_pack.kpis 7        (7 = July)
"""
from __future__ import annotations

import calendar
import sys

import pandas as pd

from monthly_pack import checks

TOP_N = 5


# --- monthly trend (from dbo.monthly_demand) ---------------------------------------------


def monthly_kpis(monthly: pd.DataFrame, month: int) -> dict:
    """Headline numbers for one month, using only data up to and including that month."""
    if month not in range(1, 13):
        raise ValueError(f"month must be 1-12, got {month!r}")
    by_month = monthly.groupby("SalesMonth")[["MonthlyRevenue", "MonthlyDemand"]].sum()
    this = monthly[monthly["SalesMonth"] == month]
    revenue = float(by_month.loc[month, "MonthlyRevenue"])
    ytd = by_month.loc[:month]
    previous = float(by_month.loc[month - 1, "MonthlyRevenue"]) if month > 1 else None
    ytd_average = float(ytd["MonthlyRevenue"].mean())
    return {
        "month": month,
        "month_name": calendar.month_name[month],
        "revenue": revenue,
        "units": int(by_month.loc[month, "MonthlyDemand"]),
        "previous_revenue": previous,
        "change": None if previous is None else revenue - previous,
        "change_pct": None if previous is None else (revenue - previous) / previous * 100,
        "ytd_revenue": float(ytd["MonthlyRevenue"].sum()),
        "ytd_units": int(ytd["MonthlyDemand"].sum()),
        "ytd_average_month": ytd_average,
        "vs_ytd_average_pct": (revenue - ytd_average) / ytd_average * 100,
        "rank_so_far": int((ytd["MonthlyRevenue"] > revenue).sum()) + 1,
        "months_so_far": int(len(ytd)),
        "active_skus": int(this["Brand"].nunique()),
        "active_vendors": int(this["VendorName"].nunique()),
    }


def top_vendors(monthly: pd.DataFrame, month: int, n: int = TOP_N) -> pd.DataFrame:
    """The n biggest vendors in the month, with their share of that month's revenue."""
    revenue = monthly[monthly["SalesMonth"] == month].groupby("VendorName")["MonthlyRevenue"].sum()
    top = revenue.sort_values(ascending=False).head(n).reset_index(name="Revenue")
    top["SharePct"] = top["Revenue"] / revenue.sum() * 100
    return top


def movers(monthly: pd.DataFrame, month: int, n: int = TOP_N) -> pd.DataFrame:
    """Vendors whose revenue changed most against the previous month, in dollars.

    Returns the n biggest rises and the n biggest falls. Empty for January (no month before).
    """
    columns = ["VendorName", "Previous", "Revenue", "Change", "ChangePct"]
    if month == 1:
        return pd.DataFrame(columns=columns)
    pair = monthly[monthly["SalesMonth"].isin([month - 1, month])]
    table = pair.pivot_table(index="VendorName", columns="SalesMonth", values="MonthlyRevenue",
                             aggfunc="sum", fill_value=0.0)
    table = table.reindex(columns=[month - 1, month], fill_value=0.0)
    table.columns = ["Previous", "Revenue"]
    table["Change"] = table["Revenue"] - table["Previous"]
    # A vendor with nothing last month has no meaningful percentage, so leave it blank.
    table["ChangePct"] = (table["Change"] / table["Previous"] * 100).where(table["Previous"] > 0)
    ordered = table.sort_values("Change", ascending=False)
    picked = pd.concat([ordered.head(n), ordered.tail(n)])
    return picked[~picked.index.duplicated()].reset_index()[columns]


# --- full-year profitability (from the yearly views) -------------------------------------


def yearly_kpis(data: dict[str, pd.DataFrame]) -> dict:
    """Whole-year 2024 profitability. Each figure says which base it is measured on."""
    leak = data["vw_ProfitLeakage"]       # all rows: 126 vendors
    skus = data["vw_PortfolioHealth"]     # cleaned base: outliers removed
    revenue = float(leak["TotalRevenue"].sum())
    gross_profit = float(leak["TotalGrossProfit"].sum())
    net_profit = float(leak["NetProfitAfterAllCosts"].sum())
    controllable = float(leak["ControllableLeakage"].sum())
    excise = float(leak["ExciseLeakage"].sum())
    cleaned_revenue = float(skus["TotalSalesDollars"].sum())
    loss_making = int((skus["HealthStatus"] == "Loss Making").sum())
    slow = int((skus["TurnoverCategory"] == "Dead Stock Risk").sum())
    return {
        "vendors": int(len(leak)),
        "revenue": revenue,
        "gross_profit": gross_profit,
        "gross_margin_pct": gross_profit / revenue * 100,
        "net_profit": net_profit,
        "net_margin_pct": net_profit / revenue * 100,
        "loss_making_leakage": float(leak["LossMakingLeakage"].sum()),
        "freight_leakage": float(leak["FreightLeakage"].sum()),
        "controllable_leakage": controllable,
        "excise": excise,
        "total_leakage": controllable + excise,
        "total_leakage_pct": (controllable + excise) / revenue * 100,
        "cleaned_skus": int(len(skus)),
        "cleaned_revenue": cleaned_revenue,
        "cleaned_gross_margin_pct": float(skus["GrossProfit"].sum()) / cleaned_revenue * 100,
        "loss_making_skus": loss_making,
        "loss_making_skus_pct": loss_making / len(skus) * 100,
        "slow_turnover_skus": slow,
        "slow_turnover_skus_pct": slow / len(skus) * 100,
    }


def sku_health(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """SKUs and revenue in each health group (cleaned base). The groups add up to 100%."""
    skus = data["vw_PortfolioHealth"]
    table = skus.groupby("HealthStatus").agg(SKUs=("Brand", "size"), Revenue=("TotalSalesDollars", "sum"))
    table["SKUsPct"] = table["SKUs"] / table["SKUs"].sum() * 100
    table["RevenuePct"] = table["Revenue"] / table["Revenue"].sum() * 100
    return table.sort_values("SKUs", ascending=False).reset_index()


def concentration(data: dict[str, pd.DataFrame]) -> dict:
    """How much of the year's revenue sits with a few vendors."""
    revenue = data["vw_VendorRevenueSummary"].set_index("VendorName")["TotalRevenue"]
    share = (revenue / revenue.sum() * 100).sort_values(ascending=False)
    running = share.cumsum()
    # Same rule as vw_ParetoAnalysis: a vendor is in the "top 80% band" while the running
    # total is still at or below 80%. round() guards against 79.9999999 vs 80.
    in_band = int((running.round(6) <= 80).sum())
    return {
        "top_vendor": share.index[0],
        "top_vendor_share_pct": float(share.iloc[0]),
        "top_10_share_pct": float(share.head(10).sum()),
        "vendors_in_top_80_band": in_band,
        "top_80_band_share_pct": float(running.iloc[in_band - 1]) if in_band else 0.0,
        "vendors": int(len(share)),
    }


def build_kpis(data: dict[str, pd.DataFrame], month: int) -> dict:
    """Everything the later steps need, in one dictionary."""
    monthly = data["monthly_demand"]
    return {
        "monthly": monthly_kpis(monthly, month),
        "top_vendors": top_vendors(monthly, month),
        "movers": movers(monthly, month),
        "yearly": yearly_kpis(data),
        "sku_health": sku_health(data),
        "concentration": concentration(data),
    }


# --- printing ----------------------------------------------------------------------------


def money(value: float) -> str:
    """$49.70M for millions, $722,473 below that; a minus sign goes in front: -$8,762."""
    sign = "-" if value < 0 else ""
    value = abs(value)
    return f"{sign}${value / 1e6:,.2f}M" if value >= 1e6 else f"{sign}${value:,.0f}"


def print_kpis(k: dict) -> None:
    m, y, c = k["monthly"], k["yearly"], k["concentration"]
    print(f"\nMONTHLY TREND - {m['month_name']} 2024 (uses January to {m['month_name']} only)")
    print(f"  Revenue            {money(m['revenue'])}   units {m['units']:,}")
    if m["change"] is None:
        print("  vs previous month  n/a (first month of the year)")
    else:
        print(f"  vs previous month  {m['change_pct']:+.1f}%  ({money(m['change'])})")
    print(f"  Year to date       {money(m['ytd_revenue'])}   units {m['ytd_units']:,}")
    print(f"  vs YTD average     {m['vs_ytd_average_pct']:+.1f}%   "
          f"(rank {m['rank_so_far']} of {m['months_so_far']} months so far)")
    print(f"  Active             {m['active_skus']:,} SKUs, {m['active_vendors']} vendors")

    print("\n  Top vendors this month")
    for row in k["top_vendors"].itertuples():
        print(f"    {row.VendorName:<30} {money(row.Revenue):>10}  {row.SharePct:5.1f}%")
    if not k["movers"].empty:
        print("\n  Biggest movers vs previous month")
        for row in k["movers"].itertuples():
            pct = "   new" if pd.isna(row.ChangePct) else f"{row.ChangePct:+6.1f}%"
            print(f"    {row.VendorName:<30} {money(row.Change):>10}  {pct}")

    print("\nFULL-YEAR 2024 PROFITABILITY (same in every month's pack)")
    print(f"  Revenue            {money(y['revenue'])}   all rows, {y['vendors']} vendors")
    print(f"  Gross profit       {money(y['gross_profit'])}   margin {y['gross_margin_pct']:.1f}%")
    print(f"  Net profit         {money(y['net_profit'])}   margin {y['net_margin_pct']:.1f}%")
    print(f"  Leakage            {money(y['total_leakage'])}   {y['total_leakage_pct']:.1f}% of revenue")
    print(f"    controllable     {money(y['controllable_leakage'])}   "
          f"(loss-making {money(y['loss_making_leakage'])} + freight {money(y['freight_leakage'])})")
    print(f"    excise           {money(y['excise'])}   not controllable")
    print(f"  Cleaned base       {y['cleaned_skus']:,} SKUs, {money(y['cleaned_revenue'])}, "
          f"gross margin {y['cleaned_gross_margin_pct']:.1f}%")
    print(f"    loss-making      {y['loss_making_skus']:,} SKUs ({y['loss_making_skus_pct']:.1f}%)")
    print(f"    turnover below 1 {y['slow_turnover_skus']:,} SKUs ({y['slow_turnover_skus_pct']:.1f}%)")

    print("\n  SKU health (cleaned base)")
    for row in k["sku_health"].itertuples():
        print(f"    {row.HealthStatus:<26} {row.SKUs:>6,} SKUs {row.SKUsPct:5.1f}%   "
              f"revenue {row.RevenuePct:5.1f}%")
    print(f"\n  Concentration      {c['top_vendor']} {c['top_vendor_share_pct']:.1f}%, "
          f"top 10 = {c['top_10_share_pct']:.1f}%, "
          f"top {c['vendors_in_top_80_band']} of {c['vendors']} vendors = "
          f"{c['top_80_band_share_pct']:.1f}%")


if __name__ == "__main__":
    month = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    data = checks.load_sources()
    results = checks.run_checks(data)
    if not checks.gate_passes(results):
        print("GATE CLOSED: KPIs not computed. Run  python -m monthly_pack.checks  to see why.")
        sys.exit(1)
    warnings = sum(r.status == "WARN" for r in results)
    print(f"Gate open ({warnings} warnings).")
    print_kpis(build_kpis(data, month))
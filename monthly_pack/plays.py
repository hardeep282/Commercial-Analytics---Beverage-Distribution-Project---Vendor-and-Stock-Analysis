"""Step 4 - size the strategy plays.

Piece 1: before putting a value on any play, check what its number really means.
Piece 2: which vendors hold the unsold stock, so a manager knows who to call first.
"""
from __future__ import annotations

import sys

import pandas as pd

from monthly_pack import checks


def diagnose_loss_makers(skus: pd.DataFrame) -> dict:
    """Why are the loss-making SKUs losing money?

    Gross profit in the data is   sales dollars - purchase dollars   for the year.
    A SKU can be negative for two very different reasons:
      priced below cost   each bottle sells for less than it cost      -> a pricing problem
      overbought          price is fine, but more was bought than sold -> a buying problem
    """
    loss = skus[skus["GrossProfit"] < 0]
    below_cost = loss["ActualPrice"] < loss["PurchasePrice"]
    unsold_units = (loss["TotalPurchaseQuantity"] - loss["TotalSalesQuantity"]).clip(lower=0)
    return {
        "skus": int(len(loss)),
        "loss": float(-loss["GrossProfit"].sum()),
        "priced_below_cost": int(below_cost.sum()),
        "priced_above_cost": int((~below_cost).sum()),
        "loss_on_priced_above_cost": float(-loss.loc[~below_cost, "GrossProfit"].sum()),
        "unsold_units": int(unsold_units.sum()),
        "unsold_stock_at_cost": float((unsold_units * loss["PurchasePrice"]).sum()),
        "median_turnover": float(loss["StockTurnover"].median()),
    }


def unsold_stock(skus: pd.DataFrame) -> pd.DataFrame:
    """Add two columns to each SKU: units bought but not sold in 2024, and their cost."""
    out = skus.copy()
    out["UnsoldUnits"] = (out["TotalPurchaseQuantity"] - out["TotalSalesQuantity"]).clip(lower=0)
    out["UnsoldCost"] = out["UnsoldUnits"] * out["PurchasePrice"]
    return out


def excess_by_vendor(skus: pd.DataFrame) -> pd.DataFrame:
    """Unsold stock (at cost) per vendor, biggest first, with a running share of the total.

    'LossMakingCost' is the part sitting on SKUs that already show a loss for the year:
    the most urgent part, because it hasn't even earned back its purchase cost.
    """
    stock = unsold_stock(skus)
    stock = stock[stock["UnsoldCost"] > 0].copy()
    stock["LossMakingCost"] = stock["UnsoldCost"].where(stock["GrossProfit"] < 0, 0.0)
    table = stock.groupby("VendorName").agg(
        SKUs=("Brand", "size"),
        UnsoldCost=("UnsoldCost", "sum"),
        LossMakingCost=("LossMakingCost", "sum"),
    ).sort_values("UnsoldCost", ascending=False)
    table["SharePct"] = table["UnsoldCost"] / table["UnsoldCost"].sum() * 100
    table["CumulativePct"] = table["SharePct"].cumsum()
    return table.reset_index()


if __name__ == "__main__":
    data = checks.load_sources()
    if not checks.gate_passes(checks.run_checks(data)):
        print("GATE CLOSED: run  python -m monthly_pack.checks  to see why.")
        sys.exit(1)
    d = diagnose_loss_makers(data["vw_PortfolioHealth"])
    print(f"Loss-making SKUs:            {d['skus']:,}   loss ${d['loss']:,.0f}")
    print(f"  priced BELOW unit cost:    {d['priced_below_cost']:,}")
    print(f"  priced ABOVE unit cost:    {d['priced_above_cost']:,}   "
          f"(${d['loss_on_priced_above_cost']:,.0f} of the loss)")
    print(f"  bought but not sold:       {d['unsold_units']:,} units, "
          f"${d['unsold_stock_at_cost']:,.0f} at cost")
    print(f"  median stock turnover:     {d['median_turnover']:.2f}  (1.00 = sold what was bought)")

    by_vendor = excess_by_vendor(data["vw_PortfolioHealth"])
    total = by_vendor["UnsoldCost"].sum()
    for_80 = int((by_vendor["CumulativePct"].round(6) < 80).sum()) + 1
    print(f"\nAll overbought SKUs:         {int(by_vendor['SKUs'].sum()):,} SKUs, "
          f"${total:,.0f} unsold at cost, across {len(by_vendor)} vendors")
    print(f"  {for_80} vendors hold 80% of it. Top 10:")
    for row in by_vendor.head(10).itertuples():
        print(f"    {row.VendorName:<30} ${row.UnsoldCost:>11,.0f}  {row.SharePct:5.1f}%  "
              f"(cumulative {row.CumulativePct:5.1f}%)  on loss-makers ${row.LossMakingCost:>10,.0f}")
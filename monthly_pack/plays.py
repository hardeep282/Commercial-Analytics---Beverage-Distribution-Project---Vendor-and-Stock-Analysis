


"""Step 4 - size the strategy plays.

Piece 1: before putting a value on any play, check what its number really means.
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
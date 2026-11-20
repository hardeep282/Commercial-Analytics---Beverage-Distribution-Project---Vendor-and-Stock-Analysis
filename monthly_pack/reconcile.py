

"""R3 - where do the monthly and yearly revenue figures part ways, product by product?

The two sources are built differently:
  monthly table   from the SALES records, so every product that sold in 2024 is in it
  yearly table    vendor_sales_summary, built FROM purchases LEFT JOIN sales (notebook
                  Vendor_Performance_EDA), so a product that sold but has no 2024 purchase
                  row is left out, and a product with several purchase rows can repeat its sales

This compares them per vendor and product and sorts every dollar of the gap into a reason.
Plain code, no AI. Run:  python -m monthly_pack.reconcile
                    or:  python -m monthly_pack.reconcile "EDRINGTON AMERICAS"
"""
from __future__ import annotations

import sys

import pandas as pd

from monthly_pack import checks
from monthly_pack.kpis import money

KEY = ["VendorName", "Brand"]


def compare(monthly: pd.DataFrame, raw: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    """One row per vendor and product: revenue in each source, the gap, and where it sits."""
    m = (monthly.assign(VendorName=monthly["VendorName"].str.strip().replace(aliases))
         .groupby(KEY).agg(Description=("Description", "first"), Monthly=("MonthlyRevenue", "sum")))
    y = (raw.assign(VendorName=raw["VendorName"].str.strip().replace(aliases))
         .groupby(KEY).agg(YDescription=("Description", "first"), Yearly=("TotalSalesDollars", "sum"),
                           YearlyRows=("TotalSalesDollars", "size")))
    both = m.join(y, how="outer")
    both["Description"] = both["Description"].fillna(both["YDescription"])
    both[["Monthly", "Yearly"]] = both[["Monthly", "Yearly"]].fillna(0.0)
    both["YearlyRows"] = both["YearlyRows"].fillna(0).astype(int)
    both["Gap"] = both["Monthly"] - both["Yearly"]
    both["Reason"] = "same in both"
    both.loc[both["YearlyRows"] == 0, "Reason"] = "sold, but not in the yearly table"
    both.loc[(both["YearlyRows"] > 0) & (both["Monthly"] == 0) & (both["Yearly"] != 0),
             "Reason"] = "in the yearly table only"
    both.loc[(both["YearlyRows"] > 1) & (both["Reason"] == "same in both")
             & (both["Gap"].abs() >= 0.01), "Reason"] = "repeated in the yearly table"
    both.loc[(both["Reason"] == "same in both") & (both["Gap"].abs() >= 0.01), "Reason"] = "different amounts"
    return both.drop(columns="YDescription").reset_index()


def by_reason(rec: pd.DataFrame) -> pd.DataFrame:
    """The total gap split into its reasons. The parts add up to the whole gap."""
    out = rec.groupby("Reason").agg(Products=("Gap", "size"), Gap=("Gap", "sum"))
    return out.sort_values("Gap", key=abs, ascending=False)


def print_report(data: dict[str, pd.DataFrame], vendor: str | None = None) -> None:
    known = set(data["vw_VendorRevenueSummary"]["VendorName"])
    aliases = checks.vendor_aliases(data["vendor_sales_summary"], known)
    rec = compare(data["monthly_demand"], data["vendor_sales_summary"], aliases)

    print(f"Monthly total {money(rec['Monthly'].sum())}   yearly total {money(rec['Yearly'].sum())}"
          f"   gap {money(rec['Gap'].sum())}")
    print(f"\nVendor names matched by vendor number ({len(aliases)}):")
    for other, name in aliases.items():
        print(f"  {other}  ->  {name}")

    print("\nThe gap, by reason (the parts add up to the gap):")
    for reason, r in by_reason(rec).iterrows():
        if reason != "same in both":
            print(f"  {reason:<36} {int(r.Products):>5,} products   {money(r.Gap):>10}")

    shown = rec[rec["Reason"] != "same in both"]
    if vendor:
        shown = shown[shown["VendorName"] == vendor]
        print(f"\n{vendor}: products behind its gap of {money(shown['Gap'].sum())}")
    else:
        print("\nLargest products behind the gap:")
    for r in shown.reindex(shown["Gap"].abs().sort_values(ascending=False).index).head(10).itertuples():
        print(f"  {r.VendorName[:26]:<26} {str(r.Description)[:30]:<30} {money(r.Monthly):>9} vs "
              f"{money(r.Yearly):>9}  gap {money(r.Gap):>9}  ({r.Reason})")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    print_report(checks.load_sources(), args[0] if args else None)
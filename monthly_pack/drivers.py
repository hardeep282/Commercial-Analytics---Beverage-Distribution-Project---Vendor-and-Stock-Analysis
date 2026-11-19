

"""R2 - why did a vendor's revenue move? A driver breakdown for any vendor and month.

    revenue change = volume effect (more or fewer bottles)
                   + price & mix effect (different prices, or a shift to dearer / cheaper products)

then: which products made the change, how widely they sold (stores), and each product's
price and volume across the whole year, so a one-off spike can be told apart from a pattern.

Plain code, no AI. Run:  python -m monthly_pack.drivers "MOET HENNESSY USA INC" 11
"""
from __future__ import annotations

import sys

import pandas as pd

from monthly_pack import db
from monthly_pack.kpis import money

PRODUCT = ["Brand", "Description", "Size"]


def _month_totals(rows: pd.DataFrame) -> pd.DataFrame:
    """Revenue, bottles and store listings per month for the rows given."""
    t = rows.groupby("SalesMonth").agg(Revenue=("MonthlyRevenue", "sum"),
                                       Units=("MonthlyDemand", "sum"),
                                       Stores=("StoreCount", "sum"))
    t["Price"] = t["Revenue"] / t["Units"]
    return t


def price_volume(monthly: pd.DataFrame, vendor: str, month: int) -> dict:
    """Split one vendor's change against the previous month into volume and price & mix.

    volume effect      = (units now - units before) x price before
    price & mix effect = (price now - price before) x units now
    The two always add up to the change exactly (a test proves it).
    """
    if month == 1:
        raise ValueError("January has no previous month in this data")
    t = _month_totals(monthly[monthly["VendorName"] == vendor]).reindex([month - 1, month])
    if t["Units"].isna().any() or (t["Units"] == 0).any():
        raise ValueError(f"{vendor} has no sales in month {month - 1} or {month}")
    before, now = t.loc[month - 1], t.loc[month]
    volume = (now["Units"] - before["Units"]) * before["Price"]
    price_mix = (now["Price"] - before["Price"]) * now["Units"]
    return {
        "vendor": vendor, "month": month,
        "revenue_before": before["Revenue"], "revenue_now": now["Revenue"],
        "change": now["Revenue"] - before["Revenue"],
        "change_pct": (now["Revenue"] / before["Revenue"] - 1) * 100,
        "units_before": int(before["Units"]), "units_now": int(now["Units"]),
        "price_before": before["Price"], "price_now": now["Price"],
        "stores_before": int(before["Stores"]), "stores_now": int(now["Stores"]),
        "volume_effect": volume, "price_mix_effect": price_mix,
    }


def product_moves(monthly: pd.DataFrame, vendor: str, month: int, n: int = 8) -> pd.DataFrame:
    """The products behind the change, biggest first, with each one's share of the total change."""
    rows = monthly[monthly["VendorName"] == vendor]

    def in_month(column: str, m: int) -> pd.Series:
        return rows[rows["SalesMonth"] == m].groupby(PRODUCT)[column].sum()

    out = pd.DataFrame({
        "Before": in_month("MonthlyRevenue", month - 1), "Now": in_month("MonthlyRevenue", month),
        "StoresBefore": in_month("StoreCount", month - 1), "StoresNow": in_month("StoreCount", month),
    }).fillna(0)                       # a product sold in only one of the two months gets 0 for the other
    out["Change"] = out["Now"] - out["Before"]
    out["SharePct"] = out["Change"] / out["Change"].sum() * 100
    out = out.sort_values("Change", ascending=False)
    out["CumSharePct"] = out["SharePct"].cumsum()
    out[["StoresBefore", "StoresNow"]] = out[["StoresBefore", "StoresNow"]].astype(int)
    return out.head(n).reset_index()


def product_year(monthly: pd.DataFrame, brand: int) -> pd.DataFrame:
    """One product's bottles, average price and store listings in every month of the year."""
    t = _month_totals(monthly[monthly["Brand"] == brand])
    return t[["Units", "Price", "Stores"]].round({"Price": 2})


def vendor_growth_rank(monthly: pd.DataFrame, month: int, min_before: float = 500_000) -> pd.DataFrame:
    """Every sizeable vendor's growth against the previous month, fastest first.

    min_before skips small vendors, where a tiny base makes any percentage look huge.
    """
    pair = monthly[monthly["SalesMonth"].isin([month - 1, month])]
    t = pair.pivot_table(index="VendorName", columns="SalesMonth", values="MonthlyRevenue",
                         aggfunc="sum", fill_value=0.0).reindex(columns=[month - 1, month], fill_value=0.0)
    t.columns = ["Before", "Now"]
    t = t[t["Before"] >= min_before]
    t["GrowthPct"] = (t["Now"] / t["Before"] - 1) * 100
    return t.sort_values("GrowthPct", ascending=False).reset_index()


def print_report(monthly: pd.DataFrame, vendor: str, month: int) -> None:
    pv = price_volume(monthly, vendor, month)
    total = _month_totals(monthly)
    portfolio_pct = (total.loc[month, "Revenue"] / total.loc[month - 1, "Revenue"] - 1) * 100
    rank = vendor_growth_rank(monthly, month)
    place = rank.index[rank["VendorName"] == vendor]

    print(f"\n{vendor}: month {month - 1} -> {month}")
    print(f"  Revenue        {money(pv['revenue_before'])} -> {money(pv['revenue_now'])}"
          f"   {pv['change_pct']:+.1f}% ({money(pv['change'])})")
    print(f"  Bottles        {pv['units_before']:,} -> {pv['units_now']:,}"
          f"   {(pv['units_now'] / pv['units_before'] - 1) * 100:+.1f}%")
    print(f"  Avg price      ${pv['price_before']:.2f} -> ${pv['price_now']:.2f}"
          f"   {(pv['price_now'] / pv['price_before'] - 1) * 100:+.1f}%")
    print(f"  Store listings {pv['stores_before']:,} -> {pv['stores_now']:,}"
          f"   (a product selling in a store in that month counts once)")
    print(f"  Volume effect       {money(pv['volume_effect'])}")
    print(f"  Price & mix effect  {money(pv['price_mix_effect'])}")
    print(f"  Whole portfolio     {portfolio_pct:+.1f}% in the same month")
    if len(place):
        print(f"  Growth rank         {place[0] + 1} of {len(rank)} vendors with at least $500,000 the month before")

    moves = product_moves(monthly, vendor, month)
    print(f"\n  Products behind the change (top {len(moves)})")
    for r in moves.itertuples():
        print(f"    {r.Description[:30]:<30} {r.Size:>6}  {money(r.Before):>9} -> {money(r.Now):>9}"
              f"  {money(r.Change):>9}  {r.SharePct:5.1f}% (cum {r.CumSharePct:5.1f}%)"
              f"  stores {r.StoresBefore}->{r.StoresNow}")

    print("\n  The top 3 across the year: bottles and average price")
    for r in moves.head(3).itertuples():
        year = product_year(monthly[monthly["VendorName"] == vendor], r.Brand)
        print(f"    {r.Description} {r.Size}")
        print("      month  " + " ".join(f"{m:>7}" for m in year.index))
        print("      units  " + " ".join(f"{int(u):>7,}" for u in year["Units"]))
        print("      price  " + " ".join(f"{p:>7.2f}" for p in year["Price"]))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    vendor = args[0] if args else "MOET HENNESSY USA INC"
    month = int(args[1]) if len(args) > 1 else 11
    print_report(db.read_view("monthly_demand"), vendor, month)
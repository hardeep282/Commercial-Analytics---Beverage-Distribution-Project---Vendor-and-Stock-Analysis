"""Step 4 - size the strategy plays.

Piece 1: before putting a value on any play, check what its number really means.
Piece 2: which vendors hold the unsold stock, so a manager knows who to call first.
Piece 3: correct piece 1 to use the price actually achieved, not the list price.
Piece 4: put a value on the first play, buying discipline, in three scenarios.
Piece 5: two smaller plays, discount review and freight terms.
Piece 6: vendor concentration (a risk), excise (not controllable), and one ranked table.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

import pandas as pd

from monthly_pack import checks


def diagnose_loss_makers(skus: pd.DataFrame) -> dict:
    """Why are the loss-making SKUs losing money?

    Gross profit in the data is   sales dollars - purchase dollars   for the year.
    A SKU can be negative for two very different reasons:
      sold below cost   bottles sold for less than they cost        -> a pricing problem
      overbought        price is fine, but more was bought than sold -> a buying problem

    "Achieved price" is what customers actually paid on average (sales dollars / bottles
    sold). It can be lower than the list price when bottles are discounted.
    """
    loss = skus[skus["GrossProfit"] < 0]
    sold_any = loss["TotalSalesQuantity"] > 0
    achieved = loss["TotalSalesDollars"] / loss["TotalSalesQuantity"].where(sold_any)
    below_cost = achieved < loss["PurchasePrice"]  # False for SKUs that sold nothing
    # The part of the loss caused by selling below cost: (cost - achieved) on each bottle sold.
    pricing_loss = ((loss["PurchasePrice"] - achieved).clip(lower=0)
                    * loss["TotalSalesQuantity"]).fillna(0.0)
    unsold_units = (loss["TotalPurchaseQuantity"] - loss["TotalSalesQuantity"]).clip(lower=0)
    total_loss = float(-loss["GrossProfit"].sum())
    return {
        "skus": int(len(loss)),
        "loss": total_loss,
        "list_price_below_cost": int((loss["ActualPrice"] < loss["PurchasePrice"]).sum()),
        "sold_below_cost": int(below_cost.sum()),
        "no_sales": int((~sold_any).sum()),
        "loss_from_selling_below_cost": float(pricing_loss.sum()),
        "loss_from_overbuying": total_loss - float(pricing_loss.sum()),
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


# --- the plays ---------------------------------------------------------------------------

# Our assumptions, not facts from the data: the share of next year's excess the buying team
# avoids by ordering closer to what actually sells. Change them here and every number follows.
AVOIDED_SHARE = {"cautious": 0.25, "base": 0.50, "stretch": 0.75}
FOCUS_SHARE_PCT = 60.0  # the play targets the fewest SKUs that hold this share of the excess
# Share of below-cost selling stopped. Lower than it looks: some discounts may be deliberate
# clearance of overbought stock, which is better handled by buying discipline.
DISCOUNT_STOP_SHARE = {"cautious": 0.25, "base": 0.50, "stretch": 0.75}
# Share of the freight bill saved by better rates or fewer, fuller deliveries.
FREIGHT_SAVING_SHARE = {"cautious": 0.05, "base": 0.10, "stretch": 0.15}


# What kind of value a play has. Different kinds can't be added together.
CASH = "Cash freed (one-off)"
PROFIT = "Profit (every year)"
RISK = "Risk to manage (no dollar value)"
FIXED = "Not controllable"
KIND_ORDER = [CASH, PROFIT, RISK, FIXED]


@dataclass
class Play:
    kind: str
    name: str
    problem: str
    action: str
    owner: str
    kpi: str
    pool: float                      # the dollars the play works on
    scenarios: dict[str, float]      # cautious / base / stretch value
    assumptions: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def scenario_values(pool: float, shares: dict[str, float]) -> dict[str, float]:
    """The play's value in each scenario: the pool times that scenario's share."""
    return {name: pool * share for name, share in shares.items()}


def focus_skus(skus: pd.DataFrame, share_pct: float = FOCUS_SHARE_PCT) -> pd.DataFrame:
    """The fewest SKUs that together hold share_pct of the unsold stock, biggest first."""
    stock = unsold_stock(skus)
    stock = stock[stock["UnsoldCost"] > 0].sort_values("UnsoldCost", ascending=False)
    running = stock["UnsoldCost"].cumsum() / stock["UnsoldCost"].sum() * 100
    count = int((running.round(6) < share_pct).sum()) + 1
    return stock.head(count)


def size_buying_discipline(skus: pd.DataFrame) -> Play:
    """Play 1: order closer to what sells, starting with the SKUs holding most of the excess."""
    focus = focus_skus(skus)
    pool = float(focus["UnsoldCost"].sum())
    no_sales = unsold_stock(skus).query("TotalSalesQuantity == 0")
    return Play(
        kind=CASH,
        name="Buying discipline",
        problem=(f"${unsold_stock(skus)['UnsoldCost'].sum():,.0f} of 2024 purchases was still "
                 f"unsold at year end; {len(focus):,} SKUs hold {FOCUS_SHARE_PCT:.0f}% of it."),
        action=("Cut reorder quantities on the focus SKUs to recent sales, starting with the "
                "vendors that hold the most; stop reordering SKUs that sold nothing."),
        owner="Buying / category managers",
        kpi="Stock turnover on the focus SKUs (target: 1.0 or above)",
        pool=pool,
        scenarios=scenario_values(pool, AVOIDED_SHARE),
        assumptions=[
            "Value = cash not tied up in excess stock next year (working capital), not profit.",
            "Avoided share of the excess: " + ", ".join(
                f"{k} {v:.0%}" for k, v in AVOIDED_SHARE.items()) + " (our assumption).",
            "'Unsold' = 2024 purchases minus 2024 sales; the data has no year-end stock count.",
        ],
        details={
            "focus_skus": int(len(focus)),
            "focus_vendors": int(focus["VendorName"].nunique()),
            "no_sales_skus": int(len(no_sales)),
            "no_sales_stock_at_cost": float(no_sales["UnsoldCost"].sum()),
        },
    )


def below_cost_sales(skus: pd.DataFrame) -> pd.DataFrame:
    """SKUs whose achieved price was below unit cost, biggest loss first."""
    sold = skus[skus["TotalSalesQuantity"] > 0].copy()
    sold["AchievedPrice"] = sold["TotalSalesDollars"] / sold["TotalSalesQuantity"]
    below = sold[sold["AchievedPrice"] < sold["PurchasePrice"]].copy()
    below["BelowCostLoss"] = (below["PurchasePrice"] - below["AchievedPrice"]) * below["TotalSalesQuantity"]
    below["DiscountOffListPct"] = (1 - below["AchievedPrice"] / below["ActualPrice"]) * 100
    return below.sort_values("BelowCostLoss", ascending=False)


def size_discount_review(skus: pd.DataFrame) -> Play:
    """Play 2: stop selling bottles for less than they cost, unless it is planned clearance."""
    below = below_cost_sales(skus)
    pool = float(below["BelowCostLoss"].sum())
    top_10_pct = float(below.head(10)["BelowCostLoss"].sum() / pool * 100) if pool else 0.0
    return Play(
        kind=PROFIT,
        name="Discount review",
        problem=(f"{len(below)} SKUs sold below cost on average in 2024, at a median "
                 f"{below['DiscountOffListPct'].median():.0f}% off list; "
                 f"${pool:,.0f} lost on those bottles."),
        action=(f"Review the 10 biggest first ({top_10_pct:.0f}% of the loss). If a discount "
                "was clearing overbought stock, handle it under buying discipline; if not, set "
                "a price floor so no bottle sells below cost."),
        owner="Pricing / category managers",
        kpi="Bottles sold below cost (target: none outside planned clearance)",
        pool=pool,
        scenarios=scenario_values(pool, DISCOUNT_STOP_SHARE),
        assumptions=[
            "Value = the below-cost part of the loss avoided each year (profit).",
            "Share stopped: " + ", ".join(
                f"{k} {v:.0%}" for k, v in DISCOUNT_STOP_SHARE.items()) + " (our assumption).",
            "Achieved price = 2024 sales dollars / bottles sold; the data doesn't say why it was lower.",
        ],
        details={
            "skus": int(len(below)),
            "vendors": int(below["VendorName"].nunique()),
            "top_10_skus_share_pct": top_10_pct,
        },
    )


def size_freight_terms(vendors: pd.DataFrame) -> Play:
    """Play 3: lower the freight bill, starting with the vendors that cost the most to ship."""
    pool = float(vendors["TotalFreight"].sum())
    revenue = float(vendors["TotalRevenue"].sum())
    ranked = vendors.sort_values("TotalFreight", ascending=False)
    running = ranked["TotalFreight"].cumsum() / pool * 100
    for_80 = int((running.round(6) < 80).sum()) + 1
    sizeable = vendors[vendors["TotalRevenue"] >= 10_000]["FreightPctOfRevenue"]
    largest = ranked.iloc[0]
    return Play(
        kind=PROFIT,
        name="Freight terms",
        problem=(f"Freight cost ${pool:,.0f} in 2024, {pool / revenue * 100:.2f}% of revenue; "
                 f"{for_80} vendors account for 80% of it."),
        action="Renegotiate rates or consolidate deliveries with the vendors carrying the biggest freight bills.",
        owner="Logistics / procurement",
        kpi=f"Freight as % of revenue (now {pool / revenue * 100:.2f}%)",
        pool=pool,
        scenarios=scenario_values(pool, FREIGHT_SAVING_SHARE),
        assumptions=[
            "Value = freight cost saved each year (profit).",
            "Saving: " + ", ".join(
                f"{k} {v:.0%}" for k, v in FREIGHT_SAVING_SHARE.items()) + " (our assumption).",
            (f"Freight is already similar across vendors ({sizeable.min():.2f}% to "
             f"{sizeable.max():.2f}% of revenue for vendors over $10K), so there are no "
             "outliers to fix; any saving comes from rates or delivery volume."),
        ],
        details={
            "vendors_for_80_percent": for_80,
            "largest_bill": f"{largest['VendorName']} ${largest['TotalFreight']:,.0f}",
        },
    )


def size_vendor_concentration(vendors: pd.DataFrame) -> Play:
    """Play 4: a risk, not a saving. Too much of the business depends on a few vendors."""
    ranked = vendors.sort_values("TotalRevenue", ascending=False)
    revenue = float(ranked["TotalRevenue"].sum())
    profit = float(ranked["TotalGrossProfit"].sum())
    top, top_10 = ranked.iloc[0], ranked.head(10)
    return Play(
        kind=RISK,
        name="Vendor concentration",
        problem=(f"The top 10 vendors make {top_10['TotalRevenue'].sum() / revenue:.0%} of revenue "
                 f"and {top_10['TotalGrossProfit'].sum() / profit:.0%} of gross profit; "
                 f"{top['VendorName']} alone makes {top['TotalRevenue'] / revenue:.1%} of revenue."),
        action=("Agree a joint business plan with each top-10 vendor (volumes, terms, supply "
                "cover), and keep a second source for the key lines of the largest ones."),
        owner="Commercial director",
        kpi="Revenue share of the top 10 vendors (now "
            f"{top_10['TotalRevenue'].sum() / revenue:.1%}), reviewed each quarter",
        pool=float(top_10["TotalRevenue"].sum()),
        scenarios={},
        assumptions=[
            "No dollar value: concentration is a risk to manage, not a cost to cut.",
            "Being dependent also gives bargaining power both ways; the plan is to manage it, not reduce it at any price.",
        ],
        details={
            "top_vendor": f"{top['VendorName']} ${top['TotalRevenue']:,.0f}",
            "top_10_revenue": float(top_10["TotalRevenue"].sum()),
        },
    )


def excise_note(leakage: pd.DataFrame) -> Play:
    """Not a play: the biggest cost, shown so nobody mistakes it for an opportunity."""
    excise = float(leakage["ExciseLeakage"].sum())
    revenue = float(leakage["TotalRevenue"].sum())
    return Play(
        kind=FIXED,
        name="Excise tax",
        problem=f"Excise tax ${excise:,.0f}, {excise / revenue:.1%} of revenue: by far the largest cost after buying the stock itself.",
        action="None. It is a tax set by government; listed so it isn't mistaken for an opportunity.",
        owner="-",
        kpi="-",
        pool=excise,
        scenarios={},
        assumptions=["Excise depends on what is sold, not on how the business negotiates."],
    )


def all_plays(data: dict[str, pd.DataFrame]) -> list[Play]:
    skus = data["vw_PortfolioHealth"]
    return [
        size_buying_discipline(skus),
        size_discount_review(skus),
        size_freight_terms(data["vw_LogisticsCostSummary"]),
        size_vendor_concentration(data["vw_VendorRevenueSummary"]),
        excise_note(data["vw_ProfitLeakage"]),
    ]


def rank_plays(plays: list[Play]) -> pd.DataFrame:
    """One table, ordered by kind first (cash, profit, risk, not controllable), then by base value.

    Kinds are never added together: $4.7M of cash freed once is not the same as $0.16M of
    profit every year, so the table keeps them in separate groups.
    """
    rows = [{
        "Kind": p.kind,
        "Play": p.name,
        "Cautious": p.scenarios.get("cautious"),
        "Base": p.scenarios.get("base"),
        "Stretch": p.scenarios.get("stretch"),
        "WorksOn": p.pool,
        "Owner": p.owner,
    } for p in plays]
    table = pd.DataFrame(rows)
    table["KindOrder"] = table["Kind"].map(KIND_ORDER.index)
    table = table.sort_values(["KindOrder", "Base"], ascending=[True, False], na_position="last")
    valued = table["Base"].notna()
    table["Priority"] = ""
    table.loc[valued, "Priority"] = [str(i) for i in range(1, int(valued.sum()) + 1)]
    table.loc[table["Kind"] == RISK, "Priority"] = "watch"
    table.loc[table["Kind"] == FIXED, "Priority"] = "-"
    return table.drop(columns="KindOrder").reset_index(drop=True)


def print_ranking(table: pd.DataFrame) -> None:
    def cell(value) -> str:
        return "" if pd.isna(value) else f"${value / 1e6:,.2f}M"

    print("\nPLAYS, RANKED")
    print(f"  {'#':<6}{'Play':<22}{'Cautious':>10}{'Base':>10}{'Stretch':>10}   Kind")
    for row in table.itertuples():
        print(f"  {row.Priority:<6}{row.Play:<22}{cell(row.Cautious):>10}{cell(row.Base):>10}"
              f"{cell(row.Stretch):>10}   {row.Kind}")


def print_play(play: Play) -> None:
    print(f"\nPLAY: {play.name}")
    print(f"  Problem   {play.problem}")
    print(f"  Action    {play.action}")
    print(f"  Owner     {play.owner}")
    print(f"  KPI       {play.kpi}")
    print(f"  Kind      {play.kind}")
    print(f"  Works on  ${play.pool:,.0f}")
    for name, value in play.scenarios.items():
        print(f"    {name:<9} ${value:>12,.0f}")
    for key, value in play.details.items():
        if isinstance(value, str):
            shown = value
        elif key.endswith("_pct"):
            shown = f"{value:.1f}%"
        elif isinstance(value, float):
            shown = f"${value:,.0f}"
        else:
            shown = f"{value:,}"
        print(f"  {key.replace('_', ' '):<23} {shown}")
    print("  Assumptions")
    for line in play.assumptions:
        print(f"    - {line}")


if __name__ == "__main__":
    data = checks.load_sources()
    if not checks.gate_passes(checks.run_checks(data)):
        print("GATE CLOSED: run  python -m monthly_pack.checks  to see why.")
        sys.exit(1)
    d = diagnose_loss_makers(data["vw_PortfolioHealth"])
    print(f"Loss-making SKUs:            {d['skus']:,}   loss ${d['loss']:,.0f}")
    print(f"  list price below cost:     {d['list_price_below_cost']:,}")
    print(f"  sold below cost (achieved price): {d['sold_below_cost']:,}   "
          f"-> ${d['loss_from_selling_below_cost']:,.0f} of the loss (pricing)")
    print(f"  sold nothing at all:       {d['no_sales']:,}")
    print(f"  rest of the loss:          ${d['loss_from_overbuying']:,.0f} (overbuying)")
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

    plays = all_plays(data)
    for play in plays:
        print_play(play)
    print_ranking(rank_plays(plays))
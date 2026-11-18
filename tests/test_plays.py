"""Step 4 tests, on made-up SKUs where the answers can be checked by hand."""
import pandas as pd

from monthly_pack import plays


def test_overbought_and_underpriced_are_told_apart():
    skus = pd.DataFrame({
        # A: price above cost, but bought 100 and sold 20  -> overbought
        # B: list price above cost, but discounted to $8   -> sold below cost
        # C: healthy, not a loss-maker
        # D: bought 5, sold nothing                        -> overbought, no sales
        "PurchasePrice": [10.0, 10.0, 10.0, 10.0],
        "ActualPrice": [15.0, 12.0, 15.0, 15.0],
        "TotalPurchaseQuantity": [100, 10, 10, 5],
        "TotalSalesQuantity": [20, 10, 10, 0],
        "TotalSalesDollars": [300.0, 80.0, 150.0, 0.0],   # B achieved 80 / 10 = $8 a bottle
        "StockTurnover": [0.2, 1.0, 1.0, 0.0],
    })
    skus["GrossProfit"] = skus["TotalSalesDollars"] - skus["PurchasePrice"] * skus["TotalPurchaseQuantity"]
    # A -700, B -20, C +50, D -50
    d = plays.diagnose_loss_makers(skus)
    assert d["skus"] == 3 and d["loss"] == 770.0
    assert d["list_price_below_cost"] == 0          # the list price hides B's problem
    assert d["sold_below_cost"] == 1 and d["no_sales"] == 1
    assert d["loss_from_selling_below_cost"] == 20.0  # B: ($10 - $8) x 10 bottles
    assert d["loss_from_overbuying"] == 750.0
    assert d["unsold_units"] == 85 and d["unsold_stock_at_cost"] == 850.0


def test_excess_by_vendor_ranks_and_splits_the_unsold_stock():
    skus = pd.DataFrame({
        "VendorName": ["ALPHA", "ALPHA", "BETA", "GAMMA"],
        "Brand": [1, 2, 3, 4],
        "PurchasePrice": [10.0, 5.0, 10.0, 10.0],
        "TotalPurchaseQuantity": [100, 10, 30, 10],
        "TotalSalesQuantity": [20, 10, 10, 10],     # GAMMA sold everything: no excess
        "GrossProfit": [-500.0, 20.0, 50.0, 30.0],  # only ALPHA's first SKU is a loss-maker
    })
    table = plays.excess_by_vendor(skus).set_index("VendorName")
    assert list(table.index) == ["ALPHA", "BETA"]              # GAMMA has nothing unsold
    assert table.loc["ALPHA", "UnsoldCost"] == 800.0            # 80 units x $10
    assert table.loc["ALPHA", "LossMakingCost"] == 800.0
    assert table.loc["BETA", "UnsoldCost"] == 200.0 and table.loc["BETA", "LossMakingCost"] == 0.0
    assert table.loc["ALPHA", "SharePct"] == 80.0 and table.loc["BETA", "CumulativePct"] == 100.0


def test_buying_discipline_targets_the_biggest_excess_and_scales_with_the_assumption():
    skus = pd.DataFrame({
        "VendorName": ["ALPHA", "ALPHA", "BETA", "BETA"],
        "Brand": [1, 2, 3, 4],
        "PurchasePrice": [10.0, 10.0, 10.0, 10.0],
        "TotalPurchaseQuantity": [100, 20, 20, 10],
        "TotalSalesQuantity": [40, 10, 10, 0],     # unsold: 60, 10, 10, 10 units
        "GrossProfit": [0.0, 0.0, 0.0, -100.0],
    })
    play = plays.size_buying_discipline(skus)
    # Unsold cost 600 + 100 + 100 + 100 = 900. The single biggest SKU holds 66.7%, enough for 60%.
    assert play.details["focus_skus"] == 1 and play.pool == 600.0
    assert play.scenarios == {"cautious": 150.0, "base": 300.0, "stretch": 450.0}
    assert play.details["no_sales_skus"] == 1 and play.details["no_sales_stock_at_cost"] == 100.0


def test_discount_review_finds_below_cost_sales_on_the_achieved_price():
    skus = pd.DataFrame({
        "VendorName": ["ALPHA", "BETA", "BETA"],
        "Brand": [1, 2, 3],
        "PurchasePrice": [10.0, 10.0, 10.0],
        "ActualPrice": [20.0, 20.0, 20.0],              # every list price is above cost
        "TotalSalesQuantity": [10, 100, 0],
        "TotalSalesDollars": [80.0, 2000.0, 0.0],       # ALPHA achieved $8, BETA $20, last sold none
    })
    play = plays.size_discount_review(skus)
    assert play.details["skus"] == 1 and play.pool == 20.0   # ALPHA: ($10 - $8) x 10 bottles
    assert play.scenarios["base"] == 10.0


def test_freight_terms_values_a_share_of_the_freight_bill():
    vendors = pd.DataFrame({
        "VendorName": ["ALPHA", "BETA", "GAMMA"],
        "TotalRevenue": [100_000.0, 50_000.0, 50_000.0],
        "TotalFreight": [400.0, 300.0, 300.0],
        "FreightPctOfRevenue": [0.4, 0.6, 0.6],
    })
    play = plays.size_freight_terms(vendors)
    assert play.pool == 1000.0
    assert play.scenarios == {"cautious": 50.0, "base": 100.0, "stretch": 150.0}
    assert play.details["vendors_for_80_percent"] == 3        # 40%, 70%, then 100%
    assert play.details["largest_bill"] == "ALPHA $400"


def test_concentration_is_a_risk_with_no_dollar_value():
    vendors = pd.DataFrame({
        "VendorName": [f"V{i}" for i in range(12)],
        "TotalRevenue": [300.0, 200.0] + [50.0] * 10,      # total 1,000
        "TotalGrossProfit": [60.0, 40.0] + [10.0] * 10,    # total 200
    })
    play = plays.size_vendor_concentration(vendors)
    assert play.kind == plays.RISK and play.scenarios == {}
    assert play.pool == 900.0                               # top 10: 300 + 200 + 8 x 50
    assert play.details["top_vendor"] == "V0 $300"


def test_ranking_keeps_kinds_apart_and_orders_by_base_value():
    def make(kind, name, base):
        scen = {} if base is None else {"cautious": base / 2, "base": base, "stretch": base * 1.5}
        return plays.Play(kind=kind, name=name, problem="", action="", owner="", kpi="",
                          pool=0.0, scenarios=scen)

    table = plays.rank_plays([
        make(plays.FIXED, "Tax", None),
        make(plays.PROFIT, "Small yearly", 100.0),
        make(plays.RISK, "Risk", None),
        make(plays.PROFIT, "Big yearly", 300.0),
        make(plays.CASH, "Cash", 50.0),
    ])
    # Cash first (even though smaller), then profit by size, then risk, then not controllable.
    assert list(table["Play"]) == ["Cash", "Big yearly", "Small yearly", "Risk", "Tax"]
    assert list(table["Priority"]) == ["1", "2", "3", "watch", "-"]
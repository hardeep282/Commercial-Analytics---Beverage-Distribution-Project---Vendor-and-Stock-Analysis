"""Step 4 tests, on made-up SKUs where the answers can be checked by hand."""
import pandas as pd

from monthly_pack import plays


def test_overbought_and_underpriced_are_told_apart():
    skus = pd.DataFrame({
        # A: price above cost, but bought 100 and sold 20  -> overbought
        # B: price below cost, bought 10 and sold 10       -> priced below cost
        # C: healthy, not a loss-maker
        "PurchasePrice": [10.0, 10.0, 10.0],
        "ActualPrice": [15.0, 8.0, 15.0],
        "TotalPurchaseQuantity": [100, 10, 10],
        "TotalSalesQuantity": [20, 10, 10],
        "StockTurnover": [0.2, 1.0, 1.0],
    })
    skus["GrossProfit"] = (skus["ActualPrice"] * skus["TotalSalesQuantity"]
                           - skus["PurchasePrice"] * skus["TotalPurchaseQuantity"])  # A -700, B -20, C 50
    d = plays.diagnose_loss_makers(skus)
    assert d["skus"] == 2 and d["loss"] == 720.0
    assert d["priced_below_cost"] == 1 and d["priced_above_cost"] == 1
    assert d["loss_on_priced_above_cost"] == 700.0
    assert d["unsold_units"] == 80 and d["unsold_stock_at_cost"] == 800.0


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
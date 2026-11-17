


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
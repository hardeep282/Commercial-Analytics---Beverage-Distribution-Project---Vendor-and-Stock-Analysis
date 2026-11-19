

"""R2 tests: the driver breakdown, on tiny made-up data worked out by hand."""
import pandas as pd
import pytest

from monthly_pack import drivers


@pytest.fixture
def monthly() -> pd.DataFrame:
    # ALPHA: product 1 sells 10 bottles at $10 in Oct, 30 at $9 in Nov (a cheaper, bigger month).
    #        product 2 sells 5 at $40 in both months.
    # BETA:  steady 100 bottles at $10, small enough to show a different growth rate.
    rows = [
        ("ALPHA", 1, "Fizz", "750mL", 10, 10, 100.0, 4), ("ALPHA", 1, "Fizz", "750mL", 11, 30, 270.0, 6),
        ("ALPHA", 2, "Gold", "750mL", 10, 5, 200.0, 2), ("ALPHA", 2, "Gold", "750mL", 11, 5, 200.0, 2),
        ("BETA", 3, "Plain", "1L", 10, 100, 1000.0, 9), ("BETA", 3, "Plain", "1L", 11, 100, 1000.0, 9),
    ]
    return pd.DataFrame(rows, columns=["VendorName", "Brand", "Description", "Size", "SalesMonth",
                                       "MonthlyDemand", "MonthlyRevenue", "StoreCount"])


def test_volume_and_price_mix_add_up_to_the_change(monthly):
    pv = drivers.price_volume(monthly, "ALPHA", 11)
    # Oct: 15 bottles, $300 -> $20.00 each. Nov: 35 bottles, $470 -> $13.43 each.
    assert pv["change"] == pytest.approx(170.0)
    assert pv["volume_effect"] == pytest.approx(20 * 20.0)                  # 20 more bottles at Oct's price
    assert pv["volume_effect"] + pv["price_mix_effect"] == pytest.approx(pv["change"])
    assert pv["price_mix_effect"] < 0                                        # more of the cheap product


def test_products_are_ranked_by_change_with_their_share(monthly):
    moves = drivers.product_moves(monthly, "ALPHA", 11)
    assert list(moves["Description"]) == ["Fizz", "Gold"]
    assert moves.loc[0, "Change"] == pytest.approx(170.0)
    assert moves.loc[0, "SharePct"] == pytest.approx(100.0)
    assert (moves.loc[0, "StoresBefore"], moves.loc[0, "StoresNow"]) == (4, 6)


def test_growth_rank_skips_small_vendors(monthly):
    rank = drivers.vendor_growth_rank(monthly, 11, min_before=500)
    assert list(rank["VendorName"]) == ["BETA"]                              # ALPHA had only $300 in Oct
    assert rank.loc[0, "GrowthPct"] == pytest.approx(0.0)


def test_january_has_no_previous_month(monthly):
    with pytest.raises(ValueError):
        drivers.price_volume(monthly, "ALPHA", 1)
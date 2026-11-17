

"""Step 3 tests, on a tiny made-up dataset where every answer can be worked out by hand."""
import pandas as pd
import pytest

from monthly_pack import kpis


@pytest.fixture
def monthly() -> pd.DataFrame:
    # ALPHA sells 100 in Jan, 150 in Feb, 150 in Mar. BETA sells 100, 50, 0. GAMMA starts in Mar.
    rows = [
        ("ALPHA", 10, 1, 100.0, 10), ("ALPHA", 10, 2, 150.0, 15), ("ALPHA", 10, 3, 150.0, 15),
        ("BETA", 20, 1, 100.0, 5), ("BETA", 20, 2, 50.0, 2),
        ("GAMMA", 30, 3, 40.0, 4),
    ]
    return pd.DataFrame(rows, columns=["VendorName", "Brand", "SalesMonth", "MonthlyRevenue", "MonthlyDemand"])


@pytest.fixture
def yearly() -> dict[str, pd.DataFrame]:
    leak = pd.DataFrame({
        "VendorName": ["ALPHA", "BETA", "GAMMA"], "TotalRevenue": [700.0, 200.0, 100.0],
        "TotalGrossProfit": [210.0, 60.0, 30.0], "NetProfitAfterAllCosts": [150.0, 40.0, 10.0],
        "LossMakingLeakage": [20.0, 0.0, 0.0], "FreightLeakage": [5.0, 3.0, 2.0],
        "ControllableLeakage": [25.0, 3.0, 2.0], "ExciseLeakage": [40.0, 20.0, 10.0],
    })
    skus = pd.DataFrame({
        "Brand": [10, 11, 20, 30], "TotalSalesDollars": [500.0, 190.0, 200.0, 100.0],
        "GrossProfit": [150.0, 50.0, 60.0, 30.0],
        "HealthStatus": ["Healthy", "Loss Making", "Healthy", "Profitable but Slow"],
        "TurnoverCategory": ["Fast Moving", "Dead Stock Risk", "Fast Moving", "Dead Stock Risk"],
    })
    return {"vw_ProfitLeakage": leak, "vw_PortfolioHealth": skus,
            "vw_VendorRevenueSummary": leak[["VendorName", "TotalRevenue"]]}


def test_february_against_january(monthly):
    k = kpis.monthly_kpis(monthly, 2)
    assert k["revenue"] == 200.0 and k["previous_revenue"] == 200.0
    assert k["change"] == 0.0 and k["change_pct"] == 0.0
    assert k["ytd_revenue"] == 400.0 and k["units"] == 17 and k["active_vendors"] == 2


def test_a_month_never_sees_later_months(monthly):
    # February's pack must give the same answers whether or not March exists.
    without_march = monthly[monthly["SalesMonth"] <= 2]
    assert kpis.monthly_kpis(monthly, 2) == kpis.monthly_kpis(without_march, 2)


def test_january_has_no_previous_month(monthly):
    k = kpis.monthly_kpis(monthly, 1)
    assert k["previous_revenue"] is None and k["change_pct"] is None
    assert kpis.movers(monthly, 1).empty


def test_month_outside_1_to_12_is_refused(monthly):
    with pytest.raises(ValueError, match="month must be 1-12"):
        kpis.monthly_kpis(monthly, 13)


def test_top_vendors_shares_add_up(monthly):
    top = kpis.top_vendors(monthly, 1)
    assert list(top["VendorName"]) == ["ALPHA", "BETA"]
    assert top["SharePct"].sum() == pytest.approx(100.0)


def test_movers_handle_a_vendor_that_stops_and_one_that_starts(monthly):
    m = kpis.movers(monthly, 3).set_index("VendorName")
    assert m.loc["BETA", "Change"] == -50.0 and m.loc["BETA", "ChangePct"] == -100.0
    assert m.loc["GAMMA", "Change"] == 40.0 and pd.isna(m.loc["GAMMA", "ChangePct"])  # new: no %


def test_yearly_margins_and_leakage(yearly):
    y = kpis.yearly_kpis(yearly)
    assert y["revenue"] == 1000.0
    assert y["gross_margin_pct"] == pytest.approx(30.0)
    assert y["net_margin_pct"] == pytest.approx(20.0)
    assert y["total_leakage"] == 100.0 and y["controllable_leakage"] == 30.0
    assert y["loss_making_skus"] == 1 and y["slow_turnover_skus_pct"] == pytest.approx(50.0)


def test_sku_health_groups_add_up_to_100(yearly):
    health = kpis.sku_health(yearly)
    assert health["SKUsPct"].sum() == pytest.approx(100.0)
    assert health["RevenuePct"].sum() == pytest.approx(100.0)


def test_concentration(yearly):
    c = kpis.concentration(yearly)
    assert c["top_vendor"] == "ALPHA" and c["top_vendor_share_pct"] == pytest.approx(70.0)
    assert c["vendors_in_top_80_band"] == 1 and c["top_80_band_share_pct"] == pytest.approx(70.0)


def test_money_formats_negatives_with_the_sign_in_front():
    assert kpis.money(49_700_000) == "$49.70M"
    assert kpis.money(-8762) == "-$8,762"
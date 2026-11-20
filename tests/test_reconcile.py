

"""R3 tests: vendor-name matching and the product-by-product reconciliation, on made-up data."""
import pandas as pd
import pytest

from monthly_pack import checks, reconcile


@pytest.fixture
def raw() -> pd.DataFrame:
    # Vendor 7 appears under two names; the views use "ACME". Product 2 has two purchase rows,
    # so the LEFT JOIN repeats its $50 of sales.
    return pd.DataFrame({
        "VendorNumber": [7, 7, 7, 7],
        "VendorName": ["ACME ", "ACME", "ACME", "ACME CO"],      # note the trailing space
        "Brand": [1, 2, 2, 4],
        "Description": ["Gin", "Rum", "Rum", "Vodka"],
        "TotalSalesDollars": [100.0, 50.0, 50.0, 30.0],
    })


@pytest.fixture
def monthly() -> pd.DataFrame:
    # Gin matches; Rum is $50 in sales (repeated in the yearly table); Malt sold but has no
    # yearly row; Vodka is sold under the other name.
    return pd.DataFrame({
        "VendorName": ["ACME", "ACME", "ACME", "ACME CO"],
        "Brand": [1, 2, 3, 4],
        "Description": ["Gin", "Rum", "Malt", "Vodka"],
        "MonthlyRevenue": [100.0, 50.0, 25.0, 30.0],
    })


def test_other_names_of_a_vendor_number_map_to_the_views_name(raw):
    assert checks.vendor_aliases(raw, known={"ACME"}) == {"ACME CO": "ACME"}


def test_every_dollar_of_the_gap_gets_a_reason(raw, monthly):
    rec = reconcile.compare(monthly, raw, {"ACME CO": "ACME"})
    reasons = dict(zip(rec["Description"], rec["Reason"]))
    assert reasons == {"Gin": "same in both", "Rum": "repeated in the yearly table",
                       "Malt": "sold, but not in the yearly table", "Vodka": "same in both"}
    split = reconcile.by_reason(rec)["Gap"]
    assert split.sum() == pytest.approx(rec["Monthly"].sum() - rec["Yearly"].sum())   # 205 - 230
    assert split["sold, but not in the yearly table"] == pytest.approx(25.0)
    assert split["repeated in the yearly table"] == pytest.approx(-50.0)


def test_standardising_names_removes_a_false_unknown_vendor(raw, monthly):
    data = {"vendor_sales_summary": raw, "monthly_demand": monthly,
            "vw_VendorRevenueSummary": pd.DataFrame({"VendorName": ["ACME"]})}
    out = checks.standardise_vendor_names(data)
    assert set(out["monthly_demand"]["VendorName"]) == {"ACME"}
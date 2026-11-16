

"""Step 2 tests. They use a tiny made-up dataset (2 vendors, 2 SKUs), not your real data:
first prove clean data passes, then break one thing at a time and prove the gate notices."""
import pandas as pd
import pytest

from monthly_pack import checks


@pytest.fixture
def data() -> dict[str, pd.DataFrame]:
    vendors = pd.DataFrame({"VendorName": ["ALPHA", "BETA"], "TotalRevenue": [600.0, 400.0]})
    leakage = vendors.assign(
        LossMakingLeakage=[30.0, 0.0], FreightLeakage=[10.0, 5.0], ControllableLeakage=[40.0, 5.0],
        ExciseLeakage=[20.0, 10.0], TotalLeakageAmount=[60.0, 15.0], ControllableLeakagePct=[6.67, 1.25],
    )
    skus = pd.DataFrame({"VendorNumber": [1, 2], "Brand": [10, 20], "TotalSalesDollars": [598.0, 400.0]})
    monthly = pd.DataFrame({
        "VendorName": ["ALPHA"] * 12 + ["BETA"] * 12,
        "Brand": [10] * 12 + [20] * 12,
        "Size": ["750mL"] * 24,
        "SalesYear": [2024] * 24,
        "SalesMonth": list(range(1, 13)) * 2,
        "MonthlyRevenue": [50.0] * 12 + [400.0 / 12] * 12,
    })
    return {
        "vw_ProfitLeakage": leakage,
        "vw_VendorRevenueSummary": vendors.copy(),
        "vw_VendorTiering": vendors.copy(),
        "vw_ParetoAnalysis": vendors.copy(),
        "vw_LogisticsCostSummary": vendors.copy(),
        "vw_PortfolioHealth": skus,
        "monthly_demand": monthly,
    }


def status_of(results, check_name):
    return next(r.status for r in results if r.name == check_name)


def test_clean_data_opens_the_gate(data):
    results = checks.run_checks(data)
    assert [r.status for r in results] == ["PASS"] * len(checks.ALL_CHECKS)
    assert checks.gate_passes(results)


def test_a_vendor_missing_from_one_view_closes_the_gate(data):
    data["vw_VendorTiering"] = data["vw_VendorTiering"].iloc[:1]
    results = checks.run_checks(data)
    assert status_of(results, "Vendor views list the same vendors") == "FAIL"
    assert not checks.gate_passes(results)


def test_revenue_that_differs_between_views_fails(data):
    data["vw_ParetoAnalysis"].loc[0, "TotalRevenue"] += 50
    assert status_of(checks.run_checks(data), "Vendor views agree on total revenue") == "FAIL"


def test_leakage_that_does_not_add_up_fails(data):
    data["vw_ProfitLeakage"].loc[0, "FreightLeakage"] = 99.0
    assert status_of(checks.run_checks(data), "Leakage parts add up to the total") == "FAIL"


def test_a_missing_month_fails(data):
    data["monthly_demand"] = data["monthly_demand"].query("SalesMonth != 7")
    assert status_of(checks.run_checks(data), "Monthly table covers 12 clean months") == "FAIL"


def test_small_monthly_gap_warns_and_large_gap_fails(data):
    data["monthly_demand"].loc[0, "MonthlyRevenue"] += 5      # 0.5% of 1,000
    assert status_of(checks.run_checks(data), "Monthly revenue matches yearly revenue") == "WARN"
    data["monthly_demand"].loc[0, "MonthlyRevenue"] += 50     # now 5.5%
    assert status_of(checks.run_checks(data), "Monthly revenue matches yearly revenue") == "FAIL"


def test_unknown_vendor_name_warns_when_small(data):
    extra = data["monthly_demand"].iloc[[0]].assign(VendorName="GAMMA", MonthlyRevenue=1.0)
    data["monthly_demand"] = pd.concat([data["monthly_demand"], extra], ignore_index=True)
    results = checks.run_checks(data)
    assert status_of(results, "Monthly vendor names are known to the views") == "WARN"
    assert checks.gate_passes(results)  # a warning does not close the gate


def test_a_check_that_crashes_counts_as_a_failure(data):
    data["vw_ProfitLeakage"] = data["vw_ProfitLeakage"].drop(columns=["ExciseLeakage"])
    results = checks.run_checks(data)
    assert not checks.gate_passes(results)
    assert any("could not run" in r.detail for r in results)
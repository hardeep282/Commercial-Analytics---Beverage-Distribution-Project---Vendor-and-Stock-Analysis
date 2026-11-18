


"""Step 6 tests, on made-up data. No database, no AI."""
import pandas as pd

from monthly_pack import build_pack, plays


def test_only_material_movers_are_kept():
    movers = pd.DataFrame({"VendorName": ["A", "B", "C", "D"],
                           "Change": [1_160_000.0, 9_999.0, -152.0, -58_920.0]})
    kept = build_pack.material_movers(movers)
    assert list(kept["VendorName"]) == ["A", "D"]       # B and C are under $10,000


def test_kpi_rows_are_one_number_per_row():
    k = {
        "monthly": {"month": 7, "revenue": 100.0, "change": 10.0, "change_pct": 11.1,
                    "ytd_revenue": 500.0, "rank_so_far": 1, "active_skus": 9, "active_vendors": 3},
        "yearly": {"revenue": 1000.0, "gross_margin_pct": 30.0, "net_margin_pct": 20.0,
                   "excise": 40.0, "loss_making_skus": 2},
        "concentration": {"top_10_share_pct": 65.0},
    }
    rows = build_pack.kpi_rows(k)
    assert list(rows.columns) == ["Month", "Section", "Metric", "Value", "Unit"]
    assert (rows["Month"] == "2024-07").all() and len(rows) == 13
    revenue = rows.query("Section == 'Monthly' and Metric == 'Revenue'")["Value"].item()
    assert revenue == 100.0


def test_plays_csv_carries_the_assumptions():
    play = plays.Play(kind=plays.CASH, name="Buying discipline", problem="", action="", owner="Buying",
                      kpi="", pool=10.0, scenarios={"cautious": 1.0, "base": 2.0, "stretch": 3.0},
                      assumptions=["Value = cash", "Shares are ours"])
    table = build_pack.plays_csv([play])
    assert table.loc[0, "Assumptions"] == "Value = cash | Shares are ours"
    assert table.loc[0, "Priority"] == "1"
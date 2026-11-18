

"""Step 6 piece 2 tests: the PDF is built from made-up data. No database, no AI."""
import pandas as pd

from monthly_pack import pdf, plays
from monthly_pack.checks import Check


def small_pack():
    k = {
        "monthly": {"revenue": 100.0, "change": None, "change_pct": None, "ytd_revenue": 100.0,
                    "rank_so_far": 1, "months_so_far": 1},
        "top_vendors": pd.DataFrame({"VendorName": ["ALPHA & SONS"], "Revenue": [60.0], "SharePct": [60.0]}),
        "yearly": {"revenue": 1000.0, "gross_margin_pct": 30.0, "net_margin_pct": 20.0, "excise": 40.0},
        "concentration": {"top_10_share_pct": 65.0},
        "sku_health": pd.DataFrame({"HealthStatus": ["Healthy"], "SKUs": [5], "SKUsPct": [100.0],
                                    "RevenuePct": [100.0]}),
    }
    play = plays.Play(kind=plays.CASH, name="Buying discipline", problem="Too much stock <here>",
                      action="Buy less", owner="Buying", kpi="", pool=10.0,
                      scenarios={"cautious": 1.0, "base": 2.0, "stretch": 3.0}, assumptions=["Ours"])
    return {"kpis": k, "results": [Check("Names", "WARN", "5 names & more")],
            "movers": pd.DataFrame(columns=["VendorName", "Change", "ChangePct"]),
            "trend": pd.Series([100.0], index=[1]), "plays": [play]}


def test_markdown_bold_becomes_pdf_bold_and_symbols_are_made_safe():
    assert pdf.markdown_line("**Summary:** A & B < C") == "<b>Summary:</b> A &amp; B &lt; C"


def test_the_pdf_is_written_with_and_without_a_memo(tmp_path):
    for memo_text in (None, "**Summary:** fine.\n# Heading is skipped"):
        path = pdf.write_pdf(small_pack(), 1, memo_text, tmp_path / "pack.pdf")
        data = path.read_bytes()
        assert data.startswith(b"%PDF") and len(data) > 2000
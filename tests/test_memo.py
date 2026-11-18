"""Step 5 tests. No AI is called in any test."""
import pandas as pd

from monthly_pack import memo, plays
from monthly_pack.checks import Check


def small_kpis():
    return {
        "monthly": {"month_name": "July", "revenue": 49_700_000.0, "change": 10_400_000.0,
                    "change_pct": 26.5, "ytd_revenue": 243_470_000.0, "rank_so_far": 1,
                    "months_so_far": 7},
        "top_vendors": pd.DataFrame({"VendorName": ["ALPHA"], "Revenue": [7_920_000.0],
                                     "SharePct": [15.9]}),
        "yearly": {"revenue": 451_620_000.0, "gross_margin_pct": 28.7, "net_margin_pct": 24.2,
                   "total_leakage": 24_960_000.0, "controllable_leakage": 5_990_000.0,
                   "excise": 18_970_000.0},
        "concentration": {"top_10_share_pct": 65.0, "top_vendor": "ALPHA",
                          "top_vendor_share_pct": 15.2},
    }


def small_plays():
    def card(kind, name, pool, base, owner, details=None):
        scen = {} if base is None else {"cautious": base / 2, "base": base, "stretch": base * 1.5}
        return plays.Play(kind=kind, name=name, problem="", action="", owner=owner, kpi="",
                          pool=pool, scenarios=scen, details=details or {})
    return [
        card(plays.CASH, "Buying discipline", 9_360_000.0, 4_680_000.0, "Buying", {"focus_skus": 620}),
        card(plays.RISK, "Vendor concentration", 0.0, None, "Commercial director"),
        card(plays.FIXED, "Excise tax", 18_970_000.0, None, "-"),
    ]


SMALL_DIAGNOSIS = {"skus": 2127, "loss": 4_350_000.0, "loss_from_overbuying": 4_100_000.0,
                   "loss_from_selling_below_cost": 250_000.0}


def test_fact_sheet_holds_the_numbers_python_worked_out():
    facts = memo.fact_sheet(small_kpis(), small_plays(), SMALL_DIAGNOSIS,
                            [Check("Names known", "WARN", "5 names not in the views")])
    assert "Revenue in July: $49.70M" in facts
    assert "Change vs previous month: +26.5% ($10.40M)" in facts
    assert "came from buying more than was sold and $250,000 from selling below cost" in facts
    assert "620 SKUs hold $9.36M of unsold stock" in facts
    assert "Priority 1: Buying discipline. Cash freed (one-off). $2.34M / $4.68M / $7.02M" in facts
    assert "Priority watch: Vendor concentration. Risk to manage (no dollar value). no dollar value" in facts
    assert "Priority -" not in facts                      # excise is listed once, above
    assert "- Names known: 5 names not in the views" in facts


def test_fact_sheet_says_none_when_there_are_no_warnings():
    facts = memo.fact_sheet(small_kpis(), small_plays(), SMALL_DIAGNOSIS, [Check("All good", "PASS", "")])
    assert "DATA-QUALITY WARNINGS (must be mentioned)\n- none" in facts


def test_prompt_puts_the_rules_in_the_system_prompt_and_the_facts_in_the_message():
    system, user = memo.build_prompt("FACT LINE")
    assert "Copy every number exactly" in system and "FACT LINE" not in system
    assert "<fact_sheet>\nFACT LINE\n</fact_sheet>" in user


# --- piece 2 -------------------------------------------------------------------------------
from types import SimpleNamespace  # noqa: E402

FACTS = ("- Revenue in July: $49.70M\n- Change vs previous month: +26.5% ($10.41M)\n"
         "- 2,127 loss-making SKUs lost $4.35M; largest: EDRINGTON ($+108,246)")


class FakeClaude:
    """Stands in for the real Anthropic client: returns a fixed memo, never calls the API."""

    def __init__(self, reply: str):
        self.reply = reply
        self.messages = self
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)],
                               usage=SimpleNamespace(input_tokens=700, output_tokens=400))


def test_numbers_copied_from_the_fact_sheet_pass():
    memo_text = "July revenue was $49.70M, up +26.5%. 2,127 SKUs lost $4.35M. Edrington $108,246."
    assert memo.check_numbers(memo_text, FACTS) == []


def test_an_invented_or_rounded_number_is_caught():
    memo_text = "Revenue was $49.70M, about $50M, and losses were $4.4M."
    assert memo.check_numbers(memo_text, FACTS) == ["$50M", "$4.4M"]


def test_list_numbers_top_10_and_the_year_are_allowed():
    assert memo.check_numbers("In 2024, priority 1 of 3; the top 10 vendors.", FACTS) == []


def test_a_clean_memo_is_saved(tmp_path):
    fake = FakeClaude("July revenue was $49.70M.")
    result = memo.produce_memo(FACTS, "July", client=fake, out_dir=tmp_path)
    assert fake.calls == 1 and result["unknown"] == []
    assert result["path"].name == "memo_2024_july.md"
    assert "Number check: passed" in result["path"].read_text(encoding="utf-8")


def test_a_memo_with_an_invented_number_is_rejected(tmp_path):
    result = memo.produce_memo(FACTS, "July", client=FakeClaude("Revenue hit $51M."), out_dir=tmp_path)
    assert result["unknown"] == ["$51M"]
    assert result["path"].name == "memo_2024_july_REJECTED.md"
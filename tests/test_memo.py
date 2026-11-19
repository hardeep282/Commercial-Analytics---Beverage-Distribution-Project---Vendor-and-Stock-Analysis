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
    """Stands in for the real Anthropic client: returns fixed memos, never calls the API.

    Give it one reply to get the same memo every time, or several to get them in turn.
    """

    def __init__(self, *replies: str, stop_reason: str = "end_turn"):
        self.replies = list(replies)
        self.stop_reason = stop_reason
        self.messages = self
        self.calls = 0
        self.last_user_message = ""

    def create(self, **kwargs):
        self.last_user_message = kwargs["messages"][0]["content"]
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)],
                               usage=SimpleNamespace(input_tokens=700, output_tokens=400),
                               stop_reason=self.stop_reason)


# A complete memo has all four section headings; the tests below build on it.
SECTIONS = "This month. Full year. Recommended actions. Data notes. "


def test_numbers_copied_from_the_fact_sheet_pass():
    memo_text = "July revenue was $49.70M, up +26.5%. 2,127 SKUs lost $4.35M. Edrington $108,246."
    assert memo.check_numbers(memo_text, FACTS) == []


def test_an_invented_or_rounded_number_is_caught():
    memo_text = "Revenue was $49.70M, about $50M, and losses were $4.4M."
    assert memo.check_numbers(memo_text, FACTS) == ["$50M", "$4.4M"]


def test_list_numbers_top_10_and_the_year_are_allowed():
    assert memo.check_numbers("In 2024, priority 1 of 3; the top 10 vendors.", FACTS) == []


def test_a_clean_memo_is_saved(tmp_path):
    fake = FakeClaude(SECTIONS + "July revenue was $49.70M.")
    result = memo.produce_memo(FACTS, "July", client=fake, out_dir=tmp_path)
    assert fake.calls == 1 and result["unknown"] == [] and result["passed"]
    assert result["path"].name == "memo_2024_july.md"
    assert "Number check: passed" in result["path"].read_text(encoding="utf-8")


def test_a_memo_with_an_invented_number_is_rejected(tmp_path):
    fake = FakeClaude(SECTIONS + "Revenue hit $51M.")
    result = memo.produce_memo(FACTS, "July", client=fake, out_dir=tmp_path)
    assert fake.calls == 2                                  # one rewrite was asked for
    assert result["unknown"] == ["$51M"] and not result["passed"]
    assert result["path"].name == "memo_2024_july_REJECTED.md"


# --- R7: wording checks -------------------------------------------------------------------

def test_target_talk_is_caught():
    problems = memo.check_wording(SECTIONS + "July sales are running well ahead of pace and beat the budget.")
    assert problems == ["compares with a target the data doesn't have: budget, pace"]


def test_a_numbered_watch_item_is_caught_and_an_unnumbered_one_passes():
    numbered = "1. Buying discipline\n2. Freight terms\n3. Discount review\n4. Watch vendor concentration"
    assert memo.check_wording(SECTIONS + numbered) == ["the watch item is numbered like an action"]
    assert memo.check_wording(SECTIONS + "3. Discount review\nWatch: vendor concentration") == []


def test_word_limit():
    assert memo.word_count("July revenue was $49.70M, up +26.5%.") == 6
    assert memo.check_wording(SECTIONS + "word " * 343) == ["351 words, over the 350-word limit"]
    assert memo.check_wording(SECTIONS + "word " * 342) == []          # 8 heading words + 342 = 350


def test_a_bad_first_draft_is_rewritten_once_and_then_saved(tmp_path):
    fake = FakeClaude(SECTIONS + "July revenue of $49.70M is well ahead of pace.",
                      SECTIONS + "July revenue was $49.70M.")
    result = memo.produce_memo(FACTS, "July", client=fake, out_dir=tmp_path)
    assert fake.calls == 2 and result["passed"] and result["attempts"] == 2
    assert "compares with a target the data doesn't have: pace" in fake.last_user_message
    assert result["tokens_in"] == 1400                      # both calls are counted in the cost
    assert result["path"].name == "memo_2024_july.md"


def test_a_memo_cut_off_at_the_token_limit_fails_even_if_short():
    # What really happened on 20 Nov: thinking used the token budget and the memo stopped mid-sentence.
    cut = "July revenue was $49.70M. **Full year** The top"
    problems = memo.check_wording(cut, stop_reason="max_tokens")
    assert problems[0] == "cut off at the token limit before the end"
    assert problems[1] == "missing sections: This month, Recommended actions, Data notes"


def test_a_cut_off_memo_is_rewritten_and_the_history_records_both_attempts(tmp_path):
    fake = FakeClaude(SECTIONS + "July revenue was $49.70M.", stop_reason="max_tokens")
    result = memo.produce_memo(FACTS, "July", client=fake, out_dir=tmp_path)
    assert fake.calls == 2 and not result["passed"]
    assert len(result["history"]) == 2 and "stopped: max_tokens" in result["history"][0]
    assert "cut off at the token limit" in fake.last_user_message
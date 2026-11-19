"""Step 5 - the board memo. The only step that uses AI.

    Python works out every number -> Claude only writes the words -> Python checks the words

Piece 1: the fact sheet (every number the memo may use) and the instructions for Claude.
         No AI call yet: run with --dry-run to see exactly what Claude would be given.
Piece 2: the AI call, the number check, and saving the memo (or rejecting it).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pandas as pd

from monthly_pack import checks, kpis, plays
from monthly_pack.kpis import money


def fact_sheet(k: dict, play_list: list, diagnosis: dict, gate_results: list) -> str:
    """Every number the memo is allowed to use, already worked out and formatted by Python.

    k          the KPIs from step 3 (kpis.build_kpis)
    play_list  the play cards from step 4 (plays.all_plays)
    diagnosis  why the loss-making SKUs lose money (plays.diagnose_loss_makers)
    """
    m, y, c = k["monthly"], k["yearly"], k["concentration"]
    top = k["top_vendors"].iloc[0]
    buying = next(p for p in play_list if p.name == "Buying discipline")
    lines = [
        f"REPORTING MONTH: {m['month_name']} 2024. Monthly figures use January to "
        f"{m['month_name']} only. Full-year figures are 2024 totals.",
        "",
        "MONTHLY TREND",
        f"- Revenue in {m['month_name']}: {money(m['revenue'])}",
    ]
    if m["change"] is not None:
        lines.append(f"- Change vs previous month: {m['change_pct']:+.1f}% ({money(m['change'])})")
    lines += [
        f"- Year to date: {money(m['ytd_revenue'])}",
        f"- Rank so far: {m['rank_so_far']} of {m['months_so_far']} months",
        f"- Top vendor this month: {top['VendorName']}, {money(top['Revenue'])} "
        f"({top['SharePct']:.1f}% of the month)",
        "",
        "FULL-YEAR 2024 PROFITABILITY",
        f"- Revenue: {money(y['revenue'])}; gross margin {y['gross_margin_pct']:.1f}%; "
        f"net margin {y['net_margin_pct']:.1f}%",
        f"- Excise tax: {money(y['excise'])}, the largest cost after the stock itself; not controllable",
        f"- Top 10 vendors: {c['top_10_share_pct']:.1f}% of revenue; largest is "
        f"{c['top_vendor']} at {c['top_vendor_share_pct']:.1f}%",
        "",
        "KEY FINDING: THE LOSSES ARE MOSTLY OVERBUYING, NOT PRICING",
        f"- {diagnosis['skus']:,} loss-making SKUs lost {money(diagnosis['loss'])} in 2024",
        f"- Of that, {money(diagnosis['loss_from_overbuying'])} came from buying more than was sold "
        f"and {money(diagnosis['loss_from_selling_below_cost'])} from selling below cost",
        f"- {buying.details['focus_skus']:,} SKUs hold {money(buying.pool)} of unsold stock "
        f"(60% of all unsold stock)",
        "",
        "STRATEGY PLAYS, RANKED (cautious / base / stretch; the shares behind them are assumptions)",
    ]
    for row in plays.rank_plays(play_list).itertuples():
        if row.Priority == "-":
            continue  # excise is already listed above as not controllable
        if pd.isna(row.Base):
            values = "no dollar value"
        else:
            values = f"{money(row.Cautious)} / {money(row.Base)} / {money(row.Stretch)}"
        lines.append(f"- Priority {row.Priority}: {row.Play}. {row.Kind}. {values}. Owner: {row.Owner}")
    warnings = [r for r in gate_results if r.status == "WARN"]
    lines += ["", "DATA-QUALITY WARNINGS (must be mentioned)"]
    lines += [f"- {r.name}: {r.detail}" for r in warnings] or ["- none"]
    return "\n".join(lines)


SYSTEM_PROMPT = """You write a one-page monthly memo for the board of a beverage distributor.

Rules, all of them strict:
1. Use ONLY the facts in the fact sheet. Never use outside knowledge about these vendors.
2. Copy every number exactly as written in the fact sheet. Do not round, convert, add,
   subtract or calculate anything. If a number isn't in the fact sheet, don't write it.
3. Cash freed (one-off) and profit (every year) are different kinds of value. Never add
   them together or describe a "total opportunity".
4. Say that the cautious / base / stretch values rest on assumptions.
5. Mention every data-quality warning in one plain sentence each.
6. Plain English for a busy reader: a 2-sentence summary, then short sections for
   This month, Full year, Recommended actions (in priority order), Data notes.
   Under 350 words. No tables.
7. There are no targets, budgets, forecasts or plans in the data. Never say a figure is
   ahead of, behind, on track, on pace, above or below plan or expectations. Compare only
   with the previous month and with the months so far, as the fact sheet does.
8. Number only the priority 1, 2, 3 actions. Put the "watch" item after them on its own
   line starting "Watch:", without a number."""

# --- R7: checks on the wording, done by code after the AI writes --------------------------

MAX_WORDS = 350

# Words that compare against a target, which the data doesn't have.
TARGET_TALK = re.compile(
    r"\b(pace|on track|off track|target\w*|budget\w*|"
    r"forecast\w*|expectations?|expected|outperform\w*|underperform\w*)\b",
    re.IGNORECASE)

# A numbered line ("4. ..." or "4) ...") that is about the watch item.
NUMBERED_WATCH = re.compile(r"^\s*\d+[.)]\s.*\b(watch|concentration)\b",
                            re.IGNORECASE | re.MULTILINE)

# The four sections rule 6 asks for. A memo missing one is incomplete (or was cut off).
REQUIRED_SECTIONS = ("This month", "Full year", "Recommended actions", "Data notes")

# One word: letters/digits with $ or %, joined by . , ' or - inside (so $49.70M is one word).
WORD = re.compile(r"[\w$%]+(?:[.,'’-][\w%]+)*")


def word_count(text: str) -> int:
    return len(WORD.findall(text))


def check_wording(memo_text: str, stop_reason: str | None = "end_turn") -> list[str]:
    """Rule breaks that a number check can't see. An empty list means it passed.

    stop_reason comes from the API: "max_tokens" means the memo was cut off before the end.
    """
    problems = []
    if stop_reason == "max_tokens":
        problems.append("cut off at the token limit before the end")
    missing = [s for s in REQUIRED_SECTIONS if s.lower() not in memo_text.lower()]
    if missing:
        problems.append("missing sections: " + ", ".join(missing))
    words = word_count(memo_text)
    if words > MAX_WORDS:
        problems.append(f"{words} words, over the {MAX_WORDS}-word limit")
    talk = sorted({m.group(0).lower() for m in TARGET_TALK.finditer(memo_text)})
    if talk:
        problems.append("compares with a target the data doesn't have: " + ", ".join(talk))
    if NUMBERED_WATCH.search(memo_text):
        problems.append("the watch item is numbered like an action")
    return problems


def build_prompt(facts: str) -> tuple[str, str]:
    """The system prompt (the rules) and the user message (the facts)."""
    return SYSTEM_PROMPT, f"Write the memo from this fact sheet.\n\n<fact_sheet>\n{facts}\n</fact_sheet>"


def gather(month: int) -> tuple[str, list]:
    """Load, check, compute, size: steps 1 to 4 in one call. Stops if the gate is closed."""
    data = checks.load_sources()
    results = checks.run_checks(data)
    if not checks.gate_passes(results):
        print("GATE CLOSED: no memo. Run  python -m monthly_pack.checks  to see why.")
        sys.exit(1)
    k = kpis.build_kpis(data, month)
    play_list = plays.all_plays(data)
    diagnosis = plays.diagnose_loss_makers(data["vw_PortfolioHealth"])
    return fact_sheet(k, play_list, diagnosis, results), results


# --- piece 2: the AI call and the number check ---------------------------------------------

MODEL = os.environ.get("MEMO_MODEL", "claude-sonnet-5")
# Room for Claude's thinking AND the memo. Sonnet 5 thinks by default, and thinking counts
# toward this limit (Anthropic docs, "Adaptive thinking"). 1,200 was too small: the memo was
# cut off mid-sentence. 8,000 caps the worst case at about 8 cents per call.
MAX_TOKENS = 8000
# USD per million tokens, from Anthropic's pricing page. Used only to print the cost.
PRICE_PER_MILLION = {"claude-sonnet-5": (2.0, 10.0)}
OUT_DIR = Path("pack_output")

# A number as written in text: optional sign and $, digits with commas, optional decimals,
# optional M or %. For example $4.68M, +26.5%, 2,127, $250,792, 0.01%.
NUMBER = re.compile(r"[-+]?\$?\d[\d,]*(?:\.\d+)?[M%]?")


def canonical(token: str) -> str:
    """The same number written the same way: no sign, no $, no commas. '$+108,246' -> '108246'."""
    return token.lstrip("+-").replace("$", "").replace(",", "").lstrip("+-")


def check_numbers(memo_text: str, facts: str) -> list[str]:
    """Every number in the memo that is NOT in the fact sheet. An empty list means it passed.

    Allowed without being in the fact sheet: whole numbers up to 12 (list numbering,
    "top 10", months) and the year 2024.
    """
    allowed = {canonical(t) for t in NUMBER.findall(facts)}
    unknown = []
    for token in NUMBER.findall(memo_text):
        c = canonical(token)
        if c in allowed or c == "2024" or (c.isdigit() and int(c) <= 12):
            continue
        unknown.append(token)
    return unknown


def ask_claude(system: str, user: str, client=None) -> dict:
    """One call to Claude. Returns the memo text, token counts, and why Claude stopped.

    The real client reads ANTHROPIC_API_KEY from your .env. Tests pass a fake client,
    so running the tests never calls the API and never costs anything.
    """
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # Thinking comes back in separate blocks; the memo is only the "text" blocks.
    text = "".join(block.text for block in response.content if block.type == "text")
    details = getattr(response.usage, "output_tokens_details", None)
    return {"text": text,
            "tokens_in": response.usage.input_tokens,
            "tokens_out": response.usage.output_tokens,           # thinking + memo, as billed
            "thinking": getattr(details, "thinking_tokens", None),  # the thinking part, if reported
            "stop_reason": getattr(response, "stop_reason", None)}


def cost_usd(input_tokens: int, output_tokens: int) -> float | None:
    if MODEL not in PRICE_PER_MILLION:
        return None
    price_in, price_out = PRICE_PER_MILLION[MODEL]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


MAX_ATTEMPTS = 2  # the first draft, plus one rewrite if a check fails


def review(text: str, facts: str, stop_reason: str | None = "end_turn") -> tuple[list[str], list[str]]:
    """Both checks: numbers not in the fact sheet, and everything else (cut off, missing
    sections, word limit, target talk, numbered watch)."""
    return check_numbers(text, facts), check_wording(text, stop_reason)


def produce_memo(facts: str, month_name: str, client=None, out_dir: Path = OUT_DIR) -> dict:
    """Ask Claude for the memo, check it, ask for one rewrite if needed, then save it
    (or save it as REJECTED)."""
    system, user = build_prompt(facts)
    tokens_in = tokens_out = 0
    history = []  # one line per attempt, so a rewrite is never hidden
    for attempt in range(1, MAX_ATTEMPTS + 1):
        reply = ask_claude(system, user, client)
        text = reply["text"]
        tokens_in, tokens_out = tokens_in + reply["tokens_in"], tokens_out + reply["tokens_out"]
        unknown, wording = review(text, facts, reply["stop_reason"])
        problems = [f"number not in the fact sheet: {n}" for n in unknown] + wording
        history.append(f"attempt {attempt}: {reply['tokens_out']:,} tokens out"
                       + (f" ({reply['thinking']:,} thinking)" if reply["thinking"] else "")
                       + f", stopped: {reply['stop_reason']}, {word_count(text)} words, "
                       + ("passed" if not problems else "failed: " + "; ".join(problems)))
        if not problems:
            break
        # Same rules and facts, plus the list of what went wrong last time.
        user = (build_prompt(facts)[1] + "\n\nYour previous draft broke these rules. "
                "Write it again and fix them:\n" + "\n".join(f"- {p}" for p in problems))
    passed = not unknown and not wording
    out_dir.mkdir(exist_ok=True)
    name = f"memo_2024_{month_name.lower()}"
    path = out_dir / (f"{name}.md" if passed else f"{name}_REJECTED.md")
    header = (f"<!-- Written by {MODEL} from a fact sheet built by Python. "
              f"Number check: {'FAILED ' + ', '.join(unknown) if unknown else 'passed'}. "
              f"Wording check: {'FAILED ' + '; '.join(wording) if wording else 'passed'}. "
              f"Attempts: {attempt}. Words: {word_count(text)}.\n"
              + "\n".join(history) + " -->\n\n")
    path.write_text(header + text, encoding="utf-8")
    return {"text": text, "unknown": unknown, "wording": wording, "passed": passed,
            "attempts": attempt, "history": history, "path": path,
            "tokens_in": tokens_in, "tokens_out": tokens_out}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    month = int(args[0]) if args else 12
    facts, _ = gather(month)
    system, user = build_prompt(facts)
    if "--dry-run" in sys.argv:
        print("=== SYSTEM PROMPT (the rules) ===\n" + system)
        print("\n=== USER MESSAGE (the facts) ===\n" + user)
        print(f"\nDry run: nothing sent to Claude. About {len(system + user) // 4:,} tokens would be sent.")
        sys.exit(0)

    month_name = facts.split("REPORTING MONTH: ")[1].split(" ")[0]
    print(f"Asking {MODEL} for the {month_name} memo...")
    result = produce_memo(facts, month_name)
    cost = cost_usd(result["tokens_in"], result["tokens_out"])
    print(f"Tokens: {result['tokens_in']:,} in, {result['tokens_out']:,} out"
          + (f"   cost about ${cost:.4f}" if cost is not None else ""))
    for line in result["history"]:
        print("  " + line)
    if not result["passed"]:
        print(f"REJECTED after {result['attempts']} attempts.")
        if result["unknown"]:
            print(f"  numbers not in the fact sheet: {result['unknown']}")
        for problem in result["wording"]:
            print(f"  {problem}")
        print(f"Saved for inspection only: {result['path']}")
        sys.exit(1)
    print(f"Checks passed on attempt {result['attempts']}: every number is in the fact sheet, "
          f"complete with all four sections, no target talk, watch item unnumbered, "
          f"{word_count(result['text'])} words.")
    print(f"Saved: {result['path']}\n")
    print(result["text"])
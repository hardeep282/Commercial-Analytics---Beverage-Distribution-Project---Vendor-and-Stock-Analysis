"""Step 6 - build the pack. The one command that runs everything.

    python -m monthly_pack.build_pack 7            -> July's pack, with the AI memo
    python -m monthly_pack.build_pack 7 --no-ai    -> July's pack, no AI call, no cost

Piece 1: run steps 1-5 in order and write the CSV files Power BI will read.
Piece 2: also write the PDF pack for management (monthly_pack/pdf.py).
"""
from __future__ import annotations

import calendar
import sys
from pathlib import Path

import pandas as pd

from monthly_pack import checks, kpis, memo, plays
from monthly_pack.pdf import write_pdf

OUT_DIR = Path("pack_output")
MATERIAL_CHANGE = 10_000  # a vendor's month-on-month change must be at least this to be listed


def material_movers(movers: pd.DataFrame, threshold: float = MATERIAL_CHANGE) -> pd.DataFrame:
    """Keep only rises and falls of at least `threshold` dollars (resume point R1).

    In a strong month almost every vendor rises, so the 'biggest falls' are tiny
    (-$152, -$279 in December). They are noise, not news.
    """
    return movers[movers["Change"].abs() >= threshold].reset_index(drop=True)


def kpi_rows(k: dict) -> pd.DataFrame:
    """The KPIs as one long table (one row per number): the shape Power BI likes best."""
    m, y, c = k["monthly"], k["yearly"], k["concentration"]
    month = f"2024-{m['month']:02d}"
    rows = [
        ("Monthly", "Revenue", m["revenue"], "$"),
        ("Monthly", "Change vs previous month", m["change"], "$"),
        ("Monthly", "Change vs previous month %", m["change_pct"], "%"),
        ("Monthly", "Year to date revenue", m["ytd_revenue"], "$"),
        ("Monthly", "Rank so far", m["rank_so_far"], "rank"),
        ("Monthly", "Active SKUs", m["active_skus"], "count"),
        ("Monthly", "Active vendors", m["active_vendors"], "count"),
        ("Full year", "Revenue", y["revenue"], "$"),
        ("Full year", "Gross margin %", y["gross_margin_pct"], "%"),
        ("Full year", "Net margin %", y["net_margin_pct"], "%"),
        ("Full year", "Excise tax", y["excise"], "$"),
        ("Full year", "Loss-making SKUs", y["loss_making_skus"], "count"),
        ("Full year", "Top 10 vendors share %", c["top_10_share_pct"], "%"),
    ]
    table = pd.DataFrame(rows, columns=["Section", "Metric", "Value", "Unit"])
    table.insert(0, "Month", month)
    return table


def plays_csv(play_list: list) -> pd.DataFrame:
    """The ranked plays with their assumptions, one row per play."""
    table = plays.rank_plays(play_list)
    notes = {p.name: " | ".join(p.assumptions) for p in play_list}
    table["Assumptions"] = table["Play"].map(notes)
    return table


def collect(month: int) -> dict:
    """Steps 1-4: load, check (stop if the gate is closed), compute, size."""
    data = checks.load_sources()
    results = checks.run_checks(data)
    if not checks.gate_passes(results):
        print("GATE CLOSED: no pack built. Run  python -m monthly_pack.checks  to see why.")
        sys.exit(1)
    k = kpis.build_kpis(data, month)
    play_list = plays.all_plays(data)
    diagnosis = plays.diagnose_loss_makers(data["vw_PortfolioHealth"])
    trend = data["monthly_demand"].groupby("SalesMonth")["MonthlyRevenue"].sum().loc[:month]
    return {
        "results": results,
        "kpis": k,
        "trend": trend,
        "movers": material_movers(k["movers"]),
        "plays": play_list,
        "diagnosis": diagnosis,
        "facts": memo.fact_sheet(k, play_list, diagnosis, results),
    }


def write_csvs(pack: dict, month: int, out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(exist_ok=True)
    stem = f"2024-{month:02d}"
    files = {
        out_dir / f"{stem}_kpis.csv": kpi_rows(pack["kpis"]),
        out_dir / f"{stem}_plays.csv": plays_csv(pack["plays"]),
        out_dir / f"{stem}_movers.csv": pack["movers"],
    }
    for path, table in files.items():
        table.round(2).to_csv(path, index=False)  # cents are enough; no 9999551.160000004
    return list(files)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    month = int(args[0]) if args else 12
    use_ai = "--no-ai" not in sys.argv
    print(f"Building the {calendar.month_name[month]} 2024 pack...")

    pack = collect(month)
    warnings = sum(r.status == "WARN" for r in pack["results"])
    print(f"  1-2  data loaded and checked: gate open ({warnings} warnings)")
    print(f"  3    KPIs computed: revenue {kpis.money(pack['kpis']['monthly']['revenue'])}")
    print(f"  4    {len(pack['plays'])} plays sized and ranked")
    print(f"       {len(pack['movers'])} material movers (at least ${MATERIAL_CHANGE:,} change)")

    memo_text = None
    if use_ai:
        result = memo.produce_memo(pack["facts"], calendar.month_name[month])
        if result["unknown"]:
            print(f"  5    memo REJECTED: numbers not in the fact sheet: {result['unknown']}")
            sys.exit(1)
        memo_text = result["text"]
        print(f"  5    memo written and checked: {result['path']}")
    else:
        print("  5    memo skipped (--no-ai)")

    for path in write_csvs(pack, month):
        print(f"  6    wrote {path}")
    pdf_path = write_pdf(pack, month, memo_text, OUT_DIR / f"2024-{month:02d}_pack.pdf")
    print(f"  6    wrote {pdf_path}")
    print("Done.")
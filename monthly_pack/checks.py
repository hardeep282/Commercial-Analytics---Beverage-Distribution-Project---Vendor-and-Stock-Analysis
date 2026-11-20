"""Step 2 - the data-quality gate.

Every check looks at the data and returns PASS, WARN or FAIL with a one-line reason.
    PASS  the rule holds
    WARN  something a reader should know about, but the numbers are still usable
    FAIL  the numbers can't be trusted: the pack must not be built

Usage:  python -m monthly_pack.checks        (exit code 1 if anything FAILs)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import pandas as pd

from monthly_pack import db

# The five views that have one row per vendor. They must all describe the same vendors.
VENDOR_VIEWS = (
    "vw_ProfitLeakage",
    "vw_VendorRevenueSummary",
    "vw_VendorTiering",
    "vw_ParetoAnalysis",
    "vw_LogisticsCostSummary",
)

# Tolerances, in one place so they are easy to find and defend.
DOLLAR_TOLERANCE = 1.0          # totals that should be identical may differ by rounding only
MONTHLY_GAP_WARN_PCT = 0.25     # monthly vs yearly revenue: above this, warn
MONTHLY_GAP_FAIL_PCT = 1.0      # ...above this, fail
UNMATCHED_NAMES_FAIL_PCT = 0.5  # revenue under vendor names the views don't know: fail above this
VENDOR_DRIFT_PCT = 1.0          # a vendor whose monthly and yearly revenue differ by more than this


@dataclass
class Check:
    name: str
    status: str  # PASS, WARN or FAIL
    detail: str


def load_sources() -> dict[str, pd.DataFrame]:
    """Read every source the pack uses, once, and give the monthly table the views' vendor names."""
    engine = db.get_engine()
    return standardise_vendor_names({name: db.read_view(name, engine) for name in db.PACK_VIEWS})


def vendor_aliases(raw: pd.DataFrame, known: set[str]) -> dict[str, str]:
    """Other names of the same vendor number -> the one name the yearly views use.

    The SQL (vw_VendorSalesBase) gives each vendor number one name. The monthly table has no
    vendor number, so without this map a renamed vendor looks like an unknown one (R3).
    """
    aliases = {}
    names = raw.assign(VendorName=raw["VendorName"].str.strip())[["VendorNumber", "VendorName"]]
    for _, group in names.drop_duplicates().groupby("VendorNumber"):
        in_views = [n for n in group["VendorName"] if n in known]
        if len(in_views) == 1:
            aliases.update({n: in_views[0] for n in group["VendorName"] if n != in_views[0]})
    return aliases


def standardise_vendor_names(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Rename monthly vendors to the names the yearly views use (no-op without the raw table)."""
    if "vendor_sales_summary" not in data:
        return data
    known = set(data["vw_VendorRevenueSummary"]["VendorName"])
    aliases = vendor_aliases(data["vendor_sales_summary"], known)
    monthly = data["monthly_demand"]
    data["monthly_demand"] = monthly.assign(VendorName=monthly["VendorName"].str.strip().replace(aliases))
    return data


# --- checks on the yearly views ----------------------------------------------------------


def check_not_empty(data: dict[str, pd.DataFrame]) -> Check:
    empty = [name for name, df in data.items() if df.empty]
    if empty:
        return Check("Sources have rows", "FAIL", "empty: " + ", ".join(empty))
    return Check("Sources have rows", "PASS", f"all {len(data)} sources have rows")


def check_vendor_views_agree(data: dict[str, pd.DataFrame]) -> Check:
    name = "Vendor views list the same vendors"
    first = set(data[VENDOR_VIEWS[0]]["VendorName"])
    for view in VENDOR_VIEWS:
        vendors = data[view]["VendorName"]
        if vendors.duplicated().any():
            return Check(name, "FAIL", f"{view} lists a vendor twice")
        if set(vendors) != first:
            return Check(name, "FAIL", f"{view} has different vendors from {VENDOR_VIEWS[0]}")
    return Check(name, "PASS", f"{len(first)} vendors in all {len(VENDOR_VIEWS)} views")


def check_revenue_agrees(data: dict[str, pd.DataFrame]) -> Check:
    name = "Vendor views agree on total revenue"
    totals = {view: data[view]["TotalRevenue"].sum() for view in VENDOR_VIEWS}
    spread = max(totals.values()) - min(totals.values())
    if spread > DOLLAR_TOLERANCE:
        return Check(name, "FAIL", f"totals differ by ${spread:,.0f}")
    return Check(name, "PASS", f"${min(totals.values()):,.0f} in every view")


def check_leakage_adds_up(data: dict[str, pd.DataFrame]) -> Check:
    name = "Leakage parts add up to the total"
    df = data["vw_ProfitLeakage"]
    controllable_gap = (df["ControllableLeakage"] - df["LossMakingLeakage"] - df["FreightLeakage"]).abs().max()
    total_gap = (df["TotalLeakageAmount"] - df["ControllableLeakage"] - df["ExciseLeakage"]).abs().max()
    if max(controllable_gap, total_gap) > DOLLAR_TOLERANCE:
        return Check(name, "FAIL", f"a vendor is out by ${max(controllable_gap, total_gap):,.2f}")
    return Check(
        name, "PASS",
        f"controllable ${df['ControllableLeakage'].sum():,.0f} + excise ${df['ExciseLeakage'].sum():,.0f}"
        f" = ${df['TotalLeakageAmount'].sum():,.0f}",
    )


def check_blanks_are_explained(data: dict[str, pd.DataFrame]) -> Check:
    """A percentage can only be blank when revenue is zero (nothing to divide by)."""
    name = "Blank percentages only where revenue is zero"
    df = data["vw_ProfitLeakage"]
    blank = df["ControllableLeakagePct"].isna()
    unexplained = int((blank & (df["TotalRevenue"] != 0)).sum())
    if unexplained:
        return Check(name, "FAIL", f"{unexplained} vendors with revenue have a blank percentage")
    return Check(name, "PASS", f"{int(blank.sum())} blank, all on zero-revenue vendors")


def check_cleaned_base(data: dict[str, pd.DataFrame]) -> Check:
    name = "Cleaned SKU base is sound"
    skus = data["vw_PortfolioHealth"]
    all_rows_revenue = data["vw_VendorRevenueSummary"]["TotalRevenue"].sum()
    cleaned_revenue = skus["TotalSalesDollars"].sum()
    if skus.duplicated(["VendorNumber", "Brand"]).any():
        return Check(name, "FAIL", "the same vendor and brand appears twice")
    if (skus["TotalSalesDollars"] < 0).any():
        return Check(name, "FAIL", "negative sales on a SKU")
    if not 0.99 * all_rows_revenue <= cleaned_revenue <= all_rows_revenue + DOLLAR_TOLERANCE:
        return Check(name, "FAIL", f"cleaned ${cleaned_revenue:,.0f} vs all rows ${all_rows_revenue:,.0f}")
    return Check(
        name, "PASS",
        f"{len(skus):,} SKUs, ${cleaned_revenue:,.0f} "
        f"({cleaned_revenue / all_rows_revenue:.2%} of all-rows revenue)",
    )


# --- checks on the monthly table ---------------------------------------------------------


def check_monthly_complete(data: dict[str, pd.DataFrame]) -> Check:
    name = "Monthly table covers 12 clean months"
    monthly = data["monthly_demand"]
    months = sorted(monthly["SalesMonth"].unique())
    if months != list(range(1, 13)) or monthly["SalesYear"].nunique() != 1:
        return Check(name, "FAIL", f"months found: {months}, years: {sorted(monthly['SalesYear'].unique())}")
    if (monthly["MonthlyRevenue"] < 0).any():
        return Check(name, "FAIL", "negative monthly revenue")
    if monthly.duplicated(["VendorName", "Brand", "Size", "SalesMonth"]).any():
        return Check(name, "FAIL", "the same vendor, brand, size and month appears twice")
    return Check(name, "PASS", f"{len(monthly):,} rows, 12 months of {monthly['SalesYear'].iloc[0]}")


def check_monthly_matches_yearly(data: dict[str, pd.DataFrame]) -> Check:
    name = "Monthly revenue matches yearly revenue"
    monthly_total = data["monthly_demand"]["MonthlyRevenue"].sum()
    yearly_total = data["vw_VendorRevenueSummary"]["TotalRevenue"].sum()
    gap = monthly_total - yearly_total
    gap_pct = abs(gap) / yearly_total * 100
    detail = f"monthly ${monthly_total:,.0f} vs yearly ${yearly_total:,.0f}: gap ${gap:,.0f} ({gap_pct:.2f}%)"
    if gap_pct > MONTHLY_GAP_FAIL_PCT:
        return Check(name, "FAIL", detail)
    if gap_pct > MONTHLY_GAP_WARN_PCT:
        return Check(name, "WARN", detail)
    return Check(name, "PASS", detail)


def check_vendor_names_match(data: dict[str, pd.DataFrame]) -> Check:
    name = "Monthly vendor names are known to the views"
    by_vendor = data["monthly_demand"].groupby("VendorName")["MonthlyRevenue"].sum()
    known = set(data["vw_VendorRevenueSummary"]["VendorName"])
    unknown = by_vendor[~by_vendor.index.isin(known)].sort_values(ascending=False)
    if unknown.empty:
        return Check(name, "PASS", "every monthly vendor name is in the views")
    share = unknown.sum() / by_vendor.sum() * 100
    detail = (
        f"{len(unknown)} vendor names in the monthly data are not in the yearly views, "
        f"${unknown.sum():,.0f} ({share:.2f}% of revenue); largest: {unknown.index[0]}"
    )
    return Check(name, "FAIL" if share > UNMATCHED_NAMES_FAIL_PCT else "WARN", detail)


def check_vendor_drift(data: dict[str, pd.DataFrame]) -> Check:
    name = "Each vendor's monthly total is close to its yearly total"
    monthly = data["monthly_demand"].groupby("VendorName")["MonthlyRevenue"].sum()
    yearly = data["vw_VendorRevenueSummary"].set_index("VendorName")["TotalRevenue"]
    both = pd.concat([monthly, yearly], axis=1, keys=["monthly", "yearly"]).dropna()
    both = both[both["yearly"] > 0]
    drift = ((both["monthly"] - both["yearly"]) / both["yearly"] * 100).abs()
    off = drift[drift > VENDOR_DRIFT_PCT].sort_values(ascending=False)
    if off.empty:
        return Check(name, "PASS", f"all {len(both)} matched vendors within {VENDOR_DRIFT_PCT:g}%")
    biggest = (both["monthly"] - both["yearly"]).abs().idxmax()
    gap = both.loc[biggest, "monthly"] - both.loc[biggest, "yearly"]
    return Check(
        name, "WARN",
        f"{len(off)} of {len(both)} vendors' monthly totals differ from their yearly totals by more "
        f"than {VENDOR_DRIFT_PCT:g}%; largest in dollars: {biggest} "
        f"(${abs(gap):,.0f} {'more' if gap > 0 else 'less'} in the monthly data)",
    )


ALL_CHECKS = (
    check_not_empty,
    check_vendor_views_agree,
    check_revenue_agrees,
    check_leakage_adds_up,
    check_blanks_are_explained,
    check_cleaned_base,
    check_monthly_complete,
    check_monthly_matches_yearly,
    check_vendor_names_match,
    check_vendor_drift,
)


def run_checks(data: dict[str, pd.DataFrame]) -> list[Check]:
    """Run every check. A check that crashes counts as a FAIL, so nothing slips through."""
    results = []
    for check in ALL_CHECKS:
        try:
            results.append(check(data))
        except Exception as error:  # e.g. a column was renamed in a view
            results.append(Check(check.__name__, "FAIL", f"could not run: {error!r}"))
    return results


def gate_passes(results: list[Check]) -> bool:
    return all(r.status != "FAIL" for r in results)


if __name__ == "__main__":
    results = run_checks(load_sources())
    for r in results:
        print(f"  {r.status:<4}  {r.name}\n        {r.detail}")
    counts = {s: sum(r.status == s for r in results) for s in ("PASS", "WARN", "FAIL")}
    print(f"\n{counts['PASS']} passed, {counts['WARN']} warnings, {counts['FAIL']} failed")
    if gate_passes(results):
        print("GATE OPEN: the pack may be built.")
    else:
        print("GATE CLOSED: fix the failures first. No pack will be built.")
        sys.exit(1)
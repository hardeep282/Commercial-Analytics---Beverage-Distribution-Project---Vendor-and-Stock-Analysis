"""
Out-of-sample backtest for the Excel demand forecast.

Why this exists
---------------
The Excel FORECAST tab fits FORECAST.ETS (seasonality = 12) on the same 12 months
it then scores, so its 9.84% MAPE is an in-sample fit, not forecast accuracy.
With only one year of history the seasonal component cannot be estimated
(Excel's gamma comes out at ~0), so the ETS projection reduces to a straight trend.

This script measures accuracy honestly: every forecast is made only from months
that came before it.

  * Rolling-origin, one month ahead: forecast Jul, Aug, ... Dec 2024, each from
    the months before it.
  * Three-month holdout: train on Jan-Sep 2024, forecast Oct-Dec 2024.

Data source: the `output_monthly_demand` sheet of the Excel workbook
(one row per SKU per month, calendar 2024).

Usage:  python forecast_backtest.py ["Excel Analysis/Vendor_Summary.xlsx"]
"""
import sys
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")

WORKBOOK = sys.argv[1] if len(sys.argv) > 1 else "Excel Analysis/Vendor_Summary.xlsx"
FLAGSHIP = "Jack Daniels No 7 Black"   # default SKU on the Excel FORECAST tab
TOP_N = 50                             # highest-volume SKUs for the portfolio-wide check
METHODS = ["Naive (last month)", "3-month MA", "6-month MA", "Linear trend", "Holt (damped trend)"]


def forecast(history, method, horizon):
    """Forecast `horizon` months ahead using only `history`."""
    y = np.asarray(history, dtype=float)
    if method == "Naive (last month)":
        return np.repeat(y[-1], horizon)
    if method == "3-month MA":
        return np.repeat(y[-3:].mean(), horizon)
    if method == "6-month MA":
        return np.repeat(y[-6:].mean(), horizon)
    if method == "Linear trend":
        slope, intercept = np.polyfit(np.arange(len(y)), y, 1)
        return intercept + slope * np.arange(len(y), len(y) + horizon)
    if method == "Holt (damped trend)":
        return ExponentialSmoothing(y, trend="add", damped_trend=True).fit().forecast(horizon)
    raise ValueError(method)


def mape(actual, predicted):
    actual, predicted = np.asarray(actual, float), np.asarray(predicted, float)
    return float(np.mean(np.abs(actual - predicted) / actual) * 100)


def rolling_one_step(y, method, first_origin=6):
    """Forecast month t from months 0..t-1, for t = first_origin..11 (Jul-Dec)."""
    preds = [forecast(y[:t], method, 1)[0] for t in range(first_origin, len(y))]
    return mape(y[first_origin:], preds)


def holdout(y, method, test=3):
    return mape(y[-test:], forecast(y[:-test], method, test))


def monthly(df, mask):
    s = df[mask].groupby("SalesMonth")["MonthlyDemand"].sum()
    return s.reindex(range(1, 13), fill_value=0).to_numpy(dtype=float)


def main():
    df = pd.read_excel(WORKBOOK, sheet_name="output_monthly_demand",
                       usecols=["Description", "SalesYear", "SalesMonth", "MonthlyDemand"])
    years = sorted(df["SalesYear"].unique())
    print(f"History: {len(years)} year(s) {years}, {df['SalesMonth'].nunique()} months, {len(df):,} SKU-month rows\n")

    rows = []
    for label, y in [(FLAGSHIP, monthly(df, df["Description"] == FLAGSHIP)),
                     ("Portfolio total", monthly(df, df["MonthlyDemand"].notna()))]:
        for m in METHODS:
            rows.append({"Series": label, "Method": m,
                         "Rolling 1-month MAPE % (Jul-Dec)": round(rolling_one_step(y, m), 1),
                         "Holdout MAPE % (train Jan-Sep, test Oct-Dec)": round(holdout(y, m), 1)})
    print(pd.DataFrame(rows).to_string(index=False))

    top = df.groupby("Description")["MonthlyDemand"].sum().nlargest(TOP_N).index
    scores = {m: [] for m in METHODS}
    for sku in top:
        y = monthly(df, df["Description"] == sku)
        if (y == 0).any():
            continue
        for m in METHODS:
            scores[m].append(rolling_one_step(y, m))
    n = len(scores[METHODS[0]])
    print(f"\nTop {TOP_N} SKUs by volume ({n} with sales every month): median rolling 1-month MAPE %")
    for m in METHODS:
        print(f"  {m:<22} {np.median(scores[m]):5.1f}")


if __name__ == "__main__":
    main()
